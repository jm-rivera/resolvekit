"""Unit tests for the groups enricher (builder/groups.py).

Tests that enrich_groups correctly creates entities, aliases, member_of
relations, handles idempotency, warns on unknown iso3, and writes null
bounds for snapshot entries.
"""

import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest
import yaml

# ---------------------------------------------------------------------------
# Helpers: minimal staging DB
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

# Minimal country set: DEU, FRA, GBR (enough to test member_of without loading all 200+)
_SEED_COUNTRIES = [
    ("country/DEU", "Germany", "DEU"),
    ("country/FRA", "France", "FRA"),
    ("country/GBR", "United Kingdom", "GBR"),
]


def _build_staging_db(tmp_path: Path) -> Path:
    """Create a minimal staging DB with a few country entities and iso3 codes."""
    db_path = tmp_path / "geo.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    for eid, name, iso3 in _SEED_COUNTRIES:
        conn.execute(
            "INSERT OR IGNORE INTO entities VALUES (?, 'geo.country', ?, ?, NULL, NULL, NULL)",
            (eid, name, name.lower()),
        )
        conn.execute(
            "INSERT OR IGNORE INTO codes VALUES (?, 'iso3', ?, ?)",
            (eid, iso3, iso3.lower()),
        )
    conn.commit()
    conn.close()
    return db_path


def _minimal_groups_yaml(tmp_path: Path, groups_data: list[dict[str, Any]]) -> Path:
    """Write a minimal groups.yaml and return its path."""
    data = {"version": 1, "groups": groups_data}
    path = tmp_path / "groups.yaml"
    path.write_text(yaml.dump(data, allow_unicode=True))
    return path


# ---------------------------------------------------------------------------
# Fixtures and helpers for patching the groups YAML path
# ---------------------------------------------------------------------------


def _run_enrich_groups(db_path: Path, groups_yaml_path: Path) -> None:
    """Run build_group_contribution + apply_contribution with a patched YAML path."""
    from resolvekit.builder import groups as groups_module
    from resolvekit.builder.pipeline.contribution import apply_contribution
    from resolvekit.builder.sqlite.context import connect_sqlite, transaction

    original = groups_module._GROUPS_YAML_PATH
    groups_module._GROUPS_YAML_PATH = groups_yaml_path
    try:
        contrib = groups_module.build_group_contribution(db_path)
        with connect_sqlite(db_path, busy_timeout_ms=30000) as conn, transaction(conn):
            apply_contribution(conn=conn, contribution=contrib)
    finally:
        groups_module._GROUPS_YAML_PATH = original


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_enrich_groups_inserts_entities(tmp_path: Path) -> None:
    """Group entity appears in entities table after enrichment."""
    db_path = _build_staging_db(tmp_path)
    yaml_path = _minimal_groups_yaml(
        tmp_path,
        [
            {
                "id": "groups/TEST_ORG",
                "type": "geo.organization",
                "canonical_name": "Test Organisation",
                "aliases": ["TEST"],
                "snapshot": False,
                "members": [{"iso3": "DEU"}],
            }
        ],
    )
    _run_enrich_groups(db_path, yaml_path)

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT entity_type, canonical_name FROM entities WHERE entity_id = ?",
        ("groups/TEST_ORG",),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "geo.organization"
    assert row[1] == "Test Organisation"


@pytest.mark.unit
def test_enrich_groups_inserts_aliases(tmp_path: Path) -> None:
    """Alias rows appear in names table for each declared alias."""
    db_path = _build_staging_db(tmp_path)
    yaml_path = _minimal_groups_yaml(
        tmp_path,
        [
            {
                "id": "groups/TEST_ORG",
                "type": "geo.organization",
                "canonical_name": "Test Organisation",
                "aliases": ["TEST", "T.E.S.T."],
                "snapshot": False,
                "members": [],
            }
        ],
    )
    _run_enrich_groups(db_path, yaml_path)

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT value FROM names WHERE entity_id = ? AND name_kind = 'alias'",
        ("groups/TEST_ORG",),
    ).fetchall()
    conn.close()

    aliases = {r[0] for r in rows}
    assert "TEST" in aliases
    assert "T.E.S.T." in aliases


@pytest.mark.unit
def test_enrich_groups_inserts_member_of_relations(tmp_path: Path) -> None:
    """member_of relations appear with correct valid_from / valid_until."""
    db_path = _build_staging_db(tmp_path)
    yaml_path = _minimal_groups_yaml(
        tmp_path,
        [
            {
                "id": "groups/TEST_ORG",
                "type": "geo.organization",
                "canonical_name": "Test Organisation",
                "aliases": ["TEST"],
                "snapshot": False,
                "members": [
                    {"iso3": "DEU", "valid_from": "2000-01-01"},
                    {
                        "iso3": "FRA",
                        "valid_from": "1999-01-01",
                        "valid_until": "2010-01-01",
                    },
                    {"iso3": "GBR"},
                ],
            }
        ],
    )
    _run_enrich_groups(db_path, yaml_path)

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """
        SELECT entity_id, valid_from, valid_until FROM relations
        WHERE target_id = 'groups/TEST_ORG' AND relation_type = 'member_of'
        """,
    ).fetchall()
    conn.close()

    by_eid = {r[0]: (r[1], r[2]) for r in rows}
    assert by_eid["country/DEU"] == ("2000-01-01", None)
    assert by_eid["country/FRA"] == ("1999-01-01", "2010-01-01")
    assert by_eid["country/GBR"] == (None, None)


