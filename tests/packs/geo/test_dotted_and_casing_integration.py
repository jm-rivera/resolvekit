"""Integration regression tests for dotted-abbreviation and mixed-case resolution.

Finding #1: 'U.S.A.' resolved to politicalParty/SocialistPartyUSA (geo
suppressed by the punctuation-noise gate); 'U.K.' returned None.

Finding #11: 'fRaNcE' / 'CHIna' went ambiguous and 'SUDan' returned None
because the AutoRouter dropped the geo pack for 50-74%-uppercase names.

These exercise the full Resolver so the gate, routing, and scoring fixes are
validated together. Acronym-admin suppression (NASA -> "Nasa") must still hold.
"""

from __future__ import annotations

import pytest

from resolvekit import Resolver


@pytest.fixture(scope="module")
def resolver() -> Resolver:
    return Resolver.auto()


# Finding #1: dotted abbreviations resolve to the correct geo entity.
@pytest.mark.parametrize(
    "query,expected",
    [
        ("U.S.A.", "country/USA"),
        ("U.S.A", "country/USA"),
        ("U.K.", "country/GBR"),
    ],
)
def test_dotted_abbreviation_resolves_to_country(resolver, query, expected):
    result = resolver.resolve(query)
    assert result.status.value == "resolved", f"{query!r} -> {result.status.value}"
    assert result.candidates[0].entity_id == expected


def test_dotted_dc_resolves_to_geo_not_org(resolver):
    """'D.C.' must resolve to a geo entity, never an org pack entity."""
    result = resolver.resolve("D.C.")
    assert result.candidates, "D.C. produced no candidates"
    top = result.candidates[0].entity_id
    assert not top.startswith(("org/", "politicalParty/")), top
    assert top == "geoId/11001"


# Finding #1: the null-marker gate must remain intact.
@pytest.mark.parametrize("query", ["#N/A", "N/A", "--", "?", "N.A.", "NA", "NULL"])
def test_null_markers_still_blocked(resolver, query):
    result = resolver.resolve(query)
    assert result.status.value != "resolved", (
        f"{query!r} resolved to "
        f"{result.candidates[0].entity_id if result.candidates else None}"
    )


# Finding #11: mixed-case country names resolve like their standard casings.
@pytest.mark.parametrize(
    "query,expected",
    [
        ("fRaNcE", "country/FRA"),
        ("CHIna", "country/CHN"),
        ("SUDan", "country/SDN"),
        ("France", "country/FRA"),
        ("FRANCE", "country/FRA"),
        ("france", "country/FRA"),
    ],
)
def test_mixed_case_name_resolves(resolver, query, expected):
    result = resolver.resolve(query)
    assert result.status.value == "resolved", f"{query!r} -> {result.status.value}"
    assert result.candidates[0].entity_id == expected


# Acronym-admin suppression must survive the dotted-form carve-out: a bare
# uppercase acronym must not leak a same-spelled admin/city geo entity.
@pytest.mark.parametrize("query", ["NASA", "SWIFT", "EMEA"])
def test_bare_acronym_does_not_leak_geo_admin(resolver, query):
    result = resolver.resolve(query)
    top = result.candidates[0].entity_id if result.candidates else None
    if top is not None and top.startswith(("geoId/", "nuts/", "wikidataId/")):
        # geo candidate must not be an accepted resolution at admin/city tier
        assert result.status.value != "resolved", f"{query!r} leaked geo {top}"
