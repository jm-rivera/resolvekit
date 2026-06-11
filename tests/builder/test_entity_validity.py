"""Tests for the entity_validity enricher (builder/entity_validity.py).

Verifies that build_entity_validity_contribution + apply_contribution correctly
UPDATE existing entities' valid_from / valid_until columns, skip (with a warning)
entity_ids that are absent from the DB, and are idempotent on re-run.

This test uses a real temporary SQLite DB with the production entities schema —
it proves the UPDATE path is wired end-to-end and that the INSERT OR IGNORE
blocker is bypassed for validity columns.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest
import yaml

# ---------------------------------------------------------------------------
# Helpers: minimal staging DB (matches production entities schema)
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


def _build_staging_db(
    tmp_path: Path,
    *,
    seed_entities: list[tuple[str, str]],
) -> Path:
    """Create a minimal staging DB seeded with (entity_id, canonical_name) pairs.

    All rows are inserted with NULL valid_from / valid_until so the UPDATE
    path has something to set.
    """
    db_path = tmp_path / "geo.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    for entity_id, canonical_name in seed_entities:
        conn.execute(
            "INSERT OR IGNORE INTO entities VALUES (?, 'geo.country', ?, ?, NULL, NULL, NULL)",
            (entity_id, canonical_name, canonical_name.lower()),
        )
    conn.commit()
    conn.close()
    return db_path


def _minimal_validity_yaml(
    tmp_path: Path,
    entries: list[dict[str, Any]],
) -> Path:
    """Write a minimal entity_validity.yaml and return its path."""
    data = {"version": 1, "entities": entries}
    path = tmp_path / "entity_validity.yaml"
    path.write_text(yaml.dump(data, allow_unicode=True))
    return path


def _run_enricher(db_path: Path, yaml_path: Path) -> None:
    """Run build_entity_validity_contribution + apply_contribution with a patched YAML path."""
    from resolvekit.builder import entity_validity as ev_module
    from resolvekit.builder.pipeline.contribution import apply_contribution
    from resolvekit.builder.sqlite.context import connect_sqlite, transaction

    original = ev_module._ENTITY_VALIDITY_YAML_PATH
    ev_module._ENTITY_VALIDITY_YAML_PATH = yaml_path
    try:
        contrib = ev_module.build_entity_validity_contribution(db_path)
        with connect_sqlite(db_path, busy_timeout_ms=30000) as conn, transaction(conn):
            apply_contribution(conn=conn, contribution=contrib)
    finally:
        ev_module._ENTITY_VALIDITY_YAML_PATH = original


def _fetch_validity(db_path: Path, entity_id: str) -> tuple[str | None, str | None]:
    """Return (valid_from, valid_until) for the given entity_id."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT valid_from, valid_until FROM entities WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, f"entity {entity_id!r} not found in DB"
    return (row[0], row[1])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_entity_validity_sets_valid_from_only(tmp_path: Path) -> None:
    """A new state (valid_from only) has valid_from set and valid_until remains NULL."""
    db_path = _build_staging_db(
        tmp_path,
        seed_entities=[("country/SSD", "South Sudan")],
    )
    yaml_path = _minimal_validity_yaml(
        tmp_path,
        [{"entity_id": "country/SSD", "valid_from": "2011-07-09"}],
    )

    _run_enricher(db_path, yaml_path)

    vf, vu = _fetch_validity(db_path, "country/SSD")
    assert vf == "2011-07-09"
    assert vu is None


@pytest.mark.unit
def test_entity_validity_sets_both_dates(tmp_path: Path) -> None:
    """A dissolved state (valid_from + valid_until) has both columns populated."""
    db_path = _build_staging_db(
        tmp_path,
        seed_entities=[("country/CSK", "Czechoslovakia")],
    )
    yaml_path = _minimal_validity_yaml(
        tmp_path,
        [
            {
                "entity_id": "country/CSK",
                "valid_from": "1918-10-28",
                "valid_until": "1993-01-01",
            }
        ],
    )

    _run_enricher(db_path, yaml_path)

    vf, vu = _fetch_validity(db_path, "country/CSK")
    assert vf == "1918-10-28"
    assert vu == "1993-01-01"


@pytest.mark.unit
def test_entity_validity_sets_valid_until_only(tmp_path: Path) -> None:
    """An entity with valid_until only (valid_from absent) sets valid_until, valid_from NULL."""
    db_path = _build_staging_db(
        tmp_path,
        seed_entities=[("country/CTE", "Canton and Enderbury Islands")],
    )
    yaml_path = _minimal_validity_yaml(
        tmp_path,
        [{"entity_id": "country/CTE", "valid_until": "1979-07-12"}],
    )

    _run_enricher(db_path, yaml_path)

    vf, vu = _fetch_validity(db_path, "country/CTE")
    assert vf is None
    assert vu == "1979-07-12"


