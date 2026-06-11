"""Base builder for DataPacks."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from resolvekit.core.datapack import ENTITY_SCHEMA_VERSION, NORMALIZER_VERSION, DataPackMetadata
from resolvekit.shared.build.schema import SCHEMA_SQL

if TYPE_CHECKING:
    from resolvekit.core.linking.linker import LinkResult
    from resolvekit.core.store.interface import EntityStore


class BaseDataPackBuilder:
    """Base class for builder DataPack artifacts.

    Creates:
    - SQLite database with entities, names, codes, relations
    - FTS5 index for full-text search
    - Optional SymSpell dictionary
    - metadata.json with versioning info
    """

    DOMAIN_PACK_ID: str | None = None
    FEATURE_SCHEMA_VERSION: str | None = None

    SCHEMA_SQL = SCHEMA_SQL

    def __init__(self, output_dir: str | Path) -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._db_path: Path | None = None
        self._conn: sqlite3.Connection | None = None
        self._base_store: EntityStore | None = None
        self._linker: Any = None
        self._normalizer: Any = None
        # Track entity_ids written in this build: when a row links to an
        # entity already seen (e.g. two input rows for one base entity), skip
        # add_entity — the canonical name and type from the first occurrence
        # win. Codes and names still accumulate onto the entity.
        self._written_entity_ids: set[str] = set()

    def set_base_modules(self, base_paths: Sequence[str | Path]) -> None:
        """Configure base modules for overlay linking."""
        raise NotImplementedError(
            "set_base_modules() must be implemented by subclasses"
        )

    def create_database(self, db_name: str = "entities.sqlite") -> Path:
        """Create SQLite database with schema."""
        self._db_path = self._output_dir / db_name
        self._conn = sqlite3.connect(self._db_path)
        # Enable foreign key enforcement
        self._conn.execute("PRAGMA foreign_keys=ON")
        # Write-optimized pragmas for bulk inserts
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA cache_size=-64000")  # 64MB
        self._conn.execute("PRAGMA temp_store=MEMORY")
        self._conn.executescript(self.SCHEMA_SQL)
        self._conn.commit()
        self._written_entity_ids = set()
        return self._db_path

    def add_entity(
        self,
        entity_id: str,
        entity_type: str,
        canonical_name: str,
        canonical_name_norm: str,
        valid_from: str | None = None,
        valid_until: str | None = None,
        attrs: dict[str, Any] | None = None,
    ) -> None:
        """Add an entity to the database."""
        if not self._conn:
            raise RuntimeError("Database not created. Call create_database first.")

        self._conn.execute(
            """
            INSERT INTO entities (
                entity_id, entity_type, canonical_name, canonical_name_norm,
                valid_from, valid_until, attrs_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity_id,
                entity_type,
                canonical_name,
                canonical_name_norm,
                valid_from,
                valid_until,
                json.dumps(attrs) if attrs else None,
            ),
        )

        self._conn.execute(
            """
            INSERT INTO names (
                entity_id, name_kind, value, value_norm, lang, script, is_preferred
            ) VALUES (?, 'canonical', ?, ?, '', '', 1)
            """,
            (entity_id, canonical_name, canonical_name_norm),
        )

    def add_name(
        self,
        entity_id: str,
        name_kind: str,
        value: str,
        value_norm: str,
        lang: str | None = None,
        script: str | None = None,
        is_preferred: bool = False,
    ) -> None:
        """Add a name variant to the database."""
        if not self._conn:
            raise RuntimeError("Database not created. Call create_database first.")

        self._conn.execute(
            """
            INSERT INTO names (
                entity_id, name_kind, value, value_norm, lang, script, is_preferred
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity_id,
                name_kind,
                value,
                value_norm,
                lang or "",
                script or "",
                int(is_preferred),
            ),
        )

    def add_code(
        self,
        entity_id: str,
        system: str,
        value: str,
        value_norm: str,
    ) -> None:
        """Add a code identifier to the database."""
        if not self._conn:
            raise RuntimeError("Database not created. Call create_database first.")

        self._conn.execute(
            """
            INSERT OR REPLACE INTO codes (entity_id, system, value, value_norm)
            VALUES (?, ?, ?, ?)
            """,
            (entity_id, system, value, value_norm),
        )

    def add_relation(
        self,
        entity_id: str,
        relation_type: str,
        target_id: str,
        *,
        valid_from: str | None = None,
        valid_until: str | None = None,
    ) -> None:
        """Add a relation to the database.

        Args:
            entity_id: Source entity ID.
            relation_type: Relation type (e.g., "member_of", "contained_in").
            target_id: Target entity ID.
            valid_from: ISO-8601 date string (nullable; "always valid from start" when None).
            valid_until: ISO-8601 date string (nullable; "no expiry" when None).
                Half-open right: a country with ``valid_until="2020-02-01"`` is a
                member through 2020-01-31 and not from 2020-02-01 onward.
        """
        if not self._conn:
            raise RuntimeError("Database not created. Call create_database first.")

        self._conn.execute(
            """
            INSERT INTO relations (entity_id, relation_type, target_id, valid_from, valid_until)
            VALUES (?, ?, ?, ?, ?)
            """,
            (entity_id, relation_type, target_id, valid_from, valid_until),
        )

    def finalize(self) -> None:
        """Finalize the database by rebuilding FTS index."""
        if not self._conn:
            raise RuntimeError("Database not created. Call create_database first.")

        # Rebuild FTS index from names table
        self._conn.execute(
            """
            INSERT INTO names_fts(names_fts) VALUES('rebuild')
            """
        )
        self._conn.commit()

    def _build_metadata(
        self,
        *,
        pack_type: Literal["base", "overlay"],
        datapack_id: str,
        source_datasets: list[str],
        domain_pack_id: str | None,
        feature_schema_version: str | None,
        module_id: str | None,
        module_dependencies: list[str] | None,
        link_keys: list[str] | None = None,
        base_module_ids: list[str] | None = None,
        allow_new_entities: bool = False,
    ) -> dict[str, Any]:
        """Construct, write, and return the DataPackMetadata dict for either pack type."""
        pack_id = domain_pack_id or self.DOMAIN_PACK_ID
        if pack_id is None:
            raise ValueError("domain_pack_id must be provided for this builder")

        overlay_kwargs: dict[str, Any] = (
            {
                "link_keys": link_keys,
                "base_module_ids": base_module_ids,
                "allow_new_entities": allow_new_entities,
            }
            if pack_type == "overlay"
            else {}
        )

        metadata = DataPackMetadata(
            datapack_id=datapack_id,
            module_id=module_id or datapack_id,
            domain_pack_id=pack_id,
            module_dependencies=module_dependencies or [],
            entity_schema_version=ENTITY_SCHEMA_VERSION,
            feature_schema_version=feature_schema_version
            or self.FEATURE_SCHEMA_VERSION
            or f"{pack_id}.features.v1",
            normalizer_version=NORMALIZER_VERSION,
            index_versions={
                "fts": "fts5",
                "symspell": None,
            },
            build_timestamp=_utc_now_iso(),
            source_datasets=source_datasets,
            pack_type=pack_type,
            store_type="sqlite",
            store_file="entities.sqlite",
            **overlay_kwargs,
        )
        metadata.to_file(self._output_dir / "metadata.json")
        return metadata.model_dump(mode="python")

    def build_metadata(
        self,
        datapack_id: str,
        source_datasets: list[str],
        domain_pack_id: str | None = None,
        feature_schema_version: str | None = None,
        module_id: str | None = None,
        module_dependencies: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build metadata for the datapack."""
        return self._build_metadata(
            pack_type="base",
            datapack_id=datapack_id,
            source_datasets=source_datasets,
            domain_pack_id=domain_pack_id,
            feature_schema_version=feature_schema_version,
            module_id=module_id,
            module_dependencies=module_dependencies,
        )

    def build_overlay_metadata(
        self,
        datapack_id: str,
        source_datasets: list[str],
        link_keys: list[str],
        base_module_ids: list[str] | None = None,
        domain_pack_id: str | None = None,
        feature_schema_version: str | None = None,
        allow_new_entities: bool = False,
        module_id: str | None = None,
        module_dependencies: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build metadata for an overlay datapack.

        Args:
            datapack_id: Unique identifier for this overlay pack.
            domain_pack_id: Domain pack this overlay belongs to (e.g., "geo").
            base_module_ids: Module IDs in the base composition this overlay extends.
            source_datasets: List of source dataset identifiers.
            link_keys: Code systems used for entity linking (e.g., ["iso3"]).
            feature_schema_version: Optional schema version override.
            allow_new_entities: Whether this overlay can introduce new entities.

        Returns:
            The metadata dict that was written to metadata.json.

        Raises:
            ValueError: If base_module_ids is empty.
        """
        resolved_base_module_ids = list(base_module_ids or [])
        resolved_base_module_ids = list(dict.fromkeys(resolved_base_module_ids))

        if not resolved_base_module_ids:
            raise ValueError("base_module_ids must not be empty")

        return self._build_metadata(
            pack_type="overlay",
            datapack_id=datapack_id,
            source_datasets=source_datasets,
            domain_pack_id=domain_pack_id,
            feature_schema_version=feature_schema_version,
            module_id=module_id,
            module_dependencies=module_dependencies,
            link_keys=link_keys,
            base_module_ids=resolved_base_module_ids,
            allow_new_entities=allow_new_entities,
        )

    def _open_base_stores(self, base_paths: Sequence[str | Path]) -> None:
        """Open read-only stores for a base module composition."""
        from resolvekit.core.store import CompositeStore
        from resolvekit.core.store.sqlite import SQLiteEntityStore, SQLiteTuning

        single_conn_tuning = SQLiteTuning(pool_size=1)
        stores = [
            SQLiteEntityStore(
                Path(base_path) / _read_store_file(Path(base_path)),
                tuning=single_conn_tuning,
            )
            for base_path in base_paths
        ]
        if not stores:
            raise ValueError("base_paths must not be empty")
        if len(stores) == 1:
            self._base_store = stores[0]
            return
        self._base_store = CompositeStore(stores)

    def _write_row(
        self,
        entity_id: str,
        codes: dict[str, str],
        names: list[dict] | None,
        attrs: dict[str, Any] | None,
        *,
        canonical_name: str,
        canonical_name_norm: str,
        entity_type: str,
        valid_from: str | None,
        valid_until: str | None,
    ) -> None:
        """Write entity, codes, and names to the database.

        Used by both linked and minted paths in ``link_and_add``.
        Requires ``_normalizer`` to be set and ``_conn`` to be open.

        If *entity_id* was already written (e.g. two rows link to the same base
        entity), skip the entity insert — first occurrence's canonical name and
        type are preserved — but still accumulate codes and names from this row.
        """
        if entity_id not in self._written_entity_ids:
            self.add_entity(
                entity_id=entity_id,
                entity_type=entity_type,
                canonical_name=canonical_name,
                canonical_name_norm=canonical_name_norm,
                valid_from=valid_from,
                valid_until=valid_until,
                attrs=attrs,
            )
            self._written_entity_ids.add(entity_id)

        for system, value in codes.items():
            norm_value = self._normalizer.normalize_code(system, value)
            self.add_code(
                entity_id=entity_id,
                system=system,
                value=value,
                value_norm=norm_value,
            )

        if names:
            for name in names:
                self.add_name(
                    entity_id=entity_id,
                    name_kind=name["name_kind"],
                    value=name["value"],
                    value_norm=name["value_norm"],
                    lang=name.get("lang"),
                    script=name.get("script"),
                    is_preferred=name.get("is_preferred", False),
                )

    def link_and_add(
        self,
        codes: dict[str, str],
        canonical_name: str | None = None,
        canonical_name_norm: str | None = None,
        entity_type: str | None = None,
        valid_from: str | None = None,
        valid_until: str | None = None,
        attrs: dict[str, Any] | None = None,
        names: list[dict] | None = None,
        link_keys: list[str] | None = None,
        *,
        name_value_norm: str | None = None,
        valid_systems: frozenset[str] | None = None,
        on_miss: Literal["mint", "skip", "error"] = "skip",
        mint_entity_id: str | None = None,
    ) -> LinkResult:
        """Resolve codes to a base entity_id via linker, then add overlay data.

        Requires ``_normalizer`` to always be set (for code/name normalisation).
        ``_base_store`` and ``_linker`` may be ``None`` only when minting
        without linking: ``on_miss="mint"`` and ``link_keys`` empty or ``None``.
        Any call with non-empty ``link_keys`` but missing base storage raises.

        Args:
            codes: Code values to resolve (e.g., {"iso3": "FRA"}).
            canonical_name: Override canonical name (fetched from base if None
                and a base store is available; required when minting without a
                base).
            canonical_name_norm: Normalised canonical name.  Computed from
                ``canonical_name`` when ``None`` and a normaliser is available.
            entity_type: Override entity type (fetched from base if None and a
                base store is available).
            valid_from: Temporal validity start (ISO date string).
            valid_until: Temporal validity end (ISO date string).
            attrs: Attributes to set on the overlay entity.
            names: Additional name dicts to add (each with keys: name_kind,
                value, value_norm, and optionally lang, script, is_preferred).
            link_keys: Ordered list of systems to try for resolution.  If
                ``None`` or empty and ``on_miss="mint"``, the row is minted
                without linking.  If ``None`` or empty with any other
                ``on_miss``, behaves like the old single-key-free path (tries
                all codes keys).
            name_value_norm: Normalised canonical name used when ``"name"`` is
                in ``link_keys`` (the ``"name"`` strategy performs an exact
                normalised-name lookup on the base store).
            valid_systems: Pre-computed ``frozenset`` of accepted code systems
                passed through to ``resolve_link`` (avoids a per-row
                ``SELECT DISTINCT``).
            on_miss: Behaviour when resolution fails.
                ``"skip"`` — return the failure ``LinkResult`` unchanged.
                ``"error"`` — raise ``ValueError``.
                ``"mint"`` — create a new entity using ``mint_entity_id``.
            mint_entity_id: Entity ID to use when minting a new entity
                (required when ``on_miss="mint"``).

        Returns:
            LinkResult indicating success or failure.  On a mint, returns a
            synthetic ``LinkResult.linked(mint_entity_id)``.

        Raises:
            RuntimeError: If ``_normalizer`` is not set, or if ``_base_store``
                / ``_linker`` are ``None`` but ``link_keys`` is non-empty.
            ValueError: If ``on_miss="error"`` and resolution fails.
        """
        if self._normalizer is None:
            raise RuntimeError(
                "Base modules not set. Call set_base_modules() before link_and_add()."
            )
        if not self._conn:
            raise RuntimeError("Database not created. Call create_database first.")

        # Pure-mint path: no base needed when link_keys is empty and on_miss=mint.
        has_link_keys = bool(link_keys)
        pure_mint = on_miss == "mint" and not has_link_keys

        if not pure_mint and (self._base_store is None or self._linker is None):
            raise RuntimeError(
                "Base modules not set. Call set_base_modules() before link_and_add()."
            )

        from resolvekit.core.linking.linker import LinkResult

        if pure_mint:
            result: LinkResult = LinkResult.not_found("Pure-mint path: no link keys")
        else:
            # Normalise code values before passing to linker
            normalized_codes = {
                system: self._normalizer.normalize_code(system, value)
                for system, value in codes.items()
            }

            # Inject the normalised name for the "name" strategy
            if name_value_norm is not None:
                normalized_codes["__name__"] = name_value_norm

            resolve_keys = list(link_keys) if link_keys else list(codes.keys())

            result = cast(
                "LinkResult",
                self._linker.resolve_link(
                    normalized_codes,
                    resolve_keys,
                    self._base_store,
                    valid_systems=valid_systems,
                ),
            )

        if result.is_success:
            entity_id = result.entity_id
            if entity_id is None:
                raise RuntimeError(
                    "Successful link result did not include an entity_id"
                )

            # Fetch base entity data for defaults when not supplied
            if (
                canonical_name is None or entity_type is None
            ) and self._base_store is not None:
                base_entity = self._base_store.get_entity(entity_id)
                if base_entity is not None:
                    if canonical_name is None:
                        canonical_name = base_entity.canonical_name
                        canonical_name_norm = base_entity.canonical_name_norm
                    if entity_type is None:
                        entity_type = base_entity.entity_type

            if canonical_name is None or entity_type is None:
                raise RuntimeError(
                    f"Could not determine canonical_name/entity_type for {entity_id}"
                )

            if canonical_name_norm is None:
                canonical_name_norm = self._normalizer.normalize_name(canonical_name)

            self._write_row(
                entity_id=entity_id,
                codes=codes,
                names=names,
                attrs=attrs,
                canonical_name=canonical_name,
                canonical_name_norm=canonical_name_norm,
                entity_type=entity_type,
                valid_from=valid_from,
                valid_until=valid_until,
            )
            return result

        # Resolution failed — apply on_miss policy
        if on_miss == "error":
            raise ValueError(
                f"Entity linking failed ({result.status}): {result.message}"
            )

        if on_miss == "mint":
            if mint_entity_id is None:
                raise ValueError("mint_entity_id must be provided when on_miss='mint'")

            if canonical_name is None:
                raise RuntimeError(
                    "canonical_name is required for minting (no base to fetch from)"
                )

            if canonical_name_norm is None:
                canonical_name_norm = self._normalizer.normalize_name(canonical_name)

            if entity_type is None:
                entity_type = "custom"

            self._write_row(
                entity_id=mint_entity_id,
                codes=codes,
                names=names,
                attrs=attrs,
                canonical_name=canonical_name,
                canonical_name_norm=canonical_name_norm,
                entity_type=entity_type,
                valid_from=valid_from,
                valid_until=valid_until,
            )
            return LinkResult.linked(mint_entity_id)

        # on_miss == "skip": return the failure result unchanged
        return result

    def commit(self) -> None:
        """Commit current transaction. Call periodically for large imports."""
        if self._conn:
            self._conn.commit()

    def close(self) -> None:
        """Close the database connection and base store."""
        if self._base_store:
            self._base_store.close()
            self._base_store = None
        if self._conn:
            self._conn.commit()
            self._conn.close()
            self._conn = None

    def __enter__(self) -> BaseDataPackBuilder:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        if exc_type is None:
            self.commit()
        self.close()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _read_store_file(base_path: Path) -> str:
    metadata_path = base_path / "metadata.json"
    if not metadata_path.is_file():
        return "entities.sqlite"

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    store_file = payload.get("store_file")
    if isinstance(store_file, str) and store_file.strip():
        return store_file
    return "entities.sqlite"
