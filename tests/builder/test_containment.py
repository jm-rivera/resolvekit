"""Unit tests for the containment enricher (builder/containment.py).

Mirrors test_groups_loader.py against a minimal staging DB.  Covers:
- Mints geo.subregion rows for sample sub-regions (incl. m49/419) with correct
  canonical_name / entity_type.
- Emits canonical names row (lang en, is_preferred 1) + m49 code row.
- Emits country→leaf and region→parent contained_in relations with correct
  target_ids.
- Enricher does NOT emit CONTINENT_REUSE_EDGES.
- Idempotent on re-run; unknown iso3 warns + skips.
- Collision guard: pre-seeded statistical region name does not collide with a
  minted M.49 canonical name.
- Completeness guard: every iso3 in M49_COUNTRY_ASSIGNMENTS maps to a valid
  leaf node; every M49Region.parent_id resolves to a valid node.
- Continents reuse edges: CONTINENT_REUSE_EDGES constant carries the expected
  (Q18→m49/419, Q49→Q828) pairs; build_continents_sqlite writes them.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest

from resolvekit.builder.containment import GEO_REGION_ENTITY_TYPE
from resolvekit.builder.sources.seed.m49 import (
    _VALID_LEAF_IDS,
    _VALID_PARENT_IDS,
    CONTINENT_REUSE_EDGES,
    M49_COUNTRY_ASSIGNMENTS,
    M49_REGIONS,
)

# ---------------------------------------------------------------------------
# Minimal staging-DB schema (matches test_groups_loader.py)
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

# A small set of countries covering several sub-regions.
_SEED_COUNTRIES: list[tuple[str, str, str]] = [
    ("country/KEN", "Kenya", "KEN"),  # Eastern Africa
    ("country/AGO", "Angola", "AGO"),  # Middle Africa
    ("country/USA", "United States", "USA"),  # Northern America (Q49)
    ("country/BRA", "Brazil", "BRA"),  # South America (Q18)
    ("country/MEX", "Mexico", "MEX"),  # Central America
    ("country/DEU", "Germany", "DEU"),  # Western Europe
    ("country/JPN", "Japan", "JPN"),  # Eastern Asia
    ("country/AUS", "Australia", "AUS"),  # Australia and New Zealand
]


def _build_staging_db(tmp_path: Path) -> Path:
    """Create a minimal staging DB with a handful of country entities + iso3 codes."""
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


def _run_enricher(db_path: Path) -> None:
    """Run build_containment_contribution and apply the result."""
    from resolvekit.builder.containment import build_containment_contribution
    from resolvekit.builder.pipeline.contribution import apply_contribution
    from resolvekit.builder.sqlite.context import connect_sqlite, transaction

    contribution = build_containment_contribution(db_path)
    with connect_sqlite(db_path, busy_timeout_ms=30000) as conn, transaction(conn):
        apply_contribution(conn=conn, contribution=contribution)


# ---------------------------------------------------------------------------
# Entity minting tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_mints_geo_region_entities(tmp_path: Path) -> None:
    """All 22 M49Region entries appear as geo.subregion rows after enrichment."""
    db_path = _build_staging_db(tmp_path)
    _run_enricher(db_path)

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT entity_id, entity_type FROM entities WHERE entity_type = ?",
        (GEO_REGION_ENTITY_TYPE,),
    ).fetchall()
    conn.close()

    minted_ids = {r[0] for r in rows}
    for region in M49_REGIONS:
        assert region.entity_id in minted_ids, (
            f"Expected {region.entity_id!r} to be minted as {GEO_REGION_ENTITY_TYPE}"
        )
    assert len(M49_REGIONS) == 22, "Sanity: seed must contain exactly 22 regions"


@pytest.mark.unit
def test_mints_lac_region(tmp_path: Path) -> None:
    """m49/419 (Latin America & the Caribbean) is minted — it does NOT pre-exist."""
    db_path = _build_staging_db(tmp_path)
    _run_enricher(db_path)

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT entity_type, canonical_name FROM entities WHERE entity_id = 'm49/419'"
    ).fetchone()
    conn.close()

    assert row is not None, "m49/419 must be minted"
    assert row[0] == GEO_REGION_ENTITY_TYPE
    assert "Latin America" in row[1]


@pytest.mark.unit
def test_canonical_name_and_type(tmp_path: Path) -> None:
    """Spot-check canonical_name and entity_type for a few sample regions."""
    db_path = _build_staging_db(tmp_path)
    _run_enricher(db_path)

    checks = {
        "m49/014": "Eastern Africa",
        "m49/202": "Sub-Saharan Africa",
        "m49/155": "Western Europe",
        "m49/030": "Eastern Asia",
    }
    conn = sqlite3.connect(db_path)
    for entity_id, expected_name in checks.items():
        row = conn.execute(
            "SELECT entity_type, canonical_name FROM entities WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()
        assert row is not None, f"{entity_id!r} not minted"
        assert row[0] == GEO_REGION_ENTITY_TYPE, (
            f"{entity_id}: wrong entity_type {row[0]!r}"
        )
        assert row[1] == expected_name, (
            f"{entity_id}: canonical_name {row[1]!r} != {expected_name!r}"
        )
    conn.close()


# ---------------------------------------------------------------------------
# Names and codes rows
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_canonical_names_row(tmp_path: Path) -> None:
    """Each minted region has a canonical names row (lang=en, is_preferred=1)."""
    db_path = _build_staging_db(tmp_path)
    _run_enricher(db_path)

    conn = sqlite3.connect(db_path)
    for region in M49_REGIONS:
        row = conn.execute(
            """
            SELECT value, lang, is_preferred FROM names
            WHERE entity_id = ? AND name_kind = 'canonical' AND lang = 'en'
            """,
            (region.entity_id,),
        ).fetchone()
        assert row is not None, f"{region.entity_id!r}: missing canonical en names row"
        assert row[0] == region.canonical_name
        assert row[1] == "en"
        assert row[2] == 1
    conn.close()


@pytest.mark.unit
def test_m49_code_row(tmp_path: Path) -> None:
    """Each minted region has an m49 code row with the correct value."""
    db_path = _build_staging_db(tmp_path)
    _run_enricher(db_path)

    conn = sqlite3.connect(db_path)
    for region in M49_REGIONS:
        row = conn.execute(
            "SELECT value FROM codes WHERE entity_id = ? AND system = 'm49'",
            (region.entity_id,),
        ).fetchone()
        assert row is not None, f"{region.entity_id!r}: missing m49 code row"
        assert row[0] == region.code, (
            f"{region.entity_id!r}: code {row[0]!r} != {region.code!r}"
        )
    conn.close()


@pytest.mark.unit
def test_alias_names_rows(tmp_path: Path) -> None:
    """Regions with declared aliases emit alias names rows."""
    db_path = _build_staging_db(tmp_path)
    _run_enricher(db_path)

    # m49/419 (LAC) has aliases including "Latin America"
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT value FROM names WHERE entity_id = 'm49/419' AND name_kind = 'alias'",
    ).fetchall()
    conn.close()

    alias_values = {r[0] for r in rows}
    assert "LAC" in alias_values
    assert "Latin America" in alias_values


# ---------------------------------------------------------------------------
# Relations: contained_in edges
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_region_parent_contained_in(tmp_path: Path) -> None:
    """Region→parent contained_in edges are emitted with correct target_ids."""
    db_path = _build_staging_db(tmp_path)
    _run_enricher(db_path)

    conn = sqlite3.connect(db_path)
    checks = {
        "m49/014": "m49/202",  # Eastern Africa → Sub-Saharan Africa
        "m49/202": "wikidataId/Q15",  # Sub-Saharan Africa → Africa
        "m49/419": "wikidataId/Q828",  # LAC → Americas
        "m49/029": "m49/419",  # Caribbean → LAC
        "m49/155": "wikidataId/Q46",  # Western Europe → Europe
        "m49/053": "wikidataId/Q55643",  # Australia & NZ → Oceania
    }
    for source_id, expected_target in checks.items():
        row = conn.execute(
            """
            SELECT target_id FROM relations
            WHERE entity_id = ? AND relation_type = 'contained_in'
            """,
            (source_id,),
        ).fetchone()
        assert row is not None, f"No contained_in edge for {source_id!r}"
        assert row[0] == expected_target, (
            f"{source_id!r} → {row[0]!r}, expected {expected_target!r}"
        )
    conn.close()


@pytest.mark.unit
def test_country_leaf_contained_in(tmp_path: Path) -> None:
    """Country→leaf contained_in edges are emitted for seeded iso3 codes."""
    db_path = _build_staging_db(tmp_path)
    _run_enricher(db_path)

    conn = sqlite3.connect(db_path)
    checks = {
        "country/KEN": "m49/014",  # Kenya → Eastern Africa
        "country/AGO": "m49/017",  # Angola → Middle Africa
        "country/USA": "wikidataId/Q49",  # USA → Northern America
        "country/BRA": "wikidataId/Q18",  # Brazil → South America
        "country/MEX": "m49/013",  # Mexico → Central America
        "country/DEU": "m49/155",  # Germany → Western Europe
        "country/JPN": "m49/030",  # Japan → Eastern Asia
        "country/AUS": "m49/053",  # Australia → Aus+NZ
    }
    for country_eid, expected_leaf in checks.items():
        row = conn.execute(
            """
            SELECT target_id FROM relations
            WHERE entity_id = ? AND relation_type = 'contained_in'
            """,
            (country_eid,),
        ).fetchone()
        assert row is not None, f"No contained_in edge from {country_eid!r}"
        assert row[0] == expected_leaf, (
            f"{country_eid!r} → {row[0]!r}, expected {expected_leaf!r}"
        )
    conn.close()


@pytest.mark.unit
def test_enricher_does_not_emit_continent_reuse_edges(tmp_path: Path) -> None:
    """The enricher does NOT write the two continent-sourced reuse edges.

    Those edges (Q18→m49/419, Q49→Q828) are owned by geo.continents and must
    be written by build_continents.py, not by this enricher.
    """
    db_path = _build_staging_db(tmp_path)
    _run_enricher(db_path)

    conn = sqlite3.connect(db_path)
    for source_id, target_id in CONTINENT_REUSE_EDGES:
        row = conn.execute(
            """
            SELECT 1 FROM relations
            WHERE entity_id = ? AND relation_type = 'contained_in' AND target_id = ?
            """,
            (source_id, target_id),
        ).fetchone()
        assert row is None, (
            f"Enricher must NOT emit continent-sourced edge {source_id!r}→{target_id!r}"
        )
    conn.close()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_idempotent_on_rerun(tmp_path: Path) -> None:
    """Running the enricher twice produces the same row counts."""
    db_path = _build_staging_db(tmp_path)
    _run_enricher(db_path)

    conn = sqlite3.connect(db_path)
    after_first = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("entities", "names", "codes", "relations")
    }
    conn.close()

    _run_enricher(db_path)

    conn = sqlite3.connect(db_path)
    after_second = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("entities", "names", "codes", "relations")
    }
    conn.close()

    assert after_first == after_second, (
        f"Enricher is not idempotent: first={after_first}, second={after_second}"
    )


# ---------------------------------------------------------------------------
# Unknown iso3 warning + skip
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_unknown_iso3_warns_and_skips(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An iso3 not in the DB emits a warning; the enricher still runs for others."""
    db_path = _build_staging_db(tmp_path)

    # The full M49_COUNTRY_ASSIGNMENTS contains hundreds of iso3 codes; the
    # staging DB only seeds 8 countries.  The enricher must warn about the
    # unknowns and still produce relations for the 8 seeded ones.
    with caplog.at_level(logging.WARNING):
        _run_enricher(db_path)

    # At least one warning about skipped iso3 codes.
    assert any(
        "iso3" in msg.lower() or "skipped" in msg.lower() for msg in caplog.messages
    ), "Expected a warning about unknown iso3 codes"

    # The 8 seeded countries must still have their relations.
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT entity_id FROM relations WHERE relation_type = 'contained_in'"
        " AND entity_id LIKE 'country/%'"
    ).fetchall()
    conn.close()
    seeded_countries_with_edges = {r[0] for r in rows}
    assert len(seeded_countries_with_edges) >= 8, (
        "All 8 seeded countries should have contained_in edges"
    )


