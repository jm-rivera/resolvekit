"""Integration tests for group abbreviation resolution.

Verifies that common group names and abbreviations (EU, NATO, OECD, G7, etc.)
resolve to their expected entity IDs in the geo pack.
"""

import pytest

from resolvekit.core.api.resolver import ExplainedResolution
from resolvekit.core.model.result import ReasonCode, ResolutionStatus

# ---------------------------------------------------------------------------
# Module-level guard
# ---------------------------------------------------------------------------


def _geo_pack_has_groups() -> bool:
    try:
        from resolvekit import Resolver

        r = Resolver.from_modules(
            ["geo.countries", "geo.regions", "geo.continental_unions"]
        )
        try:
            return len(r.known_groups()) > 0
        finally:
            r.close()
    except Exception:
        return False


_GEO_PACK_HAS_GROUPS = _geo_pack_has_groups()
pytestmark = pytest.mark.skipif(
    not _GEO_PACK_HAS_GROUPS,
    reason="geo pack does not include groups data; rebuild with build_group_contribution",
)


# ---------------------------------------------------------------------------
# Session-scoped resolver
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def geo_resolver():  # type: ignore[no-untyped-def]
    from resolvekit import Resolver

    r = Resolver.from_modules(
        ["geo.countries", "geo.regions", "geo.continental_unions"]
    )
    yield r
    r.close()


# ---------------------------------------------------------------------------
# Parametrized resolution tests
# ---------------------------------------------------------------------------

_RESOLUTION_CASES = [
    # (input_string, expected_entity_id)
    # EU reuses the existing DC entity (EuropeanUnion, no prefix).
    ("EU", "EuropeanUnion"),
    ("European Union", "EuropeanUnion"),
    ("NATO", "groups/NATO"),
    ("N.A.T.O.", "groups/NATO"),
    # OECD reuses the existing DC entity (groups/OECD).
    ("OECD", "groups/OECD"),
    # G7 resolves via GROUP_PREFERENCE_TIEBREAK (UN region also carries the alias).
    ("G7", "groups/G7"),
    ("G20", "groups/G20"),
    ("G77", "groups/G77"),
    ("ASEAN", "groups/ASEAN"),
    ("BRICS", "groups/BRICS"),
    ("MERCOSUR", "groups/MERCOSUR"),
    ("OPEC", "groups/OPEC"),
]


@pytest.mark.integration
@pytest.mark.parametrize(
    "query,expected_id", _RESOLUTION_CASES, ids=[c[0] for c in _RESOLUTION_CASES]
)
def test_group_resolves_to_expected_entity(
    geo_resolver,  # type: ignore[no-untyped-def]
    query: str,
    expected_id: str,
) -> None:
    """Each group alias resolves to its expected entity_id."""
    result = geo_resolver.resolve(query)
    assert result.is_resolved, (
        f"{query!r}: expected RESOLVED but got status={result.status.value!r}"
    )
    assert result.entity_id == expected_id, (
        f"{query!r}: expected {expected_id!r} but got {result.entity_id!r}"
    )


@pytest.mark.integration
def test_g7_via_members_of(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """G7 disambiguates via _resolve_group_id when accessed through members_of."""
    members = geo_resolver.members_of("G7", as_codes="iso3")
    assert sorted(members) == ["CAN", "DEU", "FRA", "GBR", "ITA", "JPN", "USA"]


@pytest.mark.integration
def test_oecd_does_not_resolve_to_country_starting_oec(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """OECD must not resolve to any country whose code starts with OEC."""
    result = geo_resolver.resolve("OECD")
    assert result.is_resolved
    eid = result.entity_id or ""
    # A country whose ISO3 is 'OEC' would have entity_id 'country/OEC...'
    assert not eid.startswith("country/OEC"), (
        f"OECD incorrectly resolved to a country entity: {eid!r}"
    )


@pytest.mark.integration
def test_g7_resolve_emits_tiebreak_reason(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """G7 resolves via GROUP_PREFERENCE_TIEBREAK and hydrates correctly with include_entity."""
    result = geo_resolver.resolve("G7")
    assert result.is_resolved, f"expected RESOLVED but got {result.status.value!r}"
    assert result.entity_id == "groups/G7"
    assert ReasonCode.GROUP_PREFERENCE_TIEBREAK in result.reasons

    result_with_entity = geo_resolver.resolve("G7", include_entity=True)
    assert result_with_entity.entity is not None
    assert result_with_entity.entity.entity_id == "groups/G7"


@pytest.mark.integration
def test_g7_via_resolve_explained(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """resolve_explained("G7") reflects post-rule RESOLVED status in both result and scorecard."""
    explained = geo_resolver.resolve_explained("G7")
    assert isinstance(explained, ExplainedResolution)
    assert explained.result.is_resolved, (
        f"expected result.is_resolved but got {explained.result.status.value!r}"
    )
    assert explained.result.entity_id == "groups/G7"
    assert ReasonCode.GROUP_PREFERENCE_TIEBREAK in explained.result.reasons
    assert explained.scorecard.status == ResolutionStatus.RESOLVED


@pytest.mark.integration
def test_g7_resolve_cached_returns_resolved_twice() -> None:
    """Cached resolver returns RESOLVED for G7 on both calls, with at least one cache hit."""
    from resolvekit import Resolver

    # with_modules does not expose cache_size; use from_modules instead.
    r = Resolver.from_modules(
        ["geo.countries", "geo.regions", "geo.continental_unions"],
        cache_size=8,
    )
    try:
        first = r.resolve("G7")
        assert first.is_resolved, (
            f"first call: expected RESOLVED, got {first.status.value!r}"
        )
        assert first.entity_id == "groups/G7"

        second = r.resolve("G7")
        assert second.is_resolved, (
            f"second call: expected RESOLVED, got {second.status.value!r}"
        )
        assert second.entity_id == "groups/G7"

        info = r.cache_info()
        assert info is not None
        assert info.hits >= 1, (
            f"expected >=1 cache hit after second call, got {info.hits}"
        )
    finally:
        r.close()