@pytest.mark.unit
def test_entity_validity_missing_entity_id_warns_and_skips(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An entity_id absent from the DB is counted, logged as a warning, and skipped without error."""
    db_path = _build_staging_db(
        tmp_path,
        seed_entities=[("country/SSD", "South Sudan")],
    )
    yaml_path = _minimal_validity_yaml(
        tmp_path,
        [
            {"entity_id": "country/SSD", "valid_from": "2011-07-09"},
            # This entity is NOT in the DB — should warn and skip.
            {"entity_id": "country/DOESNOTEXIST", "valid_from": "2000-01-01"},
        ],
    )

    with caplog.at_level(logging.WARNING):
        _run_enricher(db_path, yaml_path)

    # The valid entity was still updated.
    vf, _ = _fetch_validity(db_path, "country/SSD")
    assert vf == "2011-07-09"

    # A warning was logged for the absent entity_id.
    assert any("DOESNOTEXIST" in msg for msg in caplog.messages)


@pytest.mark.unit
def test_entity_validity_multiple_entities(tmp_path: Path) -> None:
    """Multiple entities in one YAML are each updated correctly."""
    db_path = _build_staging_db(
        tmp_path,
        seed_entities=[
            ("country/SSD", "South Sudan"),
            ("country/CSK", "Czechoslovakia"),
        ],
    )
    yaml_path = _minimal_validity_yaml(
        tmp_path,
        [
            {"entity_id": "country/SSD", "valid_from": "2011-07-09"},
            {
                "entity_id": "country/CSK",
                "valid_from": "1918-10-28",
                "valid_until": "1993-01-01",
            },
        ],
    )

    _run_enricher(db_path, yaml_path)

    ssd_vf, ssd_vu = _fetch_validity(db_path, "country/SSD")
    assert ssd_vf == "2011-07-09"
    assert ssd_vu is None

    csk_vf, csk_vu = _fetch_validity(db_path, "country/CSK")
    assert csk_vf == "1918-10-28"
    assert csk_vu == "1993-01-01"


@pytest.mark.unit
def test_entity_validity_idempotent(tmp_path: Path) -> None:
    """Running the enricher twice produces the same column values (idempotent)."""
    db_path = _build_staging_db(
        tmp_path,
        seed_entities=[("country/CSK", "Czechoslovakia")],
    )
    yaml_path = _minimal_validity_yaml(
        tmp_path,
        [
            {
                "entity_id": "country/CSK",
                "valid_from": "1918-10-28",
                "valid_until": "1993-01-01",
            }
        ],
    )

    _run_enricher(db_path, yaml_path)
    _run_enricher(db_path, yaml_path)

    vf, vu = _fetch_validity(db_path, "country/CSK")
    assert vf == "1918-10-28"
    assert vu == "1993-01-01"


@pytest.mark.unit
def test_entity_validity_existing_entities_unaffected(tmp_path: Path) -> None:
    """Entities NOT in the YAML retain their original (NULL) validity columns."""
    db_path = _build_staging_db(
        tmp_path,
        seed_entities=[
            ("country/SSD", "South Sudan"),
            ("country/DEU", "Germany"),  # not in YAML
        ],
    )
    yaml_path = _minimal_validity_yaml(
        tmp_path,
        [{"entity_id": "country/SSD", "valid_from": "2011-07-09"}],
    )

    _run_enricher(db_path, yaml_path)

    deu_vf, deu_vu = _fetch_validity(db_path, "country/DEU")
    assert deu_vf is None
    assert deu_vu is None


@pytest.mark.unit
def test_entity_validity_does_not_overwrite_other_columns(tmp_path: Path) -> None:
    """The UPDATE only touches valid_from / valid_until; canonical_name is preserved."""
    db_path = _build_staging_db(
        tmp_path,
        seed_entities=[("country/SSD", "South Sudan")],
    )
    yaml_path = _minimal_validity_yaml(
        tmp_path,
        [{"entity_id": "country/SSD", "valid_from": "2011-07-09"}],
    )

    _run_enricher(db_path, yaml_path)

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT canonical_name, entity_type, valid_from, valid_until FROM entities WHERE entity_id = ?",
        ("country/SSD",),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "South Sudan"
    assert row[1] == "geo.country"
    assert row[2] == "2011-07-09"
    assert row[3] is None
