"""Persistent shared geo staging store for cross-run reuse."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from resolvekit.builder.sqlite.context import attached_db, connect_sqlite, transaction
from resolvekit.builder.sqlite.specs import insert_prefix
from resolvekit.builder.sqlite.write import ensure_sqlite_schema
from resolvekit.builder.utils import json_read, json_write, utc_now_iso

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - non-Unix fallback
    _fcntl = None  # type: ignore[assignment]


COVERAGE_UNITS: tuple[str, ...] = (
    "countries",
    "regions",
    "continental_unions",
    "continents",
    "admin1",
    "admin2",
    "admin3",
    "admin4",
    "admin5",
    "admin6",
    "cities",
)

UNIT_ENTITY_TYPE_MAP: dict[str, str] = {
    "countries": "geo.country",
    "regions": "geo.region",
    "continental_unions": "geo.continental_union",
    "continents": "geo.continent",
    "admin1": "geo.admin1",
    "admin2": "geo.admin2",
    "admin3": "geo.admin3",
    "admin4": "geo.admin4",
    "admin5": "geo.admin5",
    "admin6": "geo.admin6",
    "cities": "geo.city",
}

ENTITY_TYPE_TO_UNIT: dict[str, str] = {v: k for k, v in UNIT_ENTITY_TYPE_MAP.items()}

# Valid coverage-unit states.
UNIT_STATE_READY = "ready"
UNIT_STATE_REFRESHING = "refreshing"
UNIT_STATE_INVALID = "invalid"

GEO_TRANSITIVE_REQUIREMENTS: dict[str, set[str]] = {
    "regions": {"regions"},
    "continental_unions": {"continental_unions"},
    "continents": {"continents"},
    "countries": {"regions", "countries"},
    "cities": {
        "regions",
        "countries",
        "admin1",
        "admin2",
        "admin3",
        "admin4",
        "admin5",
        "admin6",
        "cities",
    },
}
for _index, _unit_name in enumerate(
    ("admin1", "admin2", "admin3", "admin4", "admin5", "admin6"),
    start=3,
):
    GEO_TRANSITIVE_REQUIREMENTS[_unit_name] = set(
        (
            "regions",
            "countries",
            "admin1",
            "admin2",
            "admin3",
            "admin4",
            "admin5",
            "admin6",
        )[:_index]
    )


def required_units_for_entity_types(entity_types: set[str]) -> set[str]:
    """Compute required coverage units (with transitive deps) for entity types."""
    direct = GeoSharedStore.entity_types_to_units(entity_types)
    expanded: set[str] = set()
    for unit in direct:
        expanded.update(GEO_TRANSITIVE_REQUIREMENTS.get(unit, {unit}))
    return expanded


_GEO_SHARED_THREAD_LOCK = threading.Lock()

SCHEMA_VERSION = 1


class CoverageUnit(BaseModel):
    """State of one coverage unit in the shared geo manifest."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str
    state: str = UNIT_STATE_INVALID
    run_id: str | None = None
    refreshed_at: str | None = None
    entity_count: int = 0


class GeoManifest(BaseModel):
    """Shared geo manifest schema (manifest.json, schema_version=1)."""

    # Not frozen — coverage dict is replaced wholesale via model_copy.
    model_config = ConfigDict(extra="ignore")

    schema_version: int = SCHEMA_VERSION
    source_instance: str | None = None
    last_refresh: str | None = None
    coverage: dict[str, CoverageUnit] = Field(default_factory=dict)


