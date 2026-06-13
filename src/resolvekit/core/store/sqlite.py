"""SQLite implementation of EntityStore."""

import contextlib
import functools
import json
import logging
import sqlite3
from collections import defaultdict
from collections.abc import Generator, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from queue import Empty, Queue
from threading import Lock
from typing import Any, override
from urllib.parse import quote

from resolvekit.core.model import (
    CodeRecord,
    EntityRecord,
    NameRecord,
    RelationRecord,
)
from resolvekit.core.store.interface import EntityStore
from resolvekit.core.store.sqlite_helpers import (
    escape_fts5_query,
    escape_fts5_query_tokens,
)
from resolvekit.core.util.normalization import fold_for_match

logger = logging.getLogger(__name__)

_BULK_CHUNK_SIZE = 500


@dataclass(frozen=True)
class SQLiteTuning:
    """Per-Resolver SQLite connection tuning parameters.

    Controls connection pool size and per-connection memory budgets.
    One instance is shared across all stores opened by a single Resolver.

    Attributes:
        pool_size: Number of pooled connections per store. Reduce to 1 for
            single-threaded notebooks; raise for highly concurrent workloads.
        cache_size_mb: SQLite page cache size in megabytes (``PRAGMA cache_size``).
        mmap_size_mb: Memory-mapped I/O window in megabytes (``PRAGMA mmap_size``).
            Set to 0 to disable mmap entirely (relies on the page cache only).
    """

    pool_size: int = 2
    cache_size_mb: int = 64
    mmap_size_mb: int = 128

    def __post_init__(self) -> None:
        if self.pool_size < 1:
            raise ValueError(f"pool_size must be >= 1, got {self.pool_size}")
        if self.cache_size_mb < 1:
            raise ValueError(f"cache_size_mb must be >= 1, got {self.cache_size_mb}")
        if self.mmap_size_mb < 0:
            raise ValueError(f"mmap_size_mb must be >= 0, got {self.mmap_size_mb}")


def _chunked(lst: list[str], size: int) -> Generator[list[str], None, None]:
    """Yield successive chunks of the given size."""
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


def _group_rows_by_entity(
    rows: Iterable[sqlite3.Row], key: str = "entity_id"
) -> dict[str, list[sqlite3.Row]]:
    """Group rows by entity_id into a dict of lists."""
    grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        grouped[row[key]].append(row)
    return grouped