# ---------------------------------------------------------------------------
# Collision guard
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_collision_guard_distinct_from_statistical_region(tmp_path: Path) -> None:
    """Minted M.49 canonical names do not exactly match a pre-seeded statistical region.

    The existing geo.regions pack contains names like "Eastern Africa, regional"
    and "Sub-Saharan Africa (incl. Sudan)".  The minted M.49 names are clean
    short-form ("Eastern Africa", "Sub-Saharan Africa") — they differ and thus
    do not cause ambiguity with pre-existing statistical entities.
    """
    db_path = _build_staging_db(tmp_path)

    # Seed a statistical region with a name that would collide IF we weren't
    # careful about canonical-name distinctness.
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO entities VALUES"
        " ('undata-geo/G001014', 'geo.region', 'Eastern Africa, regional',"
        "  'eastern africa regional', NULL, NULL, NULL)"
    )
    conn.commit()
    conn.close()

    _run_enricher(db_path)

    conn = sqlite3.connect(db_path)
    # The minted entity must have a different entity_id and canonical name.
    row_minted = conn.execute(
        "SELECT canonical_name FROM entities WHERE entity_id = 'm49/014'"
    ).fetchone()
    row_stat = conn.execute(
        "SELECT canonical_name FROM entities WHERE entity_id = 'undata-geo/G001014'"
    ).fetchone()
    conn.close()

    assert row_minted is not None
    assert row_stat is not None
    assert row_minted[0] != row_stat[0], (
        "Minted canonical name must not exactly equal the pre-seeded statistical name"
    )
    assert row_minted[0] == "Eastern Africa"
    assert row_stat[0] == "Eastern Africa, regional"