class GeoCoverageMeta(BaseModel):
    """Snapshot of geo coverage status persisted as `geo_shared_coverage` meta."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    required_units: list[str] = Field(default_factory=list)
    ready_units: list[str] = Field(default_factory=list)
    missing_units: list[str] = Field(default_factory=list)


class GeoSharedStore:
    """Manages the persistent shared geo staging store."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.db_path = root / "entities.sqlite"
        self.manifest_path = root / "manifest.json"
        self.lock_path = root / "lock"

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def ensure_paths(self) -> None:
        """Create shared geo directory structure and initialize manifest."""
        self.root.mkdir(parents=True, exist_ok=True)
        ensure_sqlite_schema(self.db_path)
        if not self.manifest_path.exists():
            self._write_manifest(self._default_manifest())

    # ------------------------------------------------------------------
    # Manifest helpers
    # ------------------------------------------------------------------

    def _default_manifest(self) -> GeoManifest:
        return GeoManifest(
            coverage={unit: CoverageUnit(name=unit) for unit in COVERAGE_UNITS}
        )

    def read_manifest(self) -> GeoManifest:
        """Return the typed shared geo manifest, falling back to defaults.

        Raises ``OSError`` if the manifest file can't be read,
        ``json.JSONDecodeError`` if its contents aren't valid JSON, and
        ``pydantic.ValidationError`` if the JSON doesn't match
        :class:`GeoManifest`'s schema.
        """
        raw = json_read(self.manifest_path, default=None)
        if raw is None:
            return self._default_manifest()
        return GeoManifest.model_validate(raw)

    def _write_manifest(self, manifest: GeoManifest) -> None:
        json_write(self.manifest_path, manifest.model_dump(mode="json"))

    def _mutate_manifest_unlocked(
        self,
        mutator: Callable[[GeoManifest], GeoManifest],
        *,
        update_last_refresh: bool = False,
    ) -> None:
        """Apply a manifest mutation while the caller already holds the write lock."""
        manifest = self.read_manifest()
        manifest = mutator(manifest)
        if update_last_refresh:
            manifest = manifest.model_copy(update={"last_refresh": utc_now_iso()})
        self._write_manifest(manifest)

    # ------------------------------------------------------------------
    # Coverage queries
    # ------------------------------------------------------------------

    def coverage_units(self) -> dict[str, CoverageUnit]:
        """Return all coverage units from the manifest."""
        manifest = self.read_manifest()
        return {
            unit_name: manifest.coverage.get(unit_name) or CoverageUnit(name=unit_name)
            for unit_name in COVERAGE_UNITS
        }

    def unit_state(self, unit_name: str) -> str:
        """Return the state of a specific coverage unit."""
        units = self.coverage_units()
        unit = units.get(unit_name)
        return unit.state if unit else UNIT_STATE_INVALID

    def ready_units(self) -> set[str]:
        """Return names of all coverage units in 'ready' state."""
        return {
            name
            for name, unit in self.coverage_units().items()
            if unit.state == UNIT_STATE_READY
        }

    def missing_units(self, required: set[str]) -> set[str]:
        """Return coverage units from *required* that are not ready."""
        ready = self.ready_units()
        return required - ready

    # ------------------------------------------------------------------
    # Coverage-unit resolution from entity types
    # ------------------------------------------------------------------

    @staticmethod
    def entity_types_to_units(entity_types: set[str]) -> set[str]:
        """Map canonical geo entity types to coverage unit names."""
        units: set[str] = set()
        for entity_type in entity_types:
            unit = ENTITY_TYPE_TO_UNIT.get(entity_type)
            if unit is not None:
                units.add(unit)
        return units

    @staticmethod
    def units_to_entity_types(unit_names: set[str]) -> set[str]:
        """Map coverage unit names to canonical geo entity types."""
        return {
            UNIT_ENTITY_TYPE_MAP[name]
            for name in unit_names
            if name in UNIT_ENTITY_TYPE_MAP
        }

    # ------------------------------------------------------------------
    # Refresh lifecycle
    # ------------------------------------------------------------------

    def _update_unit(
        self,
        unit_name: str,
        updater: Callable[[CoverageUnit], CoverageUnit],
        *,
        update_last_refresh: bool = False,
    ) -> None:
        """Read-modify-write a single coverage unit under lock."""
        with self._write_lock():
            self._update_unit_unlocked(
                unit_name,
                updater,
                update_last_refresh=update_last_refresh,
            )

    def _update_unit_unlocked(
        self,
        unit_name: str,
        updater: Callable[[CoverageUnit], CoverageUnit],
        *,
        update_last_refresh: bool = False,
    ) -> None:
        """Read-modify-write a single coverage unit while already locked."""

        def _apply(manifest: GeoManifest) -> GeoManifest:
            current = manifest.coverage.get(unit_name) or CoverageUnit(name=unit_name)
            new_coverage = {**manifest.coverage, unit_name: updater(current)}
            return manifest.model_copy(update={"coverage": new_coverage})

        self._mutate_manifest_unlocked(_apply, update_last_refresh=update_last_refresh)

    def mark_refreshing(
        self, unit_name: str, run_id: str, *, locked: bool = False
    ) -> None:
        """Mark a coverage unit as being refreshed by *run_id*."""
        update = self._update_unit_unlocked if locked else self._update_unit
        update(
            unit_name,
            lambda u: u.model_copy(
                update={"state": UNIT_STATE_REFRESHING, "run_id": run_id}
            ),
        )

    def mark_ready(
        self,
        unit_name: str,
        run_id: str,
        entity_count: int = 0,
        *,
        locked: bool = False,
    ) -> None:
        """Mark a coverage unit as ready after successful refresh."""
        update = self._update_unit_unlocked if locked else self._update_unit
        update(
            unit_name,
            lambda u: u.model_copy(
                update={
                    "state": UNIT_STATE_READY,
                    "run_id": run_id,
                    "refreshed_at": utc_now_iso(),
                    "entity_count": entity_count,
                }
            ),
            update_last_refresh=True,
        )

    def mark_invalid(self, unit_name: str) -> None:
        """Mark a coverage unit as invalid (must be rebuilt before use)."""
        self._update_unit(
            unit_name,
            lambda u: u.model_copy(
                update={"state": UNIT_STATE_INVALID, "run_id": None}
            ),
        )

    def set_source_instance(self, source_instance: str) -> None:
        """Record the source instance used for shared geo data."""
        with self._write_lock():
            manifest = self.read_manifest()
            if (
                manifest.source_instance is not None
                and manifest.source_instance != source_instance
            ):
                # Source changed — invalidate all coverage.
                invalidated = {
                    name: u.model_copy(
                        update={"state": UNIT_STATE_INVALID, "run_id": None}
                    )
                    for name, u in manifest.coverage.items()
                }
                manifest = manifest.model_copy(
                    update={
                        "source_instance": source_instance,
                        "coverage": invalidated,
                    }
                )
            else:
                manifest = manifest.model_copy(
                    update={"source_instance": source_instance}
                )
            self._write_manifest(manifest)

    def can_claim_refresh(self, unit_name: str, run_id: str) -> bool:
        """Check whether *run_id* may claim the refresh for *unit_name*.

        Returns True if the unit is not ready, or if the unit is stuck in
        'refreshing' by a different run (stale ownership recovery).
        """
        units = self.coverage_units()
        unit = units.get(unit_name)
        if unit is None:
            return True
        if unit.state == UNIT_STATE_READY:
            return False
        if unit.state == UNIT_STATE_REFRESHING and unit.run_id == run_id:
            return True  # already owned by this run
        # invalid or stale refreshing — claimable
        return True

    # ------------------------------------------------------------------
    # Interruption-safe merge
    # ------------------------------------------------------------------

    def merge_temp_db(self, temp_db_path: Path, unit_name: str) -> int:
        """Merge validated temporary staging DB into the shared store.

        Only entities matching *unit_name*'s entity type are merged.
        Returns the count of entities merged.
        """
        entity_type = UNIT_ENTITY_TYPE_MAP.get(unit_name)
        if entity_type is None:
            return 0

        with connect_sqlite(self.db_path, busy_timeout_ms=30000) as conn:
            conn.execute("ATTACH DATABASE ? AS temp_src", (str(temp_db_path),))
            try:
                with transaction(conn):
                    # Snapshot old entity IDs for this type so we can
                    # detect which ones are dropped after the refresh.
                    conn.execute(
                        """
                        CREATE TEMP TABLE IF NOT EXISTS _old_ids(
                            entity_id TEXT PRIMARY KEY
                        )
                        """
                    )
                    conn.execute("DELETE FROM _old_ids")
                    conn.execute(
                        """
                        INSERT INTO _old_ids(entity_id)
                        SELECT entity_id FROM entities
                        WHERE entity_type = ?
                        """,
                        (entity_type,),
                    )

                    # Remove existing entities for this unit type before merge.
                    for table in ("names", "codes", "relations"):
                        conn.execute(
                            f"""
                            DELETE FROM {table} WHERE entity_id IN (
                                SELECT entity_id FROM _old_ids
                            )
                            """
                        )
                    conn.execute(
                        "DELETE FROM entities WHERE entity_type = ?",
                        (entity_type,),
                    )

                    # Copy entities of the target type with explicit column lists
                    # (physical column order matches the frozen schema).
                    conn.execute(
                        insert_prefix("entities")
                        + """
                        SELECT
                            e.entity_id, e.entity_type, e.canonical_name,
                            e.canonical_name_norm, e.valid_from, e.valid_until,
                            e.attrs_json
                        FROM temp_src.entities e
                        WHERE e.entity_type = ?
                        """,
                        (entity_type,),
                    )
                    conn.execute(
                        insert_prefix("names")
                        + """
                        SELECT
                            n.entity_id, n.name_kind, n.value, n.value_norm,
                            n.lang, n.script, n.is_preferred
                        FROM temp_src.names n
                        INNER JOIN temp_src.entities e
                            ON e.entity_id = n.entity_id
                        WHERE e.entity_type = ?
                        """,
                        (entity_type,),
                    )
                    conn.execute(
                        insert_prefix("codes")
                        + """
                        SELECT
                            c.entity_id, c.system, c.value, c.value_norm
                        FROM temp_src.codes c
                        INNER JOIN temp_src.entities e
                            ON e.entity_id = c.entity_id
                        WHERE e.entity_type = ?
                        """,
                        (entity_type,),
                    )
                    conn.execute(
                        insert_prefix("relations")
                        + """
                        SELECT
                            r.entity_id, r.relation_type, r.target_id,
                            r.valid_from, r.valid_until
                        FROM temp_src.relations r
                        INNER JOIN temp_src.entities e
                            ON e.entity_id = r.entity_id
                        WHERE e.entity_type = ?
                        """,
                        (entity_type,),
                    )

                    # Clean up cross-unit relations targeting entities
                    # that existed in this unit before but were dropped.
                    conn.execute(
                        """
                        DELETE FROM relations
                        WHERE target_id IN (
                            SELECT entity_id FROM _old_ids
                            WHERE entity_id NOT IN (
                                SELECT entity_id FROM entities
                            )
                        )
                        """
                    )

                    row = conn.execute(
                        "SELECT COUNT(*) FROM entities WHERE entity_type = ?",
                        (entity_type,),
                    ).fetchone()
                    count = int(row[0]) if row else 0
            finally:
                conn.execute("DETACH DATABASE temp_src")

        return count

    def entity_count_for_unit(self, unit_name: str) -> int:
        """Count entities in the shared store matching a coverage unit type."""
        entity_type = UNIT_ENTITY_TYPE_MAP.get(unit_name)
        if entity_type is None:
            return 0
        with connect_sqlite(self.db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM entities WHERE entity_type = ?",
                (entity_type,),
            ).fetchone()
            return int(row[0]) if row else 0

    def copy_entities_to_db(
        self,
        entity_ids: set[str],
        target_db_path: Path,
    ) -> set[str]:
        """Copy cached entities into a target staging DB via ATTACH.

        Returns the set of entity IDs that were actually found and copied.
        """
        if not entity_ids or not self.db_path.exists():
            return set()

        with (
            connect_sqlite(target_db_path, busy_timeout_ms=30000) as conn,
            attached_db(conn, alias="shared_src", db_path=self.db_path),
        ):
            conn.execute(
                "CREATE TEMP TABLE IF NOT EXISTS _requested_ids"
                "(entity_id TEXT PRIMARY KEY)"
            )
            conn.execute("DELETE FROM _requested_ids")
            conn.executemany(
                "INSERT OR IGNORE INTO _requested_ids(entity_id) VALUES (?)",
                [(eid,) for eid in entity_ids],
            )

            found_ids = {
                str(row[0])
                for row in conn.execute(
                    "SELECT r.entity_id FROM _requested_ids r "
                    "INNER JOIN shared_src.entities e "
                    "ON e.entity_id = r.entity_id"
                )
            }

            if not found_ids:
                return set()

            with transaction(conn):
                conn.execute(
                    insert_prefix("entities") + " SELECT"
                    " e.entity_id, e.entity_type, e.canonical_name,"
                    " e.canonical_name_norm, e.valid_from, e.valid_until,"
                    " e.attrs_json"
                    " FROM shared_src.entities e"
                    " INNER JOIN _requested_ids r ON r.entity_id = e.entity_id"
                )
                conn.execute(
                    insert_prefix("names") + " SELECT"
                    " n.entity_id, n.name_kind, n.value, n.value_norm,"
                    " n.lang, n.script, n.is_preferred"
                    " FROM shared_src.names n"
                    " INNER JOIN _requested_ids r ON r.entity_id = n.entity_id"
                )
                conn.execute(
                    insert_prefix("codes") + " SELECT"
                    " c.entity_id, c.system, c.value, c.value_norm"
                    " FROM shared_src.codes c"
                    " INNER JOIN _requested_ids r ON r.entity_id = c.entity_id"
                )
                conn.execute(
                    insert_prefix("relations") + " SELECT"
                    " rl.entity_id, rl.relation_type, rl.target_id,"
                    " rl.valid_from, rl.valid_until"
                    " FROM shared_src.relations rl"
                    " INNER JOIN _requested_ids r ON r.entity_id = rl.entity_id"
                )

        return found_ids

    def query_entity_ids_by_type(self, entity_type: str) -> list[str]:
        """Return sorted entity IDs for a given entity_type from the shared store."""
        if not self.db_path.exists():
            return []
        with connect_sqlite(self.db_path) as conn:
            rows = conn.execute(
                "SELECT entity_id FROM entities WHERE entity_type = ? "
                "ORDER BY entity_id",
                (entity_type,),
            ).fetchall()
        return [str(row[0]) for row in rows]

    # ------------------------------------------------------------------
    # Locking
    # ------------------------------------------------------------------

    @contextmanager
    def _write_lock(self) -> Iterator[None]:
        """Serialize manifest writes across threads and processes."""
        with _GEO_SHARED_THREAD_LOCK:
            if _fcntl is None:
                yield
                return
            self.root.mkdir(parents=True, exist_ok=True)
            with self.lock_path.open("a+", encoding="utf-8") as handle:
                _fcntl.flock(handle.fileno(), _fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    _fcntl.flock(handle.fileno(), _fcntl.LOCK_UN)

    @contextmanager
    def refresh_lock(self) -> Iterator[None]:
        """Acquire the shared geo write lock for a refresh operation."""
        with self._write_lock():
            yield

    # ------------------------------------------------------------------
    # Temporary staging DB for interruption-safe refresh
    # ------------------------------------------------------------------

    @contextmanager
    def temp_staging_db(self) -> Iterator[Path]:
        """Create a temporary staging DB for isolated unit refresh.

        The caller materializes data into this DB, validates it, and then
        calls :meth:`merge_temp_db` to atomically merge into the shared store.
        The temporary DB is cleaned up on exit.
        """
        temp_name = f".temp_refresh_{uuid.uuid4().hex}.sqlite"
        temp_path = self.root / temp_name
        try:
            yield temp_path
        finally:
            for suffix in ("", "-wal", "-shm"):
                candidate = temp_path.parent / (temp_path.name + suffix)
                if candidate.exists():
                    candidate.unlink(missing_ok=True)
