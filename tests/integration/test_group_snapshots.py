"""Integration tests for snapshot group entities.

Verifies:
- Snapshot aliases (EU27, EU28, EU15, G8, BRIC) resolve to their snapshot entity IDs.
- members_of on snapshots is stable across different as_of values.
- Canonical EU correctly responds to as_of (UK in 2018, out 2021).
- Snapshot EU28 includes UK at both dates.
"""

import warnings
from datetime import date

import pytest

# ---------------------------------------------------------------------------
# Module-level guard
# ---------------------------------------------------------------------------


def _geo_pack_has_groups() -> bool:
    try:
        from resolvekit import Resolver

        r = Resolver.with_modules(
            "geo.countries", "geo.regions", "geo.continental_unions"
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

    r = Resolver.with_modules("geo.countries", "geo.regions", "geo.continental_unions")
    yield r
    r.close()


# ---------------------------------------------------------------------------
# Snapshot entity resolution tests
# ---------------------------------------------------------------------------

_SNAPSHOT_CASES = [
    ("EU27", "groups/EU27_2020"),
    ("EU28", "groups/EU28"),
    ("EU15", "groups/EU15"),
    ("G8", "groups/G8"),
    ("BRIC", "groups/BRIC"),
]


@pytest.mark.integration
@pytest.mark.parametrize(
    "alias,expected_id", _SNAPSHOT_CASES, ids=[c[0] for c in _SNAPSHOT_CASES]
)
def test_snapshot_alias_resolves_to_expected_entity(
    geo_resolver,  # type: ignore[no-untyped-def]
    alias: str,
    expected_id: str,
) -> None:
    """Each snapshot alias resolves to its expected entity_id."""
    result = geo_resolver.resolve(alias)
    assert result.is_resolved, (
        f"{alias!r}: expected RESOLVED but got status={result.status.value!r}"
    )
    assert result.entity_id == expected_id, (
        f"{alias!r}: expected {expected_id!r} but got {result.entity_id!r}"
    )


# ---------------------------------------------------------------------------
# Snapshot stability tests: members_of identical across as_of
# ---------------------------------------------------------------------------

_SNAPSHOT_STABILITY_CASES = [
    "EU27",
    "EU28",
    "EU15",
    "G8",
    "BRIC",
]

_THREE_DATES = [date(2000, 1, 1), date(2018, 6, 1), date(2035, 1, 1)]


@pytest.mark.integration
@pytest.mark.parametrize("alias", _SNAPSHOT_STABILITY_CASES)
def test_snapshot_members_stable_across_as_of(
    geo_resolver,
    alias: str,  # type: ignore[no-untyped-def]
) -> None:
    """members_of on a snapshot returns identical results for any as_of."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        results = [geo_resolver.members_of(alias, as_of=d) for d in _THREE_DATES]

    first = results[0]
    for subsequent in results[1:]:
        assert subsequent == first, (
            f"{alias}: snapshot membership changed with as_of — "
            f"expected stable but got {subsequent} vs {first}"
        )


# ---------------------------------------------------------------------------
# Canonical EU time-awareness: UK in 2018, not in 2021
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_canonical_eu_includes_gbr_in_2018(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """Canonical EU (time-aware) includes UK on 2018-06-01."""
    members = geo_resolver.members_of("EU", as_of=date(2018, 6, 1))
    assert "country/GBR" in members, "Expected GBR in EU on 2018-06-01"


@pytest.mark.integration
def test_canonical_eu_excludes_gbr_in_2021(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """Canonical EU (time-aware) excludes UK on 2021-01-01 (post-Brexit)."""
    members = geo_resolver.members_of("EU", as_of=date(2021, 1, 1))
    assert "country/GBR" not in members, "Expected GBR not in EU on 2021-01-01"


# ---------------------------------------------------------------------------
# Snapshot EU28: UK is always a member
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_snapshot_eu28_includes_gbr_pre_brexit(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """Snapshot EU28 includes UK even at a pre-Brexit date (snapshot semantics)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        result = geo_resolver.is_member("GBR", "EU28", as_of=date(2018, 6, 1))
    assert result is True


@pytest.mark.integration
def test_snapshot_eu28_includes_gbr_post_brexit(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """Snapshot EU28 includes UK at a post-Brexit date (snapshot semantics)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        result = geo_resolver.is_member("GBR", "EU28", as_of=date(2025, 1, 1))
    assert result is True
