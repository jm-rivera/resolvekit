"""Tests for the entity_attrs apply path on GraphContribution.

Covers:
- Merging prominence into an existing attrs_json (preserving other keys).
- Idempotency: applying the same entity_attrs twice yields identical output.
- Unknown entity_id is a no-op (no rows changed, no exception).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from resolvekit.builder.pipeline.contribution import (
    GraphContribution,
    apply_contribution,
)
from resolvekit.builder.sqlite.context import connect_sqlite, transaction

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


def _make_db(tmp_path: Path) -> Path:
    db = tmp_path / "test.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()
    return db


def _seed_entity(db: Path, entity_id: str, attrs_json: str = "{}") -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT OR IGNORE INTO entities VALUES (?, 'geo.country', ?, ?, NULL, NULL, ?)",
        (entity_id, entity_id, entity_id.lower(), attrs_json),
    )
    conn.commit()
    conn.close()


def _get_attrs(db: Path, entity_id: str) -> dict:
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT attrs_json FROM entities WHERE entity_id = ?", (entity_id,)
        ).fetchone()
        if row is None:
            return {}
        return json.loads(row[0]) if row[0] else {}
    finally:
        conn.close()


def _run(db: Path, contrib: GraphContribution) -> dict[str, int]:
    with connect_sqlite(db, busy_timeout_ms=30000) as conn, transaction(conn):
        return apply_contribution(conn=conn, contribution=contrib)


@pytest.mark.unit
def test_entity_attrs_merges_prominence(tmp_path: Path) -> None:
    """Applying entity_attrs merges prominence into existing attrs_json without
    disturbing other keys."""
    db = _make_db(tmp_path)
    _seed_entity(db, "country/USA", '{"latitude": "39.8"}')

    contrib = GraphContribution(
        entity_attrs=[{"entity_id": "country/USA", "attrs": {"prominence": 0.95}}]
    )
    _run(db, contrib)

    attrs = _get_attrs(db, "country/USA")
    assert attrs == {"latitude": "39.8", "prominence": 0.95}


@pytest.mark.unit
def test_entity_attrs_idempotent(tmp_path: Path) -> None:
    """Applying the same entity_attrs twice yields byte-for-byte identical attrs_json."""
    db = _make_db(tmp_path)
    _seed_entity(db, "country/USA", '{"latitude": "39.8"}')

    contrib = GraphContribution(
        entity_attrs=[{"entity_id": "country/USA", "attrs": {"prominence": 0.95}}]
    )
    _run(db, contrib)
    first = _get_attrs(db, "country/USA")

    _run(db, contrib)
    second = _get_attrs(db, "country/USA")

    assert first == second == {"latitude": "39.8", "prominence": 0.95}


@pytest.mark.unit
def test_entity_attrs_null_attrs_json(tmp_path: Path) -> None:
    """Applying entity_attrs to an entity with NULL attrs_json produces a clean
    JSON object containing the new key (no KeyError / json.loads failure)."""
    db = _make_db(tmp_path)
    _seed_entity(db, "country/USA", None)  # type: ignore[arg-type]

    contrib = GraphContribution(
        entity_attrs=[{"entity_id": "country/USA", "attrs": {"prominence": 0.75}}]
    )
    _run(db, contrib)

    attrs = _get_attrs(db, "country/USA")
    assert attrs == {"prominence": 0.75}


@pytest.mark.unit
def test_entity_attrs_unknown_entity_id_is_noop(tmp_path: Path) -> None:
    """entity_attrs rows referencing a non-existent entity_id raise no exception
    and leave the DB unchanged."""
    db = _make_db(tmp_path)
    _seed_entity(db, "country/USA", "{}")

    contrib = GraphContribution(
        entity_attrs=[
            {"entity_id": "country/DOES_NOT_EXIST", "attrs": {"prominence": 0.5}}
        ]
    )
    # Must not raise
    _run(db, contrib)

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT COUNT(*) FROM entities WHERE entity_id = 'country/DOES_NOT_EXIST'"
    ).fetchone()
    conn.close()
    assert row[0] == 0
