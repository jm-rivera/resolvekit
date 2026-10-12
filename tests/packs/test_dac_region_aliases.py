"""Regression coverage for qualified OECD DAC region aliases."""

from __future__ import annotations

import pytest

_CARIBBEAN_AND_CENTRAL_AMERICA = {
    "ABW",
    "AIA",
    "ATG",
    "BHS",
    "BLZ",
    "BMU",
    "BRB",
    "CRI",
    "CUB",
    "CYM",
    "DMA",
    "DOM",
    "GRD",
    "GTM",
    "HND",
    "HTI",
    "JAM",
    "KNA",
    "LCA",
    "MEX",
    "MSR",
    "NIC",
    "PAN",
    "SLV",
    "SXM",
    "TCA",
    "TTO",
    "VCT",
    "VGB",
}

_SOUTH_AND_CENTRAL_ASIA = {
    "AFG",
    "ARM",
    "AZE",
    "BGD",
    "BTN",
    "GEO",
    "IND",
    "KAZ",
    "KGZ",
    "LKA",
    "MDV",
    "MMR",
    "NPL",
    "PAK",
    "TJK",
    "TKM",
    "UZB",
}


@pytest.fixture(scope="module")
def dac_regions_resolver():
    """Resolver with the packs needed for DAC membership lookups."""
    from resolvekit import Resolver

    resolver = Resolver.from_modules(
        module_ids=["geo.countries", "geo.regions", "geo.continental_unions"]
    )
    yield resolver
    resolver.close()


_QUALIFIED_DAC_REGION_ALIASES = [
    (
        "Caribbean and Central America (DAC)",
        "groups/OECD.DAC.Region.CaribbeanAndCentralAmerica",
        _CARIBBEAN_AND_CENTRAL_AMERICA,
    ),
    (
        "Caribbean & Central America (DAC)",
        "groups/OECD.DAC.Region.CaribbeanAndCentralAmerica",
        _CARIBBEAN_AND_CENTRAL_AMERICA,
    ),
    (
        "Caribbean & Central America, Total",
        "groups/OECD.DAC.Region.CaribbeanAndCentralAmerica",
        _CARIBBEAN_AND_CENTRAL_AMERICA,
    ),
    (
        "Caribbean and Central America, Total",
        "groups/OECD.DAC.Region.CaribbeanAndCentralAmerica",
        _CARIBBEAN_AND_CENTRAL_AMERICA,
    ),
    (
        "South and Central Asia (DAC)",
        "groups/OECD.DAC.Region.SouthAndCentralAsia",
        _SOUTH_AND_CENTRAL_ASIA,
    ),
    (
        "South & Central Asia (DAC)",
        "groups/OECD.DAC.Region.SouthAndCentralAsia",
        _SOUTH_AND_CENTRAL_ASIA,
    ),
    (
        "South & Central Asia, Total",
        "groups/OECD.DAC.Region.SouthAndCentralAsia",
        _SOUTH_AND_CENTRAL_ASIA,
    ),
    (
        "South and Central Asia, Total",
        "groups/OECD.DAC.Region.SouthAndCentralAsia",
        _SOUTH_AND_CENTRAL_ASIA,
    ),
]


@pytest.mark.parametrize(
    "query,expected_id,expected_members",
    _QUALIFIED_DAC_REGION_ALIASES,
    ids=[case[0] for case in _QUALIFIED_DAC_REGION_ALIASES],
)
def test_qualified_dac_region_aliases_resolve_with_canonical_membership(
    dac_regions_resolver,
    query: str,
    expected_id: str,
    expected_members: set[str],
) -> None:
    """Qualified conjunction variants resolve to their snapshot DAC regions."""
    result = dac_regions_resolver.resolve(query)

    assert result.is_resolved, f"{query!r}: got {result.status.value!r}"
    assert result.entity_id == expected_id
    assert (
        set(dac_regions_resolver.members_of(query, as_codes="iso3")) == expected_members
    )
