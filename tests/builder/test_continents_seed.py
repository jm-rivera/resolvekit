"""Tests for the geo.continents seed source and built datapack.

Covers:
- Seed data integrity (entity IDs, wikidata Q-IDs, expected aliases).
- Datapack resolution end-to-end for all 10 eval queries from the v4 eval set.
- Module catalog registration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from resolvekit.builder.module_catalog import module_entry
from resolvekit.builder.sources.seed.continents import CONTINENTS, ENTITY_TYPE

# ---------------------------------------------------------------------------
# Seed data unit tests
# ---------------------------------------------------------------------------


def test_eight_continent_entries() -> None:
    """Seed must contain exactly 8 entries (7 geographic + Americas/Q828)."""
    assert len(CONTINENTS) == 8


def test_continent_entity_ids_format() -> None:
    """All entity IDs must follow the wikidataId/<QID> pattern."""
    for entry in CONTINENTS:
        assert entry.entity_id.startswith("wikidataId/Q"), (
            f"{entry.entity_id!r} does not start with 'wikidataId/Q'"
        )


def test_wikidata_qids_match_entity_ids() -> None:
    """The bare wikidata_qid must be the Q-ID suffix of entity_id."""
    for entry in CONTINENTS:
        expected_suffix = entry.wikidata_qid
        assert entry.entity_id.endswith(f"/{expected_suffix}"), (
            f"entity_id={entry.entity_id!r} does not end with /{expected_suffix}"
        )


def test_expected_qids_present() -> None:
    """The seven geographic continents + Americas must all be present."""
    expected = {"Q15", "Q46", "Q48", "Q49", "Q18", "Q55643", "Q51", "Q828"}
    actual = {entry.wikidata_qid for entry in CONTINENTS}
    assert actual == expected


def test_entity_type_constant() -> None:
    """ENTITY_TYPE must be 'geo.continent'."""
    assert ENTITY_TYPE == "geo.continent"


def test_africa_has_dark_continent_alias() -> None:
    """Africa seed must include 'the Dark Continent' alias for the eval."""
    africa = next(e for e in CONTINENTS if e.wikidata_qid == "Q15")
    alias_values = {v for v, _, _ in africa.names}
    assert "the Dark Continent" in alias_values


def test_americas_aliases_exclude_bare_america() -> None:
    """Americas (Q828) carries 'Americas' but not the bare 'America'.

    'America' is an alias of the United States; seeding it on the Americas
    continent makes 'America' AMBIGUOUS in the full geo stack (country/USA vs
    Q828). The bare label is deliberately excluded.
    """
    americas = next(e for e in CONTINENTS if e.wikidata_qid == "Q828")
    alias_values = {v for v, _, _ in americas.names}
    assert "Americas" in alias_values or americas.canonical_name == "Americas"
    assert "America" not in alias_values


# ---------------------------------------------------------------------------
# Module catalog tests
# ---------------------------------------------------------------------------


def test_geo_continents_in_catalog() -> None:
    """geo.continents must be registered in the module catalog."""
    entry = module_entry("geo.continents")
    assert entry.module_id == "geo.continents"
    assert entry.domain == "geo"
    assert "geo.continent" in entry.include_entity_types


def test_geo_continents_in_geo_entries() -> None:
    """geo.continents must be included in the geo preset (include_in_geo=True)."""
    entry = module_entry("geo.continents")
    assert entry.include_in_geo


def test_geo_continents_is_bundled() -> None:
    """geo.continents is small — must be bundled, not remote."""
    from resolvekit.builder.module_catalog import DistributionStrategy

    entry = module_entry("geo.continents")
    assert entry.distribution is DistributionStrategy.BUNDLED


# ---------------------------------------------------------------------------
# End-to-end datapack resolution tests
# ---------------------------------------------------------------------------

_CONTINENTS_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "resolvekit"
    / "_data"
    / "geo"
    / "continents"
)


@pytest.fixture(scope="module")
def continents_resolver():
    """Load the built geo.continents datapack for resolution tests."""
    if not (_CONTINENTS_DIR / "entities.sqlite").exists():
        pytest.skip("geo.continents datapack not built yet")
    from resolvekit.core.api.resolver import Resolver

    r = Resolver.from_datapacks(datapack_paths=[_CONTINENTS_DIR])
    yield r
    r.close()


@pytest.mark.parametrize(
    "query,expected_id",
    [
        ("Africa", "wikidataId/Q15"),
        ("Europe", "wikidataId/Q46"),
        ("Asia", "wikidataId/Q48"),
        ("North America", "wikidataId/Q49"),
        ("South America", "wikidataId/Q18"),
        ("Oceania", "wikidataId/Q55643"),
        ("Antarctica", "wikidataId/Q51"),
        ("Americas", "wikidataId/Q828"),
        # Hard cases from v4 eval
        ("the Dark Continent", "wikidataId/Q15"),
        ("Antartica", "wikidataId/Q51"),  # typo — must fuzzy-resolve
    ],
)
def test_continent_resolution(
    continents_resolver,
    query: str,
    expected_id: str,
) -> None:
    """All 10 v4 eval continent queries must resolve to the expected wikidataId."""
    result = continents_resolver.resolve(query)
    assert result.entity_id == expected_id, (
        f"resolve({query!r}) -> {result.entity_id!r}, want {expected_id!r} "
        f"(status={result.status})"
    )


def test_continents_wikidata_codes(continents_resolver) -> None:
    """Every continent entity must carry a 'wikidata' code equal to its Q-ID."""
    expected_qids = {
        "wikidataId/Q15": "Q15",
        "wikidataId/Q46": "Q46",
        "wikidataId/Q48": "Q48",
        "wikidataId/Q49": "Q49",
        "wikidataId/Q18": "Q18",
        "wikidataId/Q55643": "Q55643",
        "wikidataId/Q51": "Q51",
        "wikidataId/Q828": "Q828",
    }
    for entity_id, expected_qid in expected_qids.items():
        result = continents_resolver.resolve(entity_id, include_entity=True)
        assert result.is_resolved, f"entity_id {entity_id!r} not found"
        entity = result.entity
        assert entity is not None
        wikidata_codes = [c.value for c in entity.codes if c.system == "wikidata"]
        assert wikidata_codes == [expected_qid], (
            f"{entity_id}: expected wikidata code {expected_qid!r}, got {wikidata_codes!r}"
        )
