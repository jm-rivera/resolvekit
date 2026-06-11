"""Unit tests for apply_name_rows (builder/sqlite/write.py).

Three cases: fresh insert returns delta, idempotent re-run returns 0,
partial collision returns only the new-row count.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from resolvekit.builder.sqlite.context import transaction
from resolvekit.builder.sqlite.write import apply_name_rows

# Minimal schema — names table only (all other tables omitted; apply_name_rows
# touches only names).
_SCHEMA = """
CREATE TABLE IF NOT EXISTS names (
    entity_id TEXT NOT NULL,
    name_kind TEXT NOT NULL,
    value TEXT NOT NULL,
    value_norm TEXT NOT NULL,
    lang TEXT NOT NULL DEFAULT '',
    script TEXT NOT NULL DEFAULT '',
    is_preferred INTEGER DEFAULT 0,
    PRIMARY KEY (entity_id, name_kind, value_norm, lang, script)
);
"""


def _open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    return conn


# Two distinct rows, each with a unique (entity_id, name_kind, value_norm, lang, script) PK.
_ROW_A: tuple[str, str, str, str, str, str, int] = (
    "country/TUR",
    "alias",
    "Türkiye",
    "turkiye",
    "en",
    "",
    0,
)
_ROW_B: tuple[str, str, str, str, str, str, int] = (
    "country/TUR",
    "alias",
    "Turkey",
    "turkey",
    "en",
    "",
    0,
)


@pytest.mark.unit
def test_apply_name_rows_returns_insert_delta(tmp_path: Path) -> None:
    """Inserting N rows into an empty names table returns N."""
    db = tmp_path / "names.sqlite"
    conn = _open_db(db)
    try:
        with transaction(conn):
            delta = apply_name_rows(conn=conn, rows=[_ROW_A, _ROW_B])
    finally:
        conn.close()

    assert delta == 2


@pytest.mark.unit
def test_apply_name_rows_idempotent_on_pk_collision(tmp_path: Path) -> None:
    """Re-inserting the same rows returns 0 (INSERT OR IGNORE, no duplicate)."""
    db = tmp_path / "names.sqlite"
    conn = _open_db(db)
    try:
        with transaction(conn):
            apply_name_rows(conn=conn, rows=[_ROW_A, _ROW_B])
        # Second run — all rows already present.
        with transaction(conn):
            delta = apply_name_rows(conn=conn, rows=[_ROW_A, _ROW_B])
    finally:
        conn.close()

    assert delta == 0


@pytest.mark.unit
def test_apply_name_rows_partial_collision(tmp_path: Path) -> None:
    """Mix of colliding and new rows returns only the count of new rows."""
    db = tmp_path / "names.sqlite"
    conn = _open_db(db)
    try:
        # Seed one row.
        with transaction(conn):
            apply_name_rows(conn=conn, rows=[_ROW_A])
        # Insert two rows where one already exists (_ROW_A) and one is new (_ROW_B).
        with transaction(conn):
            delta = apply_name_rows(conn=conn, rows=[_ROW_A, _ROW_B])
    finally:
        conn.close()

    assert delta == 1
