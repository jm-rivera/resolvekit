"""Tests for the formal_names enricher.

Verifies that FYROM is added as an alias for country/MKD after running
enrich_formal_names.
"""

import sqlite3
from pathlib import Path

import pytest

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    entity_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    canonical_name_norm TEXT NOT NULL,
    valid_from TEXT,
    valid_until TEXT,
    attrs_json TEXT
);
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
CREATE TABLE IF NOT EXISTS codes (
    entity_id TEXT NOT NULL,
    system TEXT NOT NULL,
    value TEXT NOT NULL,
    value_norm TEXT NOT NULL,
    PRIMARY KEY (entity_id, system)
);
CREATE TABLE IF NOT EXISTS relations (
    entity_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    valid_from TEXT,
    valid_until TEXT,
    PRIMARY KEY (entity_id, relation_type, target_id)
);
CREATE VIRTUAL TABLE IF NOT EXISTS names_fts USING fts5(entity_id, value_norm);
"""


def _build_mkd_db(tmp_path: Path) -> Path:
    """Create a minimal DB with only country/MKD."""
    db_path = tmp_path / "mkd_test.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT INTO entities VALUES (?, 'geo.country', ?, ?, NULL, NULL, NULL)",
        ("country/MKD", "North Macedonia", "north macedonia"),
    )
    conn.execute(
        "INSERT INTO names VALUES (?, 'canonical', ?, ?, 'en', '', 1)",
        ("country/MKD", "North Macedonia", "north macedonia"),
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.mark.unit
def test_fyrom_alias_added_for_mkd(tmp_path: Path) -> None:
    """After build_formal_name_contribution + apply_contribution, FYROM appears as
    an alias for country/MKD."""
    from resolvekit.builder.formal_names import build_formal_name_contribution
    from resolvekit.builder.pipeline.contribution import apply_contribution
    from resolvekit.builder.sqlite.context import connect_sqlite, transaction

    db_path = _build_mkd_db(tmp_path)
    contrib = build_formal_name_contribution(db_path)
    with connect_sqlite(db_path, busy_timeout_ms=30000) as conn, transaction(conn):
        apply_contribution(conn=conn, contribution=contrib)

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT value FROM names WHERE entity_id = 'country/MKD' AND name_kind = 'alias'"
    ).fetchall()
    conn.close()

    alias_values = {r[0] for r in rows}
    assert "FYROM" in alias_values, (
        f"Expected 'FYROM' in aliases for country/MKD, got: {sorted(alias_values)}"
    )


@pytest.mark.unit
def test_enrich_formal_names_registered_in_enrichers() -> None:
    """build_formal_name_contribution is registered in the COUNTRY_ENTITY_TYPE enricher list."""
    from resolvekit.builder.formal_names import (
        COUNTRY_ENTITY_TYPE,
        build_formal_name_contribution,
    )
    from resolvekit.builder.pipeline.enrich import _ENRICHERS

    assert build_formal_name_contribution in _ENRICHERS[COUNTRY_ENTITY_TYPE]
