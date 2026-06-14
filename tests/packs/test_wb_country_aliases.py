"""Regression tests for WB short-name + Kingdom-of-the-Netherlands aliases,
Taiwan two-part fix, EU-Institutions suppression, World seed, and DAC / Euro
aggregate aliases.

Two test groups:

1. ENRICHER-LEVEL. These tests call builder functions on a minimal tmp SQLite
   and assert the produced rows or deletion sets — no geo pack required.

2. PACK-LEVEL. These resolve against the bundled geo packs and assert the
   curated aliases, the Taiwan/EU-Institutions/World fixes, and the DAC / Non-DAC
   aggregates land as expected.

Note on ``_load_formal_overrides`` cache: the function is ``@cache``'d.  In a
fresh subprocess the cache is empty and the real on-disk YAML is read.  If you
call ``_load_formal_overrides`` multiple times in the same process you will get
the cached result — call ``_load_formal_overrides.cache_clear()`` between tests
if you need to reload the YAML (not needed here since we read the real file).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# resolvekit.builder pulls gecko-syndata (calibration extra), whose lxml<6 pin
# has no Python 3.14 wheel; skip the builder-contribution tests when it's absent.
_requires_gecko = pytest.mark.skipif(
    importlib.util.find_spec("gecko") is None,
    reason="requires the calibration extra (gecko-syndata)",
)

_GEO_DATA = Path(__file__).parent.parent.parent / "src" / "resolvekit" / "_data" / "geo"
COUNTRIES_PACK_PATH = _GEO_DATA / "countries"
REGIONS_PACK_PATH = _GEO_DATA / "regions"
CONTINENTS_PACK_PATH = _GEO_DATA / "continents"
CONTINENTAL_UNIONS_PACK_PATH = _GEO_DATA / "continental_unions"

# ---------------------------------------------------------------------------
# Shared SQLite schema for enricher-level tests
# ---------------------------------------------------------------------------

_ENTITIES_DDL = """
    CREATE TABLE entities (
        entity_id TEXT PRIMARY KEY,
        entity_type TEXT NOT NULL,
        canonical_name TEXT NOT NULL,
        canonical_name_norm TEXT NOT NULL,
        valid_from TEXT,
        valid_until TEXT,
        attrs_json TEXT
    );
