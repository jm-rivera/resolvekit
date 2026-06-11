"""Shared SQLite helpers used by both the runtime store layer and builder modules.

Single source of truth for low-level SQLite utilities.
``resolvekit.builder.sqlite.{context,write,constants}`` re-export these symbols
so that existing builder callers are unaffected.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

from resolvekit.shared.build.schema import SCHEMA_SQL

SQLITE_IDENTIFIER_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"
SQLITE_IDENTIFIER_RE = re.compile(SQLITE_IDENTIFIER_PATTERN)


@contextmanager
def connect_sqlite(
    db_path: Path,
    *,
    timeout: float = 30.0,
    row_factory: Any | None = None,
    busy_timeout_ms: int | None = None,
    pragmas: Sequence[str] = (),
) -> Iterator[sqlite3.Connection]:
    """Open and close a SQLite connection with optional baseline pragmas."""
    conn = sqlite3.connect(db_path, timeout=timeout)
    try:
        if row_factory is not None:
            conn.row_factory = row_factory
        if busy_timeout_ms is not None:
            conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
        for pragma in pragmas:
            conn.execute(pragma)
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """Wrap a set of writes in one rollback-safe transaction."""
    conn.execute("BEGIN")
    try:
        yield
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()


@contextmanager
def attached_db(
    conn: sqlite3.Connection,
    *,
    alias: str,
    db_path: Path,
) -> Iterator[None]:
    """Attach and later detach a secondary SQLite database."""
    if SQLITE_IDENTIFIER_RE.fullmatch(alias) is None:
        raise ValueError(f"Invalid SQLite alias: {alias!r}")

    conn.execute(f"ATTACH DATABASE ? AS {alias}", (str(db_path),))
    try:
        yield
    finally:
        with suppress(sqlite3.OperationalError):
            conn.execute(f"DETACH DATABASE {alias}")


def ensure_sqlite_schema(db_path: Path) -> None:
    """Ensure all required tables/indexes/views exist for a SQLite artifact."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect_sqlite(
        db_path,
        busy_timeout_ms=30000,
        pragmas=(
            "PRAGMA journal_mode=WAL",
            "PRAGMA synchronous=NORMAL",
            "PRAGMA cache_size=-64000",
        ),
    ) as conn:
        conn.executescript(SCHEMA_SQL)
        _migrate_relations_temporal_cols(conn)
        conn.commit()


def _migrate_relations_temporal_cols(conn: sqlite3.Connection) -> None:
    """Add temporal columns + their index to relations on an existing DB.

    The index is created here (not in SCHEMA_SQL) because it references
    columns that may not yet exist when SCHEMA_SQL's executescript runs
    on a pre-migration database.
    """
    for col in ("valid_from", "valid_until"):
        try:
            conn.execute(f"ALTER TABLE relations ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_relations_temporal "
        "ON relations(entity_id, relation_type, valid_from, valid_until)"
    )


def rebuild_fts(db_path: Path) -> None:
    """Rebuild names FTS index from source table."""
    with connect_sqlite(db_path) as conn:
        conn.execute("INSERT INTO names_fts(names_fts) VALUES('rebuild')")
        conn.commit()


def escape_fts5_query(text: str, *, prefix: bool = False) -> str:
    """Escape text for safe use in FTS5 MATCH queries.

    FTS5 uses special syntax for boolean operators, phrases, and wildcards.
    This function escapes input by wrapping in quotes and doubling any
    internal quotes to treat the text as a literal phrase.

    Args:
        text: Raw query text
        prefix: If True, append ``*`` for FTS5 prefix matching.

    Returns:
        Escaped query safe for FTS5 MATCH
    """
    # Double any existing quotes to escape them
    escaped = text.replace('"', '""')
    # Wrap in quotes to treat as literal phrase
    suffix = "*" if prefix else ""
    return f'"{escaped}"{suffix}'


def escape_fts5_query_tokens(text: str, *, mode: str = "AND") -> str:
    """Build an FTS5 token query with each word quoted individually.

    Each token is quoted to prevent FTS5 syntax injection, then
    joined with AND or OR.

    Args:
        text: Raw query text
        mode: Join operator — ``"AND"`` (default) or ``"OR"``.

    Returns:
        FTS5 MATCH expression with individually-quoted tokens.
    """
    tokens = text.split()
    if not tokens:
        return ""
    quoted = [f'"{t.replace(chr(34), chr(34) + chr(34))}"' for t in tokens]
    return f" {mode} ".join(quoted)