# ---------------------------------------------------------------------------
# Completeness guard (pure seed constants — no DB needed)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_completeness_all_assignments_map_to_valid_leaf() -> None:
    """Every iso3 in M49_COUNTRY_ASSIGNMENTS maps to a node in M49_REGIONS or a
    known reused continent Q-id."""
    invalid: list[str] = []
    for iso3, leaf_id in M49_COUNTRY_ASSIGNMENTS.items():
        if leaf_id not in _VALID_LEAF_IDS:
            invalid.append(f"{iso3!r}→{leaf_id!r}")
    assert not invalid, (
        f"M49_COUNTRY_ASSIGNMENTS entries map to unknown leaf ids: {invalid}"
    )


@pytest.mark.unit
def test_completeness_all_region_parents_valid() -> None:
    """Every M49Region.parent_id resolves to another M49Region or a continent Q-id."""
    invalid: list[str] = []
    for region in M49_REGIONS:
        if region.parent_id not in _VALID_PARENT_IDS:
            invalid.append(f"{region.entity_id!r}.parent_id={region.parent_id!r}")
    assert not invalid, f"M49Region entries have invalid parent_ids: {invalid}"


@pytest.mark.unit
def test_completeness_22_minted_regions() -> None:
    """M49_REGIONS contains exactly 22 entries."""
    assert len(M49_REGIONS) == 22, f"Expected 22 minted regions, got {len(M49_REGIONS)}"