"""


def _seed_countries(conn, iso3_list: list[str]) -> None:
    """Insert minimal country rows for ``build_formal_name_contribution``."""
    rows = [
        (
            f"country/{iso3}",
            "geo.country",
            iso3,  # canonical_name placeholder
            iso3.lower(),
            None,
            None,
            None,
        )
        for iso3 in iso3_list
    ]
    conn.executemany(
        "INSERT INTO entities VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


# ---------------------------------------------------------------------------
# ENRICHER-LEVEL: formal-name contribution (D1 + D3 aliases)
# ---------------------------------------------------------------------------


@_requires_gecko
def test_formal_name_contribution_wb_country_aliases(tmp_path: Path) -> None:
    """``build_formal_name_contribution`` emits the new WB comma-style aliases.

    Covers: COG, KOR, IRN, YEM, FSM, ABW, CUW, SXM, TWN.
    """
    import sqlite3

    from resolvekit.builder.formal_names import build_formal_name_contribution

    db_path = tmp_path / "entities.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(_ENTITIES_DDL)
    _seed_countries(
        conn,
        ["COG", "KOR", "IRN", "YEM", "FSM", "ABW", "CUW", "SXM", "TWN"],
    )
    conn.commit()
    conn.close()

    contribution = build_formal_name_contribution(db_path)

    alias_map: dict[str, list[str]] = {}
    for row in contribution.names:
        alias_map.setdefault(row["entity_id"], []).append(row["value"])

    # D1: COG — Congo, Rep. / Congo, Republic of / Congo, Republic of the
    cog_names = alias_map.get("country/COG", [])
    assert "Congo, Rep." in cog_names, f"country/COG names: {cog_names}"
    assert "Congo, Republic of" in cog_names, f"country/COG names: {cog_names}"
    assert "Congo, Republic of the" in cog_names, f"country/COG names: {cog_names}"

    # D1: KOR — Korea, South
    kor_names = alias_map.get("country/KOR", [])
    assert "Korea, South" in kor_names, f"country/KOR names: {kor_names}"

    # D1: IRN — Iran, Islamic Rep.
    irn_names = alias_map.get("country/IRN", [])
    assert "Iran, Islamic Rep." in irn_names, f"country/IRN names: {irn_names}"

    # D1: YEM — Yemen, Rep.
    yem_names = alias_map.get("country/YEM", [])
    assert "Yemen, Rep." in yem_names, f"country/YEM names: {yem_names}"

    # D1: FSM — Micronesia, Fed. Sts. / Micronesia, Federated States of
    fsm_names = alias_map.get("country/FSM", [])
    assert "Micronesia, Fed. Sts." in fsm_names, f"country/FSM names: {fsm_names}"
    assert "Micronesia, Federated States of" in fsm_names, (
        f"country/FSM names: {fsm_names}"
    )

    # D1: ABW — Aruba, Kingdom of the Netherlands
    abw_names = alias_map.get("country/ABW", [])
    assert "Aruba, Kingdom of the Netherlands" in abw_names, (
        f"country/ABW names: {abw_names}"
    )

    # D1: CUW — Curaçao, Kingdom of the Netherlands
    cuw_names = alias_map.get("country/CUW", [])
    assert "Curaçao, Kingdom of the Netherlands" in cuw_names, (
        f"country/CUW names: {cuw_names}"
    )

    # D1: SXM — Sint Maarten (Dutch part), Kingdom of the Netherlands
    sxm_names = alias_map.get("country/SXM", [])
    assert "Sint Maarten (Dutch part), Kingdom of the Netherlands" in sxm_names, (
        f"country/SXM names: {sxm_names}"
    )

    # D3: TWN — Taiwan Province of China
    twn_names = alias_map.get("country/TWN", [])
    assert "Taiwan Province of China" in twn_names, f"country/TWN names: {twn_names}"


# ---------------------------------------------------------------------------
# ENRICHER-LEVEL: region-filter contribution deletes G00003070 (D3)
# ---------------------------------------------------------------------------


@_requires_gecko
def test_region_filter_contribution_deletes_g00003070(tmp_path: Path) -> None:
    """``_build_region_filter_contribution`` marks ``undata-geo/G00003070`` for deletion.

    G00003070 ("Taiwan province of China") owned the exact_name claim on the
    UN long-form label and pre-empted country/TWN.  The fix adds an explicit-id
    clause (``_REGION_NOISE_EXPLICIT_IDS``) independent of the entity_type filter
    so it is deleted even if its type changes in a future data rebuild.
    """
    import sqlite3

    from resolvekit.builder.pipeline.enrich import _build_region_filter_contribution

    db_path = tmp_path / "entities.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(f"""
        {_ENTITIES_DDL}
        INSERT INTO entities VALUES
            ('undata-geo/G00003070', 'geo.region',
             'Taiwan province of China', 'taiwan province of china',
             NULL, NULL, NULL);
    """)
    conn.close()

    contribution = _build_region_filter_contribution(db_path)

    assert "undata-geo/G00003070" in contribution.entity_ids_to_delete, (
        f"Expected 'undata-geo/G00003070' in entity_ids_to_delete, "
        f"got: {contribution.entity_ids_to_delete}"
    )


# ---------------------------------------------------------------------------
# PACK-LEVEL: country aliases (D1 + D3) — post-rebuild
# ---------------------------------------------------------------------------

_COUNTRY_ALIAS_CASES = [
    # (query_string, expected_entity_id)
    ("Congo, Rep.", "country/COG"),
    ("Congo, Republic of", "country/COG"),
    ("Congo, Republic of the", "country/COG"),
    ("Korea, South", "country/KOR"),
    ("Iran, Islamic Rep.", "country/IRN"),
    ("Yemen, Rep.", "country/YEM"),
    ("Micronesia, Fed. Sts.", "country/FSM"),
    ("Micronesia, Federated States of", "country/FSM"),
    ("Aruba, Kingdom of the Netherlands", "country/ABW"),
    ("Curaçao, Kingdom of the Netherlands", "country/CUW"),
    ("Sint Maarten (Dutch part), Kingdom of the Netherlands", "country/SXM"),
    # D3: Taiwan exact-name — single candidate after G00003070 deletion
    ("Taiwan Province of China", "country/TWN"),
]


@pytest.fixture(scope="module")
def countries_resolver():
    """Resolver backed solely by the bundled geo.countries pack."""
    from resolvekit.core.api.resolver import Resolver

    resolver = Resolver.from_datapacks(datapack_paths=[COUNTRIES_PACK_PATH])
    yield resolver
    resolver.close()


@pytest.fixture(scope="module")
def lite_resolver():
    """Resolver backed by the full Resolver.lite() pack set (countries + regions +
    continents + continental_unions), needed for aggregate and World cases."""
    from resolvekit.core.api.resolver import Resolver

    resolver = Resolver.from_datapacks(
        datapack_paths=[
            COUNTRIES_PACK_PATH,
            REGIONS_PACK_PATH,
            CONTINENTS_PACK_PATH,
            CONTINENTAL_UNIONS_PACK_PATH,
        ]
    )
    yield resolver
    resolver.close()


@pytest.mark.parametrize(
    "text,expected_id",
    _COUNTRY_ALIAS_CASES,
    ids=[c[0] for c in _COUNTRY_ALIAS_CASES],
)
def test_country_alias_resolves_to_expected_entity(
    countries_resolver, text: str, expected_id: str
) -> None:
    """Each WB alias resolves to the expected country/XXX entity at EXACT_NAME tier."""
    from resolvekit.core.model import MatchTier

    result = countries_resolver.resolve(text)
    assert result.is_resolved, (
        f"{text!r}: expected RESOLVED to {expected_id}, "
        f"got status={result.status} "
        f"candidates={[c.entity_id for c in result.candidates[:3]]}"
    )
    assert result.entity_id == expected_id, (
        f"{text!r}: resolved to {result.entity_id!r}, expected {expected_id!r}"
    )
    assert result.match_tier == MatchTier.EXACT_NAME, (
        f"{text!r}: expected EXACT_NAME tier, got {result.match_tier!r}"
    )


# ---------------------------------------------------------------------------
# PACK-LEVEL: Taiwan single-candidate check (D3) — post-rebuild
# ---------------------------------------------------------------------------


def test_taiwan_province_of_china_single_candidate(countries_resolver) -> None:
    """``Taiwan Province of China`` resolves to country/TWN with a single candidate.

    After G00003070 is deleted, no competing entity claims the UN long-form
    label — so the single-candidate early-accept fires at EXACT_NAME tier.
    """
    from resolvekit.core.model import MatchTier

    result = countries_resolver.resolve("Taiwan Province of China")
    assert result.is_resolved, (
        f"Expected RESOLVED, got status={result.status} "
        f"candidates={[c.entity_id for c in result.candidates[:3]]}"
    )
    assert result.entity_id == "country/TWN"
    assert result.match_tier == MatchTier.EXACT_NAME
    assert len(result.candidates) == 1, (
        f"Expected single candidate, got {len(result.candidates)}: "
        f"{[c.entity_id for c in result.candidates]}"
    )


# ---------------------------------------------------------------------------
# PACK-LEVEL: EU Institutions / European Union (D5) — post-rebuild
# ---------------------------------------------------------------------------


def test_eu_institutions_resolves_to_dac_entity(lite_resolver) -> None:
    """``EU Institutions`` resolves to DAC/EUInstitutions at EXACT_NAME tier.

    The oecd_dac.py fix suppresses the EU-Institutions alias injection onto
    EuropeanUnion.  After rebuild DAC/EUInstitutions is the sole exact-name
    match — verified at tier level to catch an FTS masking an incomplete fix.
    """
    from resolvekit.core.model import MatchTier

    result = lite_resolver.resolve("EU Institutions")
    assert result.is_resolved, (
        f"Expected RESOLVED, got status={result.status} "
        f"candidates={[c.entity_id for c in result.candidates[:3]]}"
    )
    assert result.entity_id == "DAC/EUInstitutions", (
        f"Expected DAC/EUInstitutions, got {result.entity_id!r}"
    )
    assert result.match_tier == MatchTier.EXACT_NAME, (
        f"Expected EXACT_NAME, got {result.match_tier!r} "
        "(FTS could mask an incomplete fix — tier assertion is load-bearing)"
    )


def test_european_union_resolves_unchanged(lite_resolver) -> None:
    """``European Union`` still resolves to EuropeanUnion (suppressing EU Institutions
    alias does not affect the canonical name resolution of the geo entity)."""
    result = lite_resolver.resolve("European Union")
    assert result.is_resolved, f"Expected RESOLVED, got status={result.status}"
    assert result.entity_id == "EuropeanUnion"


# ---------------------------------------------------------------------------
# PACK-LEVEL: World entity (D6) — post-rebuild
# ---------------------------------------------------------------------------


def test_world_resolves_to_m49_001(lite_resolver) -> None:
    """``World`` resolves to m49/001 after the World seed entry lands."""
    result = lite_resolver.resolve("World")
    assert result.is_resolved, (
        f"Expected RESOLVED, got status={result.status} "
        f"candidates={[c.entity_id for c in result.candidates[:3]]}"
    )
    assert result.entity_id == "m49/001", f"Expected m49/001, got {result.entity_id!r}"


# ---------------------------------------------------------------------------
# PACK-LEVEL: DAC aggregate aliases (D2) — post-rebuild
# ---------------------------------------------------------------------------


def test_dac_countries_resolves(lite_resolver) -> None:
    """``DAC countries`` still resolves to DAC/DacCountries (bilateral, no EUI)."""
    result = lite_resolver.resolve("DAC countries")
    assert result.is_resolved
    assert result.entity_id == "DAC/DacCountries"


@pytest.mark.parametrize(
    "text",
    ["Total DAC", "DAC Countries, Total"],
    ids=["Total DAC", "DAC Countries, Total"],
)
def test_total_dac_aliases_resolve_to_dac_members(lite_resolver, text: str) -> None:
    """``Total DAC`` / ``DAC Countries, Total`` resolve to DAC/DacMembers (incl. EUI)."""
    result = lite_resolver.resolve(text)
    assert result.is_resolved, (
        f"{text!r}: expected RESOLVED, got status={result.status}"
    )
    assert result.entity_id == "DAC/DacMembers", (
        f"{text!r}: resolved to {result.entity_id!r}, expected DAC/DacMembers"
    )


def test_euro_area_ea_resolves_to_eurozone(lite_resolver) -> None:
    """``Euro Area (EA)`` resolves to groups/Eurozone."""
    result = lite_resolver.resolve("Euro Area (EA)")
    assert result.is_resolved, f"Expected RESOLVED, got status={result.status}"
    assert result.entity_id == "groups/Eurozone"


# ---------------------------------------------------------------------------
# PACK-LEVEL: Non-DAC group (D4) — post-rebuild
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["Non-DAC countries", "Non-DAC"],
    ids=["Non-DAC countries", "Non-DAC"],
)
def test_nondac_aliases_resolve_to_oecd_nondac(lite_resolver, text: str) -> None:
    """``Non-DAC countries`` / ``Non-DAC`` resolve to groups/OECD.NonDAC."""
    result = lite_resolver.resolve(text)
    assert result.is_resolved, (
        f"{text!r}: expected RESOLVED, got status={result.status}"
    )
    assert result.entity_id == "groups/OECD.NonDAC", (
        f"{text!r}: resolved to {result.entity_id!r}, expected groups/OECD.NonDAC"
    )


def test_nondac_group_has_22_members(lite_resolver) -> None:
    """groups/OECD.NonDAC has exactly 22 members after rebuild.

    Group membership rides ``member_of`` edges, so it is queried via
    ``members_of`` — ``within`` walks geographic ``contained_in`` edges only and
    never surfaces group members.
    """
    members = lite_resolver.members_of("Non-DAC countries")
    assert len(members) == 22, (
        f"Expected 22 Non-DAC members, got {len(members)}: {sorted(members)}"
    )