@pytest.mark.unit
def test_enrich_groups_idempotent(tmp_path: Path) -> None:
    """Calling enrich_groups twice produces the same row counts."""
    db_path = _build_staging_db(tmp_path)
    yaml_path = _minimal_groups_yaml(
        tmp_path,
        [
            {
                "id": "groups/TEST_ORG",
                "type": "geo.organization",
                "canonical_name": "Test Organisation",
                "aliases": ["TEST"],
                "snapshot": False,
                "members": [{"iso3": "DEU"}, {"iso3": "FRA"}],
            }
        ],
    )

    _run_enrich_groups(db_path, yaml_path)

    conn = sqlite3.connect(db_path)
    entities_after_first = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    names_after_first = conn.execute("SELECT COUNT(*) FROM names").fetchone()[0]
    relations_after_first = conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
    conn.close()

    _run_enrich_groups(db_path, yaml_path)

    conn = sqlite3.connect(db_path)
    assert (
        conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        == entities_after_first
    )
    assert conn.execute("SELECT COUNT(*) FROM names").fetchone()[0] == names_after_first
    assert (
        conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
        == relations_after_first
    )
    conn.close()


@pytest.mark.unit
def test_enrich_groups_unknown_iso3_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Unknown iso3 code emits a warning and is skipped; valid members still inserted."""
    db_path = _build_staging_db(tmp_path)
    yaml_path = _minimal_groups_yaml(
        tmp_path,
        [
            {
                "id": "groups/TEST_ORG",
                "type": "geo.organization",
                "canonical_name": "Test Organisation",
                "aliases": ["TEST"],
                "snapshot": False,
                "members": [
                    {"iso3": "ZZZ"},  # bogus
                    {"iso3": "DEU"},  # valid
                ],
            }
        ],
    )

    with caplog.at_level(logging.WARNING):
        _run_enrich_groups(db_path, yaml_path)

    assert any("ZZZ" in msg for msg in caplog.messages)

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT entity_id FROM relations WHERE target_id = 'groups/TEST_ORG'"
    ).fetchall()
    conn.close()

    entity_ids = {r[0] for r in rows}
    assert "country/DEU" in entity_ids
    # ZZZ is not in the DB; its relation should be skipped entirely
    assert not any("ZZZ" in eid for eid in entity_ids)


@pytest.mark.unit
def test_enrich_groups_snapshot_null_bounds(tmp_path: Path) -> None:
    """Snapshot group: all member relations have null valid_from and valid_until."""
    db_path = _build_staging_db(tmp_path)
    yaml_path = _minimal_groups_yaml(
        tmp_path,
        [
            {
                "id": "groups/SNAP28",
                "type": "geo.organization",
                "canonical_name": "Snapshot Group 28",
                "aliases": ["SNAP28"],
                "snapshot": True,
                "members": [
                    {"iso3": "DEU"},
                    {"iso3": "FRA"},
                    {"iso3": "GBR"},
                ],
            }
        ],
    )
    _run_enrich_groups(db_path, yaml_path)

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT valid_from, valid_until FROM relations WHERE target_id = 'groups/SNAP28'"
    ).fetchall()
    conn.close()

    assert len(rows) == 3
    for vf, vu in rows:
        assert vf is None, f"Expected null valid_from, got {vf!r}"
        assert vu is None, f"Expected null valid_until, got {vu!r}"


@pytest.mark.unit
def test_enrich_groups_snapshot_entity_attrs_json(tmp_path: Path) -> None:
    """Snapshot entity has attrs_json containing snapshot=true."""
    db_path = _build_staging_db(tmp_path)
    yaml_path = _minimal_groups_yaml(
        tmp_path,
        [
            {
                "id": "groups/SNAP28",
                "type": "geo.organization",
                "canonical_name": "Snapshot Group 28",
                "aliases": ["SNAP28"],
                "snapshot": True,
                "members": [],
            }
        ],
    )
    _run_enrich_groups(db_path, yaml_path)

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT attrs_json FROM entities WHERE entity_id = 'groups/SNAP28'"
    ).fetchone()
    conn.close()

    import json

    assert row is not None
    attrs = json.loads(row[0])
    assert attrs.get("snapshot") is True
