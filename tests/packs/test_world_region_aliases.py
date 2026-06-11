"""Tests for world_region alias resolution against the bundled geo.regions pack.

Covers the 9 eval queries from the v4 geo eval world_region category.  Several
target undata-geo entities whose canonical name does not match the plain
user-facing label (e.g. "MDG Region: Sub-Saharan Africa", "Latin America: Low
and middle income"), pinning the alias-injection fix in
builder/data/region_aliases.yaml + enrich.py.

Since the M.49 sub-region promotion (commit 78be69e), labels that match a UN
M.49 geo.subregion canonical name (or close alias) now resolve to that m49/
entity instead of the undata-geo aggregate — the m49 sub-region is the more
precise target.  Those cases are pinned to their m49/ IDs below.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REGIONS_PACK_PATH = (
    Path(__file__).parent.parent.parent
    / "src"
    / "resolvekit"
    / "_data"
    / "geo"
    / "regions"
)


@pytest.fixture(scope="module")
def regions_resolver():
    """Resolver backed solely by the bundled geo.regions pack."""
    from resolvekit.core.api.resolver import Resolver

    resolver = Resolver.from_datapacks(datapack_paths=[REGIONS_PACK_PATH])
    yield resolver
    resolver.close()


# ---------------------------------------------------------------------------
# Parametrized baseline: all 9 world_region eval queries must resolve
# ---------------------------------------------------------------------------

_WORLD_REGION_CASES = [
    # (query_text, expected_entity_id, description)
    ("Sub-Saharan Africa", "m49/202", "M.49 sub-region (exact canonical name)"),
    ("Sub Saharan Africa", "undata-geo/G01100220", "MDG Region alias (no hyphen)"),
    (
        "Latin America and the Caribbean",
        "m49/419",
        "M.49 sub-region (exact canonical name)",
    ),
    ("Latin America", "m49/419", "M.49 sub-region (Latin America alias)"),
    ("MENA", "undata-geo/G00152000", "MENA acronym"),
    (
        "Middle East and North Africa",
        "undata-geo/G00152000",
        "canonical name exact match",
    ),
    ("Western Europe", "m49/155", "M.49 sub-region (exact canonical name)"),
    ("Northern Africa", "m49/015", "M.49 sub-region (exact canonical name)"),
    ("South Asia", "m49/034", "M.49 sub-region (Southern Asia alias)"),
]


@pytest.mark.parametrize(
    "text,expected_id,desc",
    _WORLD_REGION_CASES,
    ids=[c[0] for c in _WORLD_REGION_CASES],
)
def test_world_region_resolves_to_expected_entity(
    regions_resolver, text: str, expected_id: str, desc: str
) -> None:
    """Each world_region query must resolve to the expected undata-geo entity."""
    result = regions_resolver.resolve(text)
    assert result.is_resolved, (
        f"{text!r} ({desc}): expected RESOLVED to {expected_id}, "
        f"got status={result.status} candidates={[c.entity_id for c in result.candidates[:3]]}"
    )
    assert result.entity_id == expected_id, (
        f"{text!r} ({desc}): resolved to {result.entity_id!r}, expected {expected_id!r}"
    )


# ---------------------------------------------------------------------------
# Unit: region_aliases enricher produces the expected rows
# ---------------------------------------------------------------------------


def test_build_region_aliases_contribution_produces_expected_names(
    tmp_path: Path,
) -> None:
    """_build_region_aliases_contribution returns the correct alias rows.

    Uses a minimal SQLite with just the 6 target entities so the test
    is deterministic and independent of the bundled pack state.
    """
    import sqlite3

    from resolvekit.builder.pipeline.enrich import _build_region_aliases_contribution

    db_path = tmp_path / "entities.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE entities (
            entity_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            canonical_name_norm TEXT NOT NULL,
            valid_from TEXT,
            valid_until TEXT,
            attrs_json TEXT
        );
        INSERT INTO entities VALUES
            ('undata-geo/G01100220', 'geo.region', 'MDG Region: Sub-Saharan Africa', 'mdg region: sub-saharan africa', NULL, NULL, NULL),
            ('undata-geo/G01100290', 'geo.region', 'MDG Region: Latin America and the Caribbean', 'mdg region: latin america and the caribbean', NULL, NULL, NULL),
            ('undata-geo/G00138200', 'geo.region', 'Latin America: Low and middle income', 'latin america: low and middle income', NULL, NULL, NULL),
            ('undata-geo/G00152000', 'geo.region', 'Middle East and North Africa', 'middle east and north africa', NULL, NULL, NULL),
            ('undata-geo/G00130000', 'geo.region', 'Northern, Southern and Western Europe', 'northern, southern and western europe', NULL, NULL, NULL),
            ('undata-geo/G01100210', 'geo.region', 'MDG Region: Northern Africa', 'mdg region: northern africa', NULL, NULL, NULL);
    """)
    conn.close()

    contribution = _build_region_aliases_contribution(db_path)

    alias_map: dict[str, list[str]] = {}
    for row in contribution.names:
        alias_map.setdefault(row["entity_id"], []).append(row["value"])

    assert "Sub-Saharan Africa" in alias_map.get("undata-geo/G01100220", [])
    assert "Sub Saharan Africa" in alias_map.get("undata-geo/G01100220", [])
    assert "Latin America and the Caribbean" in alias_map.get(
        "undata-geo/G01100290", []
    )
    assert "Latin America" in alias_map.get("undata-geo/G00138200", [])
    assert "MENA" in alias_map.get("undata-geo/G00152000", [])
    assert "Western Europe" in alias_map.get("undata-geo/G00130000", [])
    assert "Northern Africa" in alias_map.get("undata-geo/G01100210", [])

    # No spurious aliases for South Asia (already has canonical name; not in YAML)
    assert "undata-geo/G00158000" not in alias_map


