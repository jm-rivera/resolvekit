"""Unit-level characterization test for _enrich_region_filter_placeholders.

Pins the negative-int return value and the cascading DELETE across names/codes/
relations/entities for a known mix of geo.region keep/remove entities.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from resolvekit.builder.pipeline.contribution import apply_contribution
from resolvekit.builder.pipeline.enrich import _build_region_filter_contribution
from resolvekit.builder.sqlite.context import connect_sqlite, transaction

# ---------------------------------------------------------------------------
# Schema — reproduced locally from test_enrich_fts_ordering.py; do NOT import
# across test files.
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Seed data
#
# KEEP entities — should survive the filter:
#   region/EU          — name "European Union"           (no pattern match)
#   undata-geo/G00001020 — name "Federal Republic of Germany"
#                          (G000*, not G009*; no [former])
#
# REMOVE entities — matched by at least one filter pattern:
#   undata-geo/G00001950 — name "Micronesia [former]"        (%[former]%)
#   undata-geo/G00900010 — name "Not applicable"             (id undata-geo/G009%)
#   undata-geo/C07400000 — name "Cocos (Keeling) Islands: All cities or breakdown
#                               by cities not available"
#                          (%: All cities or breakdown%)
# ---------------------------------------------------------------------------

_KEEP = [
    ("region/EU", "European Union"),
    ("undata-geo/G00001020", "Federal Republic of Germany"),
]

_REMOVE = [
    ("undata-geo/G00001950", "Micronesia [former]"),
    ("undata-geo/G00900010", "Not applicable"),
    (
        "undata-geo/C07400000",
        "Cocos (Keeling) Islands: All cities or breakdown by cities not available",
    ),
]


def _seed_db(db: Path) -> None:
    conn = sqlite3.connect(db)
    conn.executescript(_SCHEMA)

    # Insert all geo.region entities
    for eid, name in _KEEP + _REMOVE:
        conn.execute(
            "INSERT OR IGNORE INTO entities VALUES (?, 'geo.region', ?, ?, NULL, NULL, '{}')",
            (eid, name, name.lower()),
        )
        # One canonical names row per entity
        conn.execute(
            "INSERT OR IGNORE INTO names VALUES (?, 'canonical', ?, ?, 'en', '', 1)",
            (eid, name, name.lower()),
        )

    # For each REMOVE entity: one codes row, one relations row where it is
    # entity_id, and one relations row where a KEEP entity points to it as
    # target_id (exercises the DELETE ... WHERE target_id IN branch).
    for eid, _ in _REMOVE:
        conn.execute(
            "INSERT OR IGNORE INTO codes VALUES (?, 'undata', ?, ?)",
            (eid, eid, eid.lower()),
        )
        # relation: removed entity → region/EU (entity_id branch)
        conn.execute(
            "INSERT OR IGNORE INTO relations VALUES (?, 'part_of', 'region/EU', NULL, NULL)",
            (eid,),
        )
        # relation: region/EU → removed entity (target_id branch)
        conn.execute(
            "INSERT OR IGNORE INTO relations VALUES ('region/EU', 'has_part', ?, NULL, NULL)",
            (eid,),
        )

    conn.commit()
    conn.close()


def _query_entity_ids(db: Path) -> set[str]:
    conn = sqlite3.connect(db)
    try:
        return {row[0] for row in conn.execute("SELECT entity_id FROM entities")}
    finally:
        conn.close()


def _query_names_for(db: Path, entity_id: str) -> list[str]:
    conn = sqlite3.connect(db)
    try:
        return [
            row[0]
            for row in conn.execute(
                "SELECT value FROM names WHERE entity_id=?", (entity_id,)
            )
        ]
    finally:
        conn.close()


def _query_codes_for(db: Path, entity_id: str) -> list[str]:
    conn = sqlite3.connect(db)
    try:
        return [
            row[0]
            for row in conn.execute(
                "SELECT value FROM codes WHERE entity_id=?", (entity_id,)
            )
        ]
    finally:
        conn.close()


def _query_relation(db: Path, entity_id: str, target_id: str) -> tuple | None:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT 1 FROM relations WHERE entity_id=? AND target_id=?",
            (entity_id, target_id),
        ).fetchone()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_region_filter_returns_negative_and_cascades(tmp_path: Path) -> None:
    """_build_region_filter_contribution returns the 3 matched geo.region entity ids
    and apply_contribution cascades deletes to names/codes/relations.
    """
    db = tmp_path / "geo.sqlite"
    _seed_db(db)

    contrib = _build_region_filter_contribution(db)

    # Contribution must identify exactly the 3 REMOVE entity ids.
    assert sorted(contrib.entity_ids_to_delete) == sorted(eid for eid, _ in _REMOVE)

    with connect_sqlite(db, busy_timeout_ms=30000) as conn, transaction(conn):
        deltas = apply_contribution(conn=conn, contribution=contrib)

    # 3 entities removed, each owned 1 names row → names delta = -3
    assert deltas["names"] == -3  # after_names(2) - before_names(5)

    # --- entities ---
    # Only the KEEP entities remain
    kept_ids = _query_entity_ids(db)
    assert kept_ids == {"region/EU", "undata-geo/G00001020"}

    # --- names cascade ---
    # KEEP entities still have their names row
    assert _query_names_for(db, "region/EU") == ["European Union"]
    assert _query_names_for(db, "undata-geo/G00001020") == [
        "Federal Republic of Germany"
    ]
    # REMOVE entities have no names rows left
    for eid, _ in _REMOVE:
        assert _query_names_for(db, eid) == [], f"names rows not deleted for {eid}"

    # --- codes cascade ---
    for eid, _ in _REMOVE:
        assert _query_codes_for(db, eid) == [], f"codes rows not deleted for {eid}"

    # --- relations cascade: entity_id branch ---
    for eid, _ in _REMOVE:
        assert _query_relation(db, eid, "region/EU") is None, (
            f"relation (entity_id={eid}) not deleted"
        )

    # --- relations cascade: target_id branch ---
    # region/EU had part_of relations pointing to removed entities; they must be gone
    for eid, _ in _REMOVE:
        assert _query_relation(db, "region/EU", eid) is None, (
            f"relation (target_id={eid}) not deleted from KEEP entity"
        )

    # Idempotency: second build → empty entity_ids_to_delete → all-zero deltas.
    second_contrib = _build_region_filter_contribution(db)
    assert second_contrib.entity_ids_to_delete == []
    with connect_sqlite(db, busy_timeout_ms=30000) as conn, transaction(conn):
        second_deltas = apply_contribution(conn=conn, contribution=second_contrib)
    assert second_deltas == {"entities": 0, "names": 0, "codes": 0, "relations": 0}