class SQLiteEntityStore(EntityStore):
    """SQLite-backed entity store.

    Provides efficient lookups using:
    - Indexed code lookups
    - Indexed exact name lookups
    - FTS5 full-text search

    Features:
    - Connection pooling for improved throughput
    - Optimized SQLite pragmas (WAL mode, appropriate cache size)
    """

    DEFAULT_POOL_SIZE = (
        2  # exported for callers; authoritative default lives in SQLiteTuning
    )

    def __init__(
        self,
        db_path: str | Path,
        *,
        tuning: SQLiteTuning | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        if not self._db_path.exists():
            raise FileNotFoundError(f"Database not found: {db_path}")

        self._tuning = tuning if tuning is not None else SQLiteTuning()

        # Connection pool
        self._pool: Queue[sqlite3.Connection] = Queue(maxsize=self._tuning.pool_size)
        self._pool_size = self._tuning.pool_size
        self._pool_lock = Lock()
        self._initialized = False
        self._closed = False
        self._open_read_only = False

        # Initialize the pool
        self._init_pool()

        # Per-instance LRU cache for get_entity lookups
        self._get_entity_cached = functools.lru_cache(maxsize=4096)(
            self._get_entity_uncached
        )

        # One-time FTS5 availability check
        self._has_fts = self._check_fts5_available()

    def _check_fts5_available(self) -> bool:
        """Check if the names_fts FTS5 table exists in the database."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='names_fts'"
            ).fetchone()
            return row is not None

    def _init_pool(self) -> None:
        """Initialize connection pool with optimized connections."""
        # Migrate the relations table to add temporal columns if missing.
        # Idempotent and harmless on already-migrated DBs; required for
        # legacy datapacks (and inline test fixtures) that predate the
        # schema delta.
        self._migrate_relations_temporal_if_writable()

        for _ in range(self._pool_size):
            conn = self._create_connection()
            self._pool.put(conn)
        self._initialized = True

    def _migrate_relations_temporal_if_writable(self) -> None:
        """Add valid_from/valid_until to relations on legacy DBs (best-effort).

        Sets self._relations_has_temporal so query paths can fall back to
        a NULL-projecting SELECT on truly read-only legacy DBs.
        """
        self._relations_has_temporal = False
        try:
            conn = sqlite3.connect(self._db_path)
        except sqlite3.OperationalError:
            return
        try:
            existing = {
                row[1]
                for row in conn.execute("PRAGMA table_info(relations)").fetchall()
            }
            if "valid_from" in existing and "valid_until" in existing:
                self._relations_has_temporal = True
                return
            for col in ("valid_from", "valid_until"):
                if col in existing:
                    continue
                try:
                    conn.execute(f"ALTER TABLE relations ADD COLUMN {col} TEXT")
                except sqlite3.OperationalError as exc:
                    msg = str(exc).lower()
                    if "duplicate column name" in msg:
                        continue
                    if (
                        "readonly" in msg
                        or "read-only" in msg
                        or "no such table" in msg
                    ):
                        return
                    raise
            conn.commit()
            self._relations_has_temporal = True
        finally:
            conn.close()

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new optimized SQLite connection."""
        conn = self._open_connection(read_only=self._open_read_only)
        conn.row_factory = sqlite3.Row

        try:
            self._configure_connection(conn, read_only=self._open_read_only)
        except sqlite3.OperationalError as exc:
            if self._open_read_only or not self._is_read_only_error(exc):
                conn.close()
                raise

            conn.close()
            self._open_read_only = True
            conn = self._open_connection(read_only=True)
            conn.row_factory = sqlite3.Row
            try:
                self._configure_connection(conn, read_only=True)
            except Exception:
                conn.close()
                raise

        return conn

    def _open_connection(self, *, read_only: bool) -> sqlite3.Connection:
        if read_only:
            uri_path = quote(str(self._db_path.resolve()), safe="/")
            return sqlite3.connect(
                f"file:{uri_path}?mode=ro",
                uri=True,
                check_same_thread=False,
            )
        return sqlite3.connect(
            self._db_path,
            check_same_thread=False,  # Allow multi-threaded access
        )

    def _configure_connection(
        self, conn: sqlite3.Connection, *, read_only: bool
    ) -> None:
        """Apply connection pragmas, falling back to read-only-safe settings."""
        if read_only:
            conn.execute("PRAGMA query_only=ON")
        else:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")

        # cache_size pragma uses negative values for kilobytes.
        cache_kb = self._tuning.cache_size_mb * 1024
        conn.execute(f"PRAGMA cache_size=-{cache_kb}")
        conn.execute("PRAGMA temp_store=MEMORY")
        mmap_bytes = self._tuning.mmap_size_mb * 1024 * 1024
        conn.execute(f"PRAGMA mmap_size={mmap_bytes}")

    def _is_read_only_error(self, exc: sqlite3.OperationalError) -> bool:
        message = str(exc).lower()
        return (
            "readonly" in message
            or "read-only" in message
            or "attempt to write" in message
        )

    def _is_closed(self) -> bool:
        """Return the live closed flag.

        Read through a method (not the attribute directly) so that re-checks
        after the precondition guard see the current value: ``close()`` may
        flip ``self._closed`` on another thread while a borrowed connection is
        in use.
        """
        return self._closed

    # Seconds to wait for a pool slot before re-checking the closed flag.
    # Large enough that a legitimately-busy-but-open pool slot is never
    # spuriously dropped; small enough that a close() on another thread is
    # detected promptly.
    _POOL_GET_TIMEOUT = 5.0

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for pooled database connections."""
        if self._closed:
            raise RuntimeError("SQLiteEntityStore has been closed")
        conn: sqlite3.Connection | None = None
        while conn is None:
            try:
                conn = self._pool.get(timeout=self._POOL_GET_TIMEOUT)
            except Empty:
                # Timeout — re-check whether close() raced us.
                if self._is_closed():
                    raise RuntimeError("SQLiteEntityStore has been closed") from None
                # Pool is legitimately busy; retry.
        try:
            yield conn
        finally:
            # If close() raced the yield on another thread it already drained
            # the pool, so close this orphaned connection rather than returning
            # it to a dead pool.
            if self._is_closed():
                conn.close()
            else:
                self._pool.put(conn)

    def close(self) -> None:
        """Close all pooled connections."""
        if self._closed:
            return
        self._closed = True
        while True:
            try:
                conn = self._pool.get_nowait()
            except Empty:
                break
            conn.close()

    def __del__(self) -> None:
        """Cleanup: close all pooled connections on garbage collection."""
        with contextlib.suppress(Exception):
            self.close()

    @override
    def all_entity_ids(self) -> set[str]:
        """Return all entity IDs in this store."""
        with self._connection() as conn:
            rows = conn.execute("SELECT entity_id FROM entities").fetchall()
            return {r["entity_id"] for r in rows}

    @override
    def iter_names(
        self,
        *,
        entity_type_prefixes: frozenset[str] | None = None,
        with_name_meta: bool = False,
    ) -> Iterator[tuple[str, str]] | Iterator[tuple[str, str, str, str]]:
        """Yield name rows for every name in the store.

        Streams rows from the ``names`` table; does not materialise a list.
        When ``entity_type_prefixes`` is given, the query joins to ``entities``
        and filters by ``entity_type`` prefix so only matching entity types
        are enumerated — this avoids loading city-tier rows for country-only
        automaton builds.

        When ``with_name_meta=True``, selects two extra columns (``name_kind``
        and the original-cased ``value``) and yields 4-tuples instead of
        2-tuples. The 2-tuple default is byte-identical to the original
        contract; every existing caller is unaffected.
        """
        if with_name_meta:
            yield from self._iter_names_meta(entity_type_prefixes=entity_type_prefixes)
        else:
            yield from self._iter_names_base(entity_type_prefixes=entity_type_prefixes)

    def _iter_names_base(
        self, *, entity_type_prefixes: frozenset[str] | None
    ) -> Iterator[tuple[str, str]]:
        """Yield ``(value_norm, entity_id)`` 2-tuples."""
        with self._connection() as conn:
            if entity_type_prefixes:
                predicates = " OR ".join(
                    "e.entity_type LIKE ?" for _ in entity_type_prefixes
                )
                params = tuple(f"{prefix}%" for prefix in entity_type_prefixes)
                cur = conn.execute(
                    f"SELECT n.value_norm, n.entity_id"
                    f" FROM names n"
                    f" JOIN entities e ON n.entity_id = e.entity_id"
                    f" WHERE {predicates}",
                    params,
                )
            else:
                cur = conn.execute("SELECT value_norm, entity_id FROM names")
            for row in cur:
                yield row[0], row[1]

    def _iter_names_meta(
        self, *, entity_type_prefixes: frozenset[str] | None
    ) -> Iterator[tuple[str, str, str, str]]:
        """Yield ``(value_norm, entity_id, name_kind, value)`` 4-tuples.

        ``value`` is the original-cased name string (e.g. ``"AND"`` for
        Andorra's ISO alias) — used by the automaton builder to identify
        code-shaped patterns.
        """
        with self._connection() as conn:
            if entity_type_prefixes:
                predicates = " OR ".join(
                    "e.entity_type LIKE ?" for _ in entity_type_prefixes
                )
                params = tuple(f"{prefix}%" for prefix in entity_type_prefixes)
                cur = conn.execute(
                    f"SELECT n.value_norm, n.entity_id, n.name_kind, n.value"
                    f" FROM names n"
                    f" JOIN entities e ON n.entity_id = e.entity_id"
                    f" WHERE {predicates}",
                    params,
                )
            else:
                cur = conn.execute(
                    "SELECT value_norm, entity_id, name_kind, value FROM names"
                )
            for row in cur:
                yield row[0], row[1], row[2], row[3]

    def get_entity(self, entity_id: str) -> EntityRecord | None:
        return self._get_entity_cached(entity_id)

    def _get_entity_uncached(self, entity_id: str) -> EntityRecord | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM entities WHERE entity_id = ?", (entity_id,)
            ).fetchone()

            if not row:
                return None

            name_rows = conn.execute(
                "SELECT value, value_norm, name_kind, lang, is_preferred"
                " FROM names WHERE entity_id = ?",
                (entity_id,),
            ).fetchall()

            names = [
                NameRecord(
                    value=r["value"],
                    value_norm=r["value_norm"],
                    kind=r["name_kind"],
                    lang=r["lang"],
                    is_preferred=bool(r["is_preferred"]),
                )
                for r in name_rows
            ]

            code_rows = conn.execute(
                "SELECT * FROM codes WHERE entity_id = ?", (entity_id,)
            ).fetchall()

            codes = [
                CodeRecord(
                    system=r["system"],
                    value=r["value"],
                    value_norm=r["value_norm"],
                )
                for r in code_rows
            ]

            select_temporal = (
                "valid_from, valid_until"
                if self._relations_has_temporal
                else "NULL AS valid_from, NULL AS valid_until"
            )
            relation_rows = conn.execute(
                f"SELECT relation_type, target_id, {select_temporal}"
                " FROM relations WHERE entity_id = ?",
                (entity_id,),
            ).fetchall()

            relations = [
                RelationRecord(
                    relation_type=r["relation_type"],
                    target_id=r["target_id"],
                    valid_from=r["valid_from"],
                    valid_until=r["valid_until"],
                )
                for r in relation_rows
            ]

            # Parse attrs_json if present (column absent in older stores).
            attrs: dict[str, Any] = {}
            if "attrs_json" in row.keys() and (attrs_json := row["attrs_json"]):  # noqa: SIM118 — sqlite3.Row iterates values, not keys
                with contextlib.suppress(json.JSONDecodeError):
                    attrs = json.loads(attrs_json)

            return EntityRecord(
                entity_id=row["entity_id"],
                entity_type=row["entity_type"],
                canonical_name=row["canonical_name"],
                canonical_name_norm=row["canonical_name_norm"],
                names=names,
                codes=codes,
                relations=relations,
                valid_from=row["valid_from"],
                valid_until=row["valid_until"],
                attributes=attrs,
            )

    def lookup_code(self, system: str, value_norm: str) -> list[str]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT entity_id FROM codes WHERE system = ? AND value_norm = ?"
                " ORDER BY entity_id",
                (system, value_norm),
            ).fetchall()
            return [r["entity_id"] for r in rows]

    def lookup_code_any(self, value_norm: str) -> list[tuple[str, str]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT entity_id, system FROM codes WHERE value_norm = ?"
                " ORDER BY entity_id, system",
                (value_norm,),
            ).fetchall()
            return [(r["entity_id"], r["system"]) for r in rows]

    def code_systems(self) -> frozenset[str]:
        with self._connection() as conn:
            rows = conn.execute("SELECT DISTINCT system FROM codes").fetchall()
            return frozenset(r["system"] for r in rows)

    @override
    def relation_types(self) -> frozenset[str]:
        with self._connection() as conn:
            try:
                rows = conn.execute(
                    "SELECT DISTINCT relation_type FROM relations"
                ).fetchall()
            except sqlite3.OperationalError:
                return frozenset()  # legacy DB with no relations table
            return frozenset(r["relation_type"] for r in rows)

    def lookup_name_exact(
        self, value_norm: str, name_kinds: set[str] | None = None
    ) -> list[str]:
        with self._connection() as conn:
            if name_kinds:
                placeholders = ",".join("?" * len(name_kinds))
                rows = conn.execute(
                    f"SELECT DISTINCT entity_id FROM names WHERE value_norm = ? AND name_kind IN ({placeholders})"
                    " ORDER BY entity_id",
                    (value_norm, *name_kinds),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT DISTINCT entity_id FROM names WHERE value_norm = ?"
                    " ORDER BY entity_id",
                    (value_norm,),
                ).fetchall()
            return [r["entity_id"] for r in rows]

    def _execute_fts_query(
        self,
        conn: sqlite3.Connection,
        fts_expr: str,
        limit: int,
    ) -> list[tuple[str, float, int]]:
        """Run a single FTS5 MATCH query and return ranked results.

        Args:
            conn: Active database connection.
            fts_expr: Pre-escaped FTS5 MATCH expression.
            limit: Maximum number of results to return.

        Returns:
            List of ``(entity_id, score, rank)`` tuples, or empty list on error.
        """
        try:
            rows = conn.execute(
                """
                SELECT entity_id, MIN(rank) AS score
                FROM names_fts
                WHERE names_fts MATCH ?
                GROUP BY entity_id
                ORDER BY score
                LIMIT ?
                """,
                (fts_expr, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            logger.debug("FTS5 MATCH failed for expression: %s", fts_expr)
            return []
        return [(r["entity_id"], abs(r["score"]), i + 1) for i, r in enumerate(rows)]

    def search_fulltext(
        self,
        query_norm: str,
        fields: set[str] | None = None,
        limit: int = 10,
    ) -> list[tuple[str, float, int]]:
        # `fields` is intentionally unused: SQLite only FTS-indexes the "name" field;
        # field-level filtering is not implemented for this backend.
        _ = fields
        if not query_norm or not self._has_fts:
            return []
        with self._connection() as conn:
            # Exact phrase match first — most queries match this way.
            # Phrase order and completeness must match exactly.
            escaped_phrase = escape_fts5_query(query_norm)
            results = self._execute_fts_query(conn, escaped_phrase, limit)
            if results:
                return results

            # Token-AND fallback for multi-word queries only.
            tokens = query_norm.split()
            if len(tokens) >= 2:
                # AND of individual tokens — handles word reordering
                # (e.g. "States United" → "states" AND "united").
                and_query = escape_fts5_query_tokens(query_norm, mode="AND")
                results = self._execute_fts_query(conn, and_query, limit)
                if results:
                    return results

            return []

    def bulk_get_entities(self, entity_ids: list[str]) -> dict[str, EntityRecord]:
        if not entity_ids:
            return {}

        result: dict[str, EntityRecord] = {}

        with self._connection() as conn:
            for chunk in _chunked(entity_ids, _BULK_CHUNK_SIZE):
                placeholders = ",".join("?" * len(chunk))

                entity_rows = conn.execute(
                    f"SELECT * FROM entities WHERE entity_id IN ({placeholders})",
                    chunk,
                ).fetchall()

                name_rows = conn.execute(
                    f"SELECT entity_id, value, value_norm, name_kind, lang,"
                    f" is_preferred FROM names WHERE entity_id IN ({placeholders})",
                    chunk,
                ).fetchall()

                code_rows = conn.execute(
                    f"SELECT * FROM codes WHERE entity_id IN ({placeholders})",
                    chunk,
                ).fetchall()

                rel_temporal = (
                    "valid_from, valid_until"
                    if self._relations_has_temporal
                    else "NULL AS valid_from, NULL AS valid_until"
                )
                relation_rows = conn.execute(
                    f"SELECT entity_id, relation_type, target_id, {rel_temporal}"
                    f" FROM relations WHERE entity_id IN ({placeholders})",
                    chunk,
                ).fetchall()

                names_by_entity = _group_rows_by_entity(name_rows)
                codes_by_entity = _group_rows_by_entity(code_rows)
                relations_by_entity = _group_rows_by_entity(relation_rows)

                for row in entity_rows:
                    eid = row["entity_id"]

                    names = [
                        NameRecord(
                            value=r["value"],
                            value_norm=r["value_norm"],
                            kind=r["name_kind"],
                            lang=r["lang"],
                            is_preferred=bool(r["is_preferred"]),
                        )
                        for r in names_by_entity.get(eid, [])
                    ]

                    codes = [
                        CodeRecord(
                            system=r["system"],
                            value=r["value"],
                            value_norm=r["value_norm"],
                        )
                        for r in codes_by_entity.get(eid, [])
                    ]

                    relations = [
                        RelationRecord(
                            relation_type=r["relation_type"],
                            target_id=r["target_id"],
                            valid_from=r["valid_from"],
                            valid_until=r["valid_until"],
                        )
                        for r in relations_by_entity.get(eid, [])
                    ]

                    # Parse attrs_json if present (column absent in older stores).
                    attrs: dict[str, Any] = {}
                    if "attrs_json" in row.keys() and (attrs_json := row["attrs_json"]):  # noqa: SIM118 — sqlite3.Row iterates values, not keys
                        with contextlib.suppress(json.JSONDecodeError):
                            attrs = json.loads(attrs_json)

                    result[eid] = EntityRecord(
                        entity_id=eid,
                        entity_type=row["entity_type"],
                        canonical_name=row["canonical_name"],
                        canonical_name_norm=row["canonical_name_norm"],
                        names=names,
                        codes=codes,
                        relations=relations,
                        valid_from=row["valid_from"],
                        valid_until=row["valid_until"],
                        attributes=attrs,
                    )

        return result

    def get_relations(
        self, entity_id: str, relation_type: str | None = None
    ) -> list[str]:
        with self._connection() as conn:
            if relation_type:
                rows = conn.execute(
                    "SELECT target_id FROM relations WHERE entity_id = ? AND relation_type = ?"
                    " ORDER BY target_id",
                    (entity_id, relation_type),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT target_id FROM relations WHERE entity_id = ?"
                    " ORDER BY target_id",
                    (entity_id,),
                ).fetchall()
            return [r["target_id"] for r in rows]

    def get_relations_as_of(
        self, entity_id: str, relation_type: str, as_of: date
    ) -> list[str]:
        """Return target entity IDs for relations active on the given date.

        Half-open interval on the right: a relation with ``valid_until=X`` is
        active for ``as_of < X`` but not for ``as_of >= X``.

        Args:
            entity_id: Source entity ID.
            relation_type: Relation type to filter by.
            as_of: Reference date for the temporal filter.

        Returns:
            List of target entity IDs whose validity window contains ``as_of``.
        """
        as_of_str = as_of.isoformat()
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT target_id FROM relations
                WHERE entity_id = ?
                  AND relation_type = ?
                  AND (valid_from IS NULL OR valid_from <= ?)
                  AND (valid_until IS NULL OR valid_until > ?)
                ORDER BY target_id
                """,
                (entity_id, relation_type, as_of_str, as_of_str),
            ).fetchall()
        return [r["target_id"] for r in rows]

    def get_reverse_relations(
        self,
        target_id: str,
        relation_type: str,
        *,
        as_of: date | None = None,
    ) -> list[str]:
        """Return entity IDs that have a given relation pointing to target_id.

        Args:
            target_id: Target entity ID to look up.
            relation_type: Relation type to filter by.
            as_of: When provided, only returns relations active on that date.
                Null bounds are treated as always-valid.

        Returns:
            List of source entity IDs with the given relation to ``target_id``.
        """
        with self._connection() as conn:
            if as_of is None:
                rows = conn.execute(
                    "SELECT entity_id FROM relations"
                    " WHERE target_id = ? AND relation_type = ?"
                    " ORDER BY entity_id",
                    (target_id, relation_type),
                ).fetchall()
            else:
                as_of_str = as_of.isoformat()
                rows = conn.execute(
                    """
                    SELECT entity_id FROM relations
                    WHERE target_id = ?
                      AND relation_type = ?
                      AND (valid_from IS NULL OR valid_from <= ?)
                      AND (valid_until IS NULL OR valid_until > ?)
                    ORDER BY entity_id
                    """,
                    (target_id, relation_type, as_of_str, as_of_str),
                ).fetchall()
        return [r["entity_id"] for r in rows]

    def list_entities_by_type(self, entity_type: str) -> list[EntityRecord]:
        """Return all entities of the given type.

        Args:
            entity_type: Entity type string to filter by (e.g., "geo.organization").

        Returns:
            List of ``EntityRecord`` objects with the given type.
        """
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT entity_id FROM entities WHERE entity_type = ?",
                (entity_type,),
            ).fetchall()
        entity_ids = [r["entity_id"] for r in rows]
        if not entity_ids:
            return []
        entities = self.bulk_get_entities(entity_ids)
        return list(entities.values())

    def search_prefix(
        self, query_norm: str, field: str, limit: int = 10
    ) -> list[tuple[str, float, int]]:
        """Prefix search using FTS5 prefix matching for fast autocomplete.

        Uses FTS5's native prefix query syntax (term*) with BM25 ranking.
        Falls back to LIKE on the names table if FTS5 is unavailable.
        Only the ``"name"`` field is FTS-indexed; other fields return empty.
        """
        if not query_norm or field != "name":
            return []

        if not self._has_fts:
            return self._search_prefix_like(query_norm, limit)

        fts_query = escape_fts5_query(query_norm, prefix=True)

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT entity_id, MIN(rank) AS score
                FROM names_fts
                WHERE names_fts MATCH ?
                GROUP BY entity_id
                ORDER BY score
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()

            return [
                (r["entity_id"], abs(r["score"]), i + 1) for i, r in enumerate(rows)
            ]

    def _search_prefix_like(
        self, query_norm: str, limit: int
    ) -> list[tuple[str, float, int]]:
        """Fallback prefix search using diacritic-folded LIKE on names table.

        Compares a diacritic-folded projection of ``value_norm`` against the
        folded query so that ``"sao"`` finds ``"são"``-normalised rows.
        Since ``value_norm`` is NFKC+lower (not diacritic-folded), the fold is
        applied in Python after fetching all rows — acceptable because this path
        is only hit on non-FTS stores (rare; shipped packs use FTS5).

        Note: the asymmetry is fully closed on this LIKE fallback only; the FTS5
        path is unchanged (diacritic handling there is a separate corpus concern).
        """
        query_folded = fold_for_match(query_norm)
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT entity_id, value_norm FROM names",
            ).fetchall()

        results: list[tuple[str, float, int]] = []
        seen: set[str] = set()
        for row in rows:
            if len(results) >= limit:
                break
            eid = row["entity_id"]
            if eid in seen:
                continue
            if fold_for_match(row["value_norm"]).startswith(query_folded):
                seen.add(eid)
                results.append((eid, 1.0, len(results) + 1))
        return results

    @override
    def iter_suggest_names(
        self,
        *,
        entity_type_prefixes: frozenset[str] | None = None,
        entity_type_exclude_prefixes: frozenset[str] | None = None,
    ) -> Iterator[tuple[str, str, str, bool, str]]:
        """Yield ``(value_norm, entity_id, name_kind, is_preferred, value)`` 5-tuples.

        Extends the ``_iter_names_meta`` join shape to also select ``is_preferred``.
        Filtered by ``entity_type_prefixes`` when provided; rows whose entity type
        matches ``entity_type_exclude_prefixes`` are skipped (exclude wins over include).
        """
        with self._connection() as conn:
            predicates: list[str] = []
            params: list[str] = []
            needs_join = bool(entity_type_prefixes or entity_type_exclude_prefixes)
            if entity_type_prefixes:
                include_pred = (
                    "("
                    + " OR ".join("e.entity_type LIKE ?" for _ in entity_type_prefixes)
                    + ")"
                )
                predicates.append(include_pred)
                params.extend(f"{p}%" for p in entity_type_prefixes)
            if entity_type_exclude_prefixes:
                exclude_pred = (
                    "("
                    + " AND ".join(
                        "e.entity_type NOT LIKE ?" for _ in entity_type_exclude_prefixes
                    )
                    + ")"
                )
                predicates.append(exclude_pred)
                params.extend(f"{p}%" for p in entity_type_exclude_prefixes)
            if needs_join:
                where = " AND ".join(predicates)
                cur = conn.execute(
                    f"SELECT n.value_norm, n.entity_id, n.name_kind,"
                    f"       n.is_preferred, n.value"
                    f" FROM names n"
                    f" JOIN entities e ON n.entity_id = e.entity_id"
                    f" WHERE {where}",
                    tuple(params),
                )
            else:
                cur = conn.execute(
                    "SELECT value_norm, entity_id, name_kind, is_preferred, value"
                    " FROM names"
                )
            for row in cur:
                yield row[0], row[1], row[2], bool(row[3]), row[4]

    @override
    def search_token_infix(
        self,
        query_norm: str,
        *,
        entity_type_prefixes: frozenset[str] | None = None,
        limit: int = 10,
    ) -> list[tuple[str, float, int]]:
        """Search for entities where ``query_norm`` appears as an FTS5 token.

        FTS stores: bare-token MATCH via ``escape_fts5_query(query_norm,
        prefix=False)`` — no standalone ``LIKE %q%`` scan.
        Non-FTS fallback: ``LIKE %query%`` with ``%``/``_`` escaped via
        ``ESCAPE '\\'`` and bound params, scoped by ``entity_type_prefixes``.

        Interior-substring (mid-token) infix matching is out of scope.
        """
        if not query_norm:
            return []

        if self._has_fts:
            return self._search_token_infix_fts(
                query_norm,
                entity_type_prefixes=entity_type_prefixes,
                limit=limit,
            )
        return self._search_token_infix_like(
            query_norm,
            entity_type_prefixes=entity_type_prefixes,
            limit=limit,
        )

    def _search_token_infix_fts(
        self,
        query_norm: str,
        *,
        entity_type_prefixes: frozenset[str] | None,
        limit: int,
    ) -> list[tuple[str, float, int]]:
        """FTS5 token MATCH for infix search."""
        fts_expr = escape_fts5_query(query_norm, prefix=False)
        with self._connection() as conn:
            if entity_type_prefixes:
                # Join to entities to filter by type prefix.
                predicates = " OR ".join(
                    "e.entity_type LIKE ?" for _ in entity_type_prefixes
                )
                type_params = tuple(f"{prefix}%" for prefix in entity_type_prefixes)
                try:
                    rows = conn.execute(
                        f"""
                        SELECT f.entity_id, MIN(f.rank) AS score
                        FROM names_fts f
                        JOIN entities e ON f.entity_id = e.entity_id
                        WHERE names_fts MATCH ?
                          AND ({predicates})
                        GROUP BY f.entity_id
                        ORDER BY score
                        LIMIT ?
                        """,
                        (fts_expr, *type_params, limit),
                    ).fetchall()
                except sqlite3.OperationalError:
                    logger.debug("FTS5 token MATCH failed for expression: %s", fts_expr)
                    return []
            else:
                try:
                    rows = conn.execute(
                        """
                        SELECT entity_id, MIN(rank) AS score
                        FROM names_fts
                        WHERE names_fts MATCH ?
                        GROUP BY entity_id
                        ORDER BY score
                        LIMIT ?
                        """,
                        (fts_expr, limit),
                    ).fetchall()
                except sqlite3.OperationalError:
                    logger.debug("FTS5 token MATCH failed for expression: %s", fts_expr)
                    return []
        return [(r["entity_id"], abs(r["score"]), i + 1) for i, r in enumerate(rows)]

    def _search_token_infix_like(
        self,
        query_norm: str,
        *,
        entity_type_prefixes: frozenset[str] | None,
        limit: int,
    ) -> list[tuple[str, float, int]]:
        """Non-FTS fallback: LIKE %query% with escaped bounds + type filter."""
        escaped = (
            query_norm.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        with self._connection() as conn:
            if entity_type_prefixes:
                predicates = " OR ".join(
                    "e.entity_type LIKE ?" for _ in entity_type_prefixes
                )
                type_params = tuple(f"{prefix}%" for prefix in entity_type_prefixes)
                rows = conn.execute(
                    f"""
                    SELECT DISTINCT n.entity_id
                    FROM names n
                    JOIN entities e ON n.entity_id = e.entity_id
                    WHERE n.value_norm LIKE ? ESCAPE '\\'
                      AND ({predicates})
                    ORDER BY n.entity_id
                    LIMIT ?
                    """,
                    (f"%{escaped}%", *type_params, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT DISTINCT entity_id
                    FROM names
                    WHERE value_norm LIKE ? ESCAPE '\\'
                    ORDER BY entity_id
                    LIMIT ?
                    """,
                    (f"%{escaped}%", limit),
                ).fetchall()
        return [(r["entity_id"], 1.0, i + 1) for i, r in enumerate(rows)]