def test_build_region_aliases_contribution_skips_absent_entities(
    tmp_path: Path,
) -> None:
    """_build_region_aliases_contribution is safe on a DB missing some target entities."""
    import sqlite3

    from resolvekit.builder.pipeline.enrich import _build_region_aliases_contribution

    db_path = tmp_path / "entities.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE entities (
            entity_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            canonical_name_norm TEXT NOT NULL,
            valid_from TEXT,
            valid_until TEXT,
            attrs_json TEXT
        );
        INSERT INTO entities VALUES
            ('undata-geo/G00152000', 'geo.region', 'Middle East and North Africa', 'middle east and north africa', NULL, NULL, NULL);
    """)
    conn.close()

    contribution = _build_region_aliases_contribution(db_path)
    entity_ids = {row["entity_id"] for row in contribution.names}

    assert entity_ids == {"undata-geo/G00152000"}
    values = [row["value"] for row in contribution.names]
    assert "MENA" in values


def test_build_region_aliases_contribution_idempotent(tmp_path: Path) -> None:
    """Calling the enricher twice yields the same rows (INSERT OR IGNORE safe)."""
    import sqlite3

    from resolvekit.builder.pipeline.contribution import apply_contribution
    from resolvekit.builder.pipeline.enrich import _build_region_aliases_contribution
    from resolvekit.builder.sqlite.context import connect_sqlite, transaction

    db_path = tmp_path / "entities.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE entities (
            entity_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            canonical_name_norm TEXT NOT NULL,
            valid_from TEXT,
            valid_until TEXT,
            attrs_json TEXT
        );
        CREATE TABLE names (
            entity_id TEXT NOT NULL,
            name_kind TEXT NOT NULL,
            value TEXT NOT NULL,
            value_norm TEXT NOT NULL,
            lang TEXT NOT NULL DEFAULT '',
            script TEXT NOT NULL DEFAULT '',
            is_preferred INTEGER DEFAULT 0,
            PRIMARY KEY (entity_id, name_kind, value_norm, lang, script)
        );
        CREATE TABLE codes (entity_id TEXT, system TEXT, value TEXT, value_norm TEXT, PRIMARY KEY(entity_id, system));
        CREATE TABLE relations (entity_id TEXT, relation_type TEXT, target_id TEXT, valid_from TEXT, valid_until TEXT, PRIMARY KEY(entity_id, relation_type, target_id));
        INSERT INTO entities VALUES
            ('undata-geo/G00152000', 'geo.region', 'Middle East and North Africa', 'middle east and north africa', NULL, NULL, NULL);
    """)
    conn.close()

    contribution = _build_region_aliases_contribution(db_path)
    with connect_sqlite(db_path, busy_timeout_ms=30000) as conn, transaction(conn):
        deltas1 = apply_contribution(conn=conn, contribution=contribution)

    contribution2 = _build_region_aliases_contribution(db_path)
    with connect_sqlite(db_path, busy_timeout_ms=30000) as conn, transaction(conn):
        deltas2 = apply_contribution(conn=conn, contribution=contribution2)

    assert deltas1["names"] > 0, "first run should add rows"
    assert deltas2["names"] == 0, "second run should add zero rows (idempotent)"
