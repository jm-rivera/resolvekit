"""Composed SQLite store for same-domain base-module composition.

On a cache miss the composed DB is built as before (ATTACH + INSERT + FTS
rebuild) and written atomically into the cache directory.  On a cache hit the
pre-built file is opened directly — no copy, no FTS rebuild, sub-second
startup.

Cache key
---------
The key is a SHA-256 digest of the sorted tuple::

    (domain, CACHE_FORMAT_VERSION, (module_id, datapack_id, db_size, db_mtime), ...)

``datapack_id`` is the human-readable version tag from ``DataPackMetadata``
(e.g. ``"geo.admin1-v2026.06"``).  ``db_size`` and ``db_mtime`` are redundant
safety signals: if a pack is rebuilt in-place with the same ``datapack_id``
(a build bug) the stale cached composed DB is evicted automatically.

``CACHE_FORMAT_VERSION`` is bumped whenever the composition logic or schema
changes in a way that invalidates existing cached files.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import weakref
from pathlib import Path
from queue import Empty, Queue

from resolvekit.core.config import get_cache_dir
from resolvekit.core.datapack import LoadedDataPack
from resolvekit.core.errors import ModuleConflictError
from resolvekit.core.store.sqlite import SQLiteEntityStore, SQLiteTuning
from resolvekit.core.store.sqlite_helpers import (
    attached_db,
    connect_sqlite,
    ensure_sqlite_schema,
    rebuild_fts,
    transaction,
)

logger = logging.getLogger(__name__)

# Bump this when composition logic or schema changes incompatibly.
CACHE_FORMAT_VERSION = "1"

# Sub-directory inside the resolvekit cache dir for composed DBs.
_COMPOSED_SUBDIR = "composed"


# ---------------------------------------------------------------------------
# Persistent store (cache hits) — does NOT delete the file on close
# ---------------------------------------------------------------------------


class PersistentSQLiteEntityStore(SQLiteEntityStore):
    """SQLite store backed by a cache file that must NOT be deleted on close.

    Used for composed-DB cache hits so the cached file persists for the next
    process.
    """

    # No extra logic needed beyond the base class — SQLiteEntityStore.close()
    # already just closes connections without touching the file.  The class
    # exists as a distinct type so tests can assert the correct subclass is
    # returned on a hit vs. miss.
    pass


# ---------------------------------------------------------------------------
# Temporary store (cache miss — cleanup on close)
# ---------------------------------------------------------------------------


class TemporarySQLiteEntityStore(SQLiteEntityStore):
    """SQLite store that owns and removes a temporary backing directory."""

    def __init__(
        self,
        db_path: Path,
        *,
        temp_dir: str | Path,
        tuning: SQLiteTuning | None = None,
    ) -> None:
        super().__init__(db_path, tuning=tuning)
        # Drive cleanup through one finalizer so the connection pool is always
        # drained before the directory is removed — on the garbage-collection
        # and interpreter-exit paths, not only an explicit close(). An open
        # SQLite handle blocks directory removal on Windows (WinError 32), so a
        # bare TemporaryDirectory, whose own finalizer can rmtree while the pool
        # is still open, races that ordering and fails there.
        self._finalizer = weakref.finalize(self, _cleanup, self._pool, str(temp_dir))

    def close(self) -> None:
        super().close()
        self._finalizer()


def _cleanup(pool: Queue[sqlite3.Connection], temp_dir: str) -> None:
    """Close any pooled connections, then remove the temporary directory."""
    while True:
        try:
            conn = pool.get_nowait()
        except Empty:
            break
        conn.close()
    shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------


def _pack_file_signature(db_path: Path) -> tuple[int, float]:
    """Return (size_bytes, mtime) for a db file as a cheap content signal."""
    try:
        st = db_path.stat()
        return (st.st_size, st.st_mtime)
    except OSError:
        return (0, 0.0)


def _compose_cache_key(domain: str, loaded_packs: list[LoadedDataPack]) -> str:
    """Return a hex SHA-256 cache key for the given composition inputs.

    Inputs that affect the composed bytes:
    - ``domain`` — domain pack id string
    - ``CACHE_FORMAT_VERSION`` — bumped on schema/logic changes
    - Per pack (sorted by module_id for stability):
        - ``module_id``
        - ``datapack_id`` — stable version tag from metadata
        - db file size + mtime — evicts if pack rebuilt in-place with same ID

    Returns:
        40-character hex prefix (first 20 bytes) of the SHA-256 digest.
        Collision probability for ≤10 k entries is negligible.
    """
    entries = sorted(
        (
            lp.module_id,
            lp.metadata.datapack_id,
            *_pack_file_signature(lp.db_path),
        )
        for lp in loaded_packs
    )
    payload = json.dumps(
        {
            "domain": domain,
            "version": CACHE_FORMAT_VERSION,
            "packs": entries,
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return digest[:40]


# ---------------------------------------------------------------------------
# Cache I/O helpers
# ---------------------------------------------------------------------------


def _composed_cache_dir() -> Path:
    """Return the directory where composed DBs are cached."""
    return get_cache_dir() / _COMPOSED_SUBDIR


def _cache_path_for_key(cache_key: str) -> Path:
    """Return the canonical cache file path for a given cache key."""
    return _composed_cache_dir() / f"{cache_key}.sqlite"


def _try_open_cached(
    cache_path: Path,
    *,
    tuning: SQLiteTuning | None,
) -> PersistentSQLiteEntityStore | None:
    """Return a persistent store for the cached DB, or None if invalid."""
    if not cache_path.exists():
        return None
    try:
        store = PersistentSQLiteEntityStore(cache_path, tuning=tuning)
        logger.debug("composed-sqlite cache HIT: %s", cache_path)
        return store
    except Exception:
        # Corrupted or otherwise unreadable — fall through to rebuild.
        logger.debug(
            "composed-sqlite cache file unreadable, rebuilding: %s", cache_path
        )
        with contextlib.suppress(OSError):
            cache_path.unlink(missing_ok=True)
        return None


def _build_composed_db(
    *,
    domain: str,
    loaded_packs: list[LoadedDataPack],
) -> tuple[Path, str]:
    """Build the composed SQLite DB in a temp dir and return (db_path, temp_dir).

    Raises ``ModuleConflictError`` on overlapping entity IDs.
    ``temp_dir`` must be cleaned up by the caller (via shutil.rmtree or by
    serving from it as a TemporarySQLiteEntityStore).
    """
    temp_dir = tempfile.mkdtemp(prefix=f"resolvekit-{domain}-")
    db_path = Path(temp_dir) / "entities.sqlite"
    try:
        ensure_sqlite_schema(db_path)

        with connect_sqlite(db_path, busy_timeout_ms=30000) as conn, transaction(conn):
            conn.execute(
                "CREATE TABLE composed_sources(entity_id TEXT PRIMARY KEY, module_id TEXT NOT NULL)"
            )
            for index, loaded in enumerate(loaded_packs):
                alias = f"src_{index}"
                with attached_db(conn, alias=alias, db_path=loaded.db_path):
                    _copy_attached_module(
                        conn=conn,
                        alias=alias,
                        domain=domain,
                        loaded=loaded,
                    )
            conn.execute("DROP TABLE composed_sources")

        rebuild_fts(db_path)
        return db_path, temp_dir
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def _write_to_cache_atomically(
    src_db_path: Path,
    cache_path: Path,
) -> None:
    """Copy the composed DB into the cache atomically via rename.

    Writes to a sibling temp file in the same directory, then os.replace()
    for an atomic swap.  Concurrent processes racing to write the same key
    are harmless: the last writer wins and the file is always a complete DB.
    """
    cache_dir = cache_path.parent
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Write to a temp file in the same directory so os.replace() is atomic
    # (same filesystem, avoids cross-device rename).
    fd, tmp_path_str = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
    tmp_path = Path(tmp_path_str)
    try:
        os.close(fd)
        shutil.copy2(src_db_path, tmp_path)
        os.replace(tmp_path, cache_path)
        logger.debug("composed-sqlite cache WRITTEN: %s", cache_path)
    except Exception:
        with contextlib.suppress(OSError):
            tmp_path.unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compose_base_module_store(
    *,
    domain: str,
    loaded_packs: list[LoadedDataPack],
    sqlite_tuning: SQLiteTuning | None = None,
) -> SQLiteEntityStore:
    """Compose multiple same-domain base modules into one SQLite store.

    On the first call the composed DB is built (ATTACH + INSERT + FTS rebuild)
    and written into the resolvekit cache directory.  Subsequent calls with the
    same set of packs (same ``datapack_id`` + file signature) return a
    ``PersistentSQLiteEntityStore`` backed by the cached file — no copy, no
    FTS rebuild, typically < 100 ms.

    Single-pack shortcut: returns a plain ``SQLiteEntityStore`` without caching
    (no composition needed).

    Raises:
        ValueError: if ``loaded_packs`` is empty.
        ModuleConflictError: if two modules share an ``entity_id`` (only on
            a cache miss; a hit implies the build previously succeeded).
    """
    if not loaded_packs:
        raise ValueError("loaded_packs must be non-empty")
    if len(loaded_packs) == 1:
        return SQLiteEntityStore(loaded_packs[0].db_path, tuning=sqlite_tuning)

    cache_key = _compose_cache_key(domain, loaded_packs)
    cache_path = _cache_path_for_key(cache_key)

    # --- Cache hit ---
    cached = _try_open_cached(cache_path, tuning=sqlite_tuning)
    if cached is not None:
        return cached

    # --- Cache miss: build, cache, return ---
    logger.debug(
        "composed-sqlite cache MISS (key=%s), building %d packs for domain=%s",
        cache_key,
        len(loaded_packs),
        domain,
    )
    db_path, temp_dir = _build_composed_db(domain=domain, loaded_packs=loaded_packs)
    try:
        # Write atomically into cache; best-effort — if the cache write fails
        # (e.g. read-only filesystem) we fall back to a temporary store.
        try:
            _write_to_cache_atomically(db_path, cache_path)
            cached_store = _try_open_cached(cache_path, tuning=sqlite_tuning)
            if cached_store is not None:
                # Cache write succeeded — clean up the temp dir (we serve
                # from the stable cache path now, not the temp file).
                shutil.rmtree(temp_dir, ignore_errors=True)
                return cached_store
            # Cache write succeeded but open failed — fall through to temp store.
        except Exception as exc:
            logger.debug(
                "composed-sqlite cache write failed (%s), using temp store", exc
            )
        # Fallback: serve from temp dir (original behavior).
        return TemporarySQLiteEntityStore(
            db_path, temp_dir=temp_dir, tuning=sqlite_tuning
        )
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _copy_attached_module(
    *,
    conn: sqlite3.Connection,
    alias: str,
    domain: str,
    loaded: LoadedDataPack,
) -> None:
    try:
        _copy_table(conn, alias=alias, table="entities")
    except sqlite3.IntegrityError as exc:
        overlap_rows = conn.execute(
            f"""
            SELECT src.entity_id, composed.module_id
            FROM {alias}.entities src
            INNER JOIN composed_sources composed
                ON composed.entity_id = src.entity_id
            ORDER BY src.entity_id
            LIMIT 10
            """
        ).fetchall()
        overlapping_entity_ids = [str(row[0]) for row in overlap_rows]
        left_module_id = str(overlap_rows[0][1]) if overlap_rows else loaded.module_id
        raise ModuleConflictError(
            domain=domain,
            left_module_id=left_module_id,
            right_module_id=loaded.module_id,
            overlapping_entity_ids=overlapping_entity_ids,
        ) from exc

    conn.execute(
        f"INSERT INTO composed_sources(entity_id, module_id) "
        f"SELECT entity_id, ? FROM {alias}.entities",
        (loaded.module_id,),
    )
    _copy_table(conn, alias=alias, table="names", conflict_clause="OR IGNORE")
    _copy_table(conn, alias=alias, table="codes", conflict_clause="OR REPLACE")
    _copy_table(conn, alias=alias, table="relations", conflict_clause="OR IGNORE")


def _copy_table(
    conn: sqlite3.Connection,
    *,
    alias: str,
    table: str,
    conflict_clause: str = "",
) -> None:
    target_columns = _table_columns(conn, alias="main", table=table)
    source_column_names = {
        str(column["name"]) for column in _table_columns(conn, alias=alias, table=table)
    }

    column_names = ", ".join(f'"{column["name"]}"' for column in target_columns)
    select_parts = []
    for column in target_columns:
        name = column["name"]
        if name in source_column_names:
            select_parts.append(f'"{name}"')
        else:
            select_parts.append(f'{_default_sql(column)} AS "{name}"')
    select_sql = ", ".join(select_parts)
    conflict_sql = f" {conflict_clause}" if conflict_clause else ""
    conn.execute(
        f'INSERT{conflict_sql} INTO "{table}" ({column_names}) '
        f'SELECT {select_sql} FROM {alias}."{table}"'
    )


def _table_columns(
    conn: sqlite3.Connection,
    *,
    alias: str,
    table: str,
) -> list[dict[str, str | int | None]]:
    rows = conn.execute(f'PRAGMA {alias}.table_info("{table}")').fetchall()
    return [
        {
            "name": row[1],
            "notnull": row[3],
            "default": row[4],
        }
        for row in rows
    ]


def _default_sql(column: dict[str, str | int | None]) -> str:
    if column["default"] is not None:
        return str(column["default"])
    return "NULL"