# ---------------------------------------------------------------------------
# Continent reuse-edge constant + build_continents_sqlite integration
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_continent_reuse_edges_constant() -> None:
    """CONTINENT_REUSE_EDGES holds exactly the two expected (source, target) pairs."""
    expected = {
        ("wikidataId/Q18", "m49/419"),
        ("wikidataId/Q49", "wikidataId/Q828"),
    }
    actual = set(CONTINENT_REUSE_EDGES)
    assert actual == expected, (
        f"CONTINENT_REUSE_EDGES mismatch: {actual!r} != {expected!r}"
    )


@pytest.mark.unit
def test_build_continents_writes_reuse_edges(tmp_path: Path) -> None:
    """build_continents_sqlite writes the two continent-sourced reuse edges."""
    from resolvekit.builder.sqlite import ensure_sqlite_schema
    from resolvekit.builder.sqlite.context import connect_sqlite
    from resolvekit.core.util.normalization import TextNormalizer
    from scripts.build.build_continents import build_continents_sqlite

    db_path = tmp_path / "continents.sqlite"
    ensure_sqlite_schema(db_path)

    build_continents_sqlite(db_path, TextNormalizer())

    with connect_sqlite(db_path) as conn:
        rows = conn.execute(
            "SELECT entity_id, target_id FROM relations"
            " WHERE relation_type = 'contained_in'"
        ).fetchall()

    edge_set = {(r[0], r[1]) for r in rows}
    for source_id, target_id in CONTINENT_REUSE_EDGES:
        assert (source_id, target_id) in edge_set, (
            f"Expected continent reuse edge {source_id!r}→{target_id!r} in continents pack"
        )


# ---------------------------------------------------------------------------
# Region noise-filter pin (R3 guard)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_m49_names_survive_noise_filter() -> None:
    """Clean m49/* canonical names do not match any noise-filter pattern.

    The region filter deletes entities matching ``undata-geo/G009%``,
    ``%[former]%``, ``%not elsewhere specified%``, or ``%: All cities…%``.
    None of the M49Region canonical names trigger these patterns.
    """
    noise_patterns = (
        "[former]",
        "not elsewhere specified",
        ": All cities",
    )
    for region in M49_REGIONS:
        for pattern in noise_patterns:
            assert pattern.lower() not in region.canonical_name.lower(), (
                f"{region.entity_id!r} canonical name {region.canonical_name!r} "
                f"matches noise pattern {pattern!r}"
            )
        # entity_id prefix check: must not start with undata-geo/G009
        assert not region.entity_id.startswith("undata-geo/G009"), (
            f"{region.entity_id!r} matches noise id pattern"
        )
