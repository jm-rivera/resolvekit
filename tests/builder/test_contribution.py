"""Unit tests for GraphContribution and apply_contribution.

Tests:
- apply_contribution inserts all four tables and returns correct deltas.
- apply_contribution uses INSERT OR IGNORE (not OR REPLACE) for all tables.
- apply_contribution cascades deletes for entity_ids_to_delete.
- apply_contribution is idempotent on re-run.
"""

from __future__ import annotations

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


def _seed_entity(db: Path, entity_id: str, canonical_name: str) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT OR IGNORE INTO entities VALUES (?, 'geo.country', ?, ?, NULL, NULL, '{}')",
        (entity_id, canonical_name, canonical_name.lower()),
    )
    conn.commit()
    conn.close()


def _query_one(db: Path, sql: str, params: tuple = ()) -> tuple | None:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def _run(db: Path, contrib: GraphContribution) -> dict[str, int]:
    with connect_sqlite(db, busy_timeout_ms=30000) as conn, transaction(conn):
        return apply_contribution(conn=conn, contribution=contrib)


@pytest.mark.unit
def test_apply_contribution_inserts_all_tables(tmp_path: Path) -> None:
    """One row per table → deltas {entities:1, names:1, codes:1, relations:1}."""
    db = _make_db(tmp_path)
    # seed a target entity for the relation
    _seed_entity(db, "country/DEU", "Germany")

    contrib = GraphContribution(
        entities=[
            {
                "entity_id": "country/X",
                "entity_type": "geo.country",
                "canonical_name": "X",
                "canonical_name_norm": "x",
                "valid_from": None,
                "valid_until": None,
                "attrs_json": "{}",
            }
        ],
        names=[
            {
                "entity_id": "country/X",
                "name_kind": "alias",
                "value": "Ex",
                "value_norm": "ex",
                "lang": "en",
                "script": "",
                "is_preferred": 0,
            }
        ],
        codes=[
            {
                "entity_id": "country/X",
                "system": "iso3",
                "value": "XXX",
                "value_norm": "xxx",
            }
        ],
        relations=[
            {
                "entity_id": "country/X",
                "relation_type": "part_of",
                "target_id": "country/DEU",
                "valid_from": None,
                "valid_until": None,
            }
        ],
    )

    deltas = _run(db, contrib)
    assert deltas == {"entities": 1, "names": 1, "codes": 1, "relations": 1}


@pytest.mark.unit
def test_apply_contribution_uses_or_ignore_not_replace(tmp_path: Path) -> None:
    """INSERT OR IGNORE: applying a contribution with the same entity_id but a
    different canonical_name must NOT overwrite the existing canonical_name."""
    db = _make_db(tmp_path)
    _seed_entity(db, "country/X", "Original")

    contrib = GraphContribution(
        entities=[
            {
                "entity_id": "country/X",
                "entity_type": "geo.country",
                "canonical_name": "OVERWRITTEN",
                "canonical_name_norm": "overwritten",
                "valid_from": None,
                "valid_until": None,
                "attrs_json": "{}",
            }
        ]
    )

    _run(db, contrib)

    row = _query_one(
        db, "SELECT canonical_name FROM entities WHERE entity_id='country/X'"
    )
    assert row is not None
    assert row[0] == "Original", (
        f"canonical_name must not be overwritten by apply_contribution; got: {row[0]!r}"
    )


@pytest.mark.unit
def test_apply_contribution_removal_cascades(tmp_path: Path) -> None:
    """entity_ids_to_delete cascades across names/codes/relations/entities."""
    db = _make_db(tmp_path)
    # Seed entity with dependent rows
    _seed_entity(db, "country/X", "X")
    _seed_entity(db, "country/Y", "Y")
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT OR IGNORE INTO names VALUES ('country/X','alias','Xalias','xalias','en','',0)"
    )
    conn.execute("INSERT OR IGNORE INTO codes VALUES ('country/X','iso3','XXX','xxx')")
    conn.execute(
        "INSERT OR IGNORE INTO relations VALUES ('country/X','part_of','country/Y',NULL,NULL)"
    )
    # relation where country/X is the TARGET
    conn.execute(
        "INSERT OR IGNORE INTO relations VALUES ('country/Y','part_of','country/X',NULL,NULL)"
    )
    conn.commit()
    conn.close()

    contrib = GraphContribution(entity_ids_to_delete=["country/X"])
    deltas = _run(db, contrib)

    # entity gone
    assert _query_one(db, "SELECT 1 FROM entities WHERE entity_id='country/X'") is None
    # names gone
    assert _query_one(db, "SELECT 1 FROM names WHERE entity_id='country/X'") is None
    # codes gone
    assert _query_one(db, "SELECT 1 FROM codes WHERE entity_id='country/X'") is None
    # relation where entity_id was country/X gone
    assert _query_one(db, "SELECT 1 FROM relations WHERE entity_id='country/X'") is None
    # relation where target_id was country/X gone
    assert _query_one(db, "SELECT 1 FROM relations WHERE target_id='country/X'") is None
    # country/Y untouched
    assert (
        _query_one(db, "SELECT 1 FROM entities WHERE entity_id='country/Y'") is not None
    )
    # names delta is negative (1 name row removed)
    assert deltas["names"] == -1
    assert deltas["entities"] == -1


@pytest.mark.unit
def test_apply_contribution_entity_attrs_merges(tmp_path: Path) -> None:
    """entity_attrs rows merge into existing attrs_json without overwriting other keys."""
    db = _make_db(tmp_path)
    _seed_entity(db, "country/USA", "United States")
    # Pre-set an existing attrs key
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE entities SET attrs_json = ? WHERE entity_id = ?",
        ('{"latitude": "39.8"}', "country/USA"),
    )
    conn.commit()
    conn.close()

    contrib = GraphContribution(
        entities=[
            {
                "entity_id": "country/DEU",
                "entity_type": "geo.country",
                "canonical_name": "Germany",
                "canonical_name_norm": "germany",
                "valid_from": None,
                "valid_until": None,
                "attrs_json": "{}",
            }
        ],
        entity_attrs=[
            {"entity_id": "country/USA", "attrs": {"prominence": 0.95}},
        ],
    )

    _run(db, contrib)

    row = _query_one(
        db, "SELECT attrs_json FROM entities WHERE entity_id = 'country/USA'"
    )
    assert row is not None
    import json as _json

    attrs = _json.loads(row[0])
    assert attrs == {"latitude": "39.8", "prominence": 0.95}


@pytest.mark.unit
def test_apply_contribution_idempotent(tmp_path: Path) -> None:
    """Applying the same contribution twice → second run returns all-zero deltas."""
    db = _make_db(tmp_path)

    contrib = GraphContribution(
        entities=[
            {
                "entity_id": "country/X",
                "entity_type": "geo.country",
                "canonical_name": "X",
                "canonical_name_norm": "x",
                "valid_from": None,
                "valid_until": None,
                "attrs_json": "{}",
            }
        ],
        names=[
            {
                "entity_id": "country/X",
                "name_kind": "alias",
                "value": "Ex",
                "value_norm": "ex",
                "lang": "en",
                "script": "",
                "is_preferred": 0,
            }
        ],
    )

    first = _run(db, contrib)
    assert first["entities"] == 1
    assert first["names"] == 1

    second = _run(db, contrib)
    assert second == {"entities": 0, "names": 0, "codes": 0, "relations": 0}
