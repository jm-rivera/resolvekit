"""Integration tests for Resolver.members_of, is_member, and known_groups.

These tests require the geo pack to have been built with the groups enricher.
They are skipped automatically when groups data is not present.
"""

import warnings
from datetime import date

import pytest

from resolvekit.core.errors import GroupNotFoundError, UnknownCodeSystemError

# ---------------------------------------------------------------------------
# Module-level guard: check whether the installed geo pack has groups data
# ---------------------------------------------------------------------------


def _geo_pack_has_groups() -> bool:
    """Return True iff the bundled geo pack contains groups data."""
    try:
        from resolvekit import Resolver

        r = Resolver.from_modules(
            module_ids=["geo.countries", "geo.regions", "geo.continental_unions"]
        )
        try:
            names = r.known_groups()
            return len(names) > 0
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
# Session-scoped resolver fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def geo_resolver():  # type: ignore[no-untyped-def]
    from resolvekit import Resolver

    r = Resolver.from_modules(
        module_ids=["geo.countries", "geo.regions", "geo.continental_unions"]
    )
    yield r
    r.close()


# ---------------------------------------------------------------------------
# members_of tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_members_of_eu_current(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """EU post-Brexit has 27 members."""
    members = geo_resolver.members_of("EU", as_of=date(2025, 1, 1))
    assert len(members) == 27
    assert "country/GBR" not in members


@pytest.mark.integration
def test_members_of_eu_as_of_2018(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """EU in 2018 has 28 members (UK still in)."""
    members = geo_resolver.members_of("EU", as_of=date(2018, 6, 1))
    assert len(members) == 28
    assert "country/GBR" in members


@pytest.mark.integration
def test_members_of_as_codes_iso3(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """G7 members with as_codes='iso3' returns ISO3 strings."""
    codes = geo_resolver.members_of("G7", as_codes="iso3")
    assert isinstance(codes, list)
    assert all(isinstance(c, str) and len(c) == 3 for c in codes)
    assert "USA" in codes
    assert "DEU" in codes


@pytest.mark.integration
def test_members_of_snapshot_alias_resolves(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """Snapshot group aliases (EU28, G8) resolve and return non-empty member sets.

    Regression test for routing bug: alphanumeric aliases (letters + digits)
    were routed exclusively to the org pack, bypassing geo where these entities live.
    """
    members_eu28 = geo_resolver.members_of("EU28", as_codes="iso3")
    assert len(members_eu28) == 28, f"EU28 expected 28 members, got {len(members_eu28)}"
    assert "GBR" in members_eu28, "UK must be in EU28 snapshot"

    members_g8 = geo_resolver.members_of("G8", as_codes="iso3")
    assert len(members_g8) == 8, f"G8 expected 8 members, got {len(members_g8)}"
    assert "RUS" in members_g8, "Russia must be in G8 snapshot"


@pytest.mark.integration
def test_members_of_snapshot_ignores_as_of(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """EU28 members are identical regardless of as_of (snapshot)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        m1 = geo_resolver.members_of("EU28", as_of=date(2010, 1, 1))
        m2 = geo_resolver.members_of("EU28", as_of=date(2025, 1, 1))
        m3 = geo_resolver.members_of("EU28", as_of=date(2050, 1, 1))

    assert m1 == m2 == m3
    assert len(m1) == 28


@pytest.mark.integration
def test_members_of_snapshot_warns_on_as_of(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """Passing as_of to a snapshot group emits a UserWarning mentioning 'frozen'."""
    with pytest.warns(UserWarning, match="frozen"):
        geo_resolver.members_of("EU28", as_of=date(2018, 1, 1))


@pytest.mark.integration
def test_members_of_snapshot_no_as_of_no_warning(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """Calling members_of on a snapshot without as_of does NOT warn."""
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        geo_resolver.members_of("EU28")

    user_warnings = [w for w in record if issubclass(w.category, UserWarning)]
    assert len(user_warnings) == 0, f"Unexpected warnings: {user_warnings}"


# ---------------------------------------------------------------------------
# is_member tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_is_member_positional_args(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """is_member accepts country and group as positional args (not kwarg-only)."""
    result = geo_resolver.is_member("USA", "NATO")
    assert result is True


@pytest.mark.integration
def test_is_member_uk_in_eu_2018(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """UK was in the EU in 2018."""
    assert geo_resolver.is_member("GBR", "EU", as_of=date(2018, 1, 1)) is True


@pytest.mark.integration
def test_is_member_uk_in_eu_2025(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """UK is not in the EU in 2025."""
    assert geo_resolver.is_member("GBR", "EU", as_of=date(2025, 1, 1)) is False


@pytest.mark.integration
def test_is_member_hrv_in_eu_2010(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """Croatia did not join EU until 2013-07-01; not a member in 2010."""
    assert geo_resolver.is_member("HRV", "EU", as_of=date(2010, 1, 1)) is False


@pytest.mark.integration
def test_is_member_gbr_in_eu28_snapshot(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """UK is always in EU28 (snapshot), regardless of as_of."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        assert geo_resolver.is_member("GBR", "EU28", as_of=date(2018, 1, 1)) is True
        assert geo_resolver.is_member("GBR", "EU28", as_of=date(2025, 1, 1)) is True
    assert geo_resolver.is_member("GBR", "EU28") is True


@pytest.mark.integration
def test_is_member_snapshot_warns_on_as_of(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """is_member on a snapshot group with as_of emits UserWarning mentioning 'frozen'."""
    with pytest.warns(UserWarning, match="frozen"):
        geo_resolver.is_member("GBR", "EU28", as_of=date(2018, 1, 1))


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_members_of_unknown_group_raises_group_not_found(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """Unknown group raises GroupNotFoundError from resolvekit.errors."""
    with pytest.raises(GroupNotFoundError):
        geo_resolver.members_of("ZZZNOTAGROUP99999")


@pytest.mark.integration
def test_members_of_bad_as_codes_raises(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """Bad as_codes value raises UnknownCodeSystemError."""
    with pytest.raises(UnknownCodeSystemError):
        geo_resolver.members_of("EU", as_codes="fips")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# known_groups tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_known_groups_returns_canonical_names(geo_resolver) -> None:  # type: ignore[no-untyped-def]
    """known_groups returns a sorted list of strings including key group names."""
    groups = geo_resolver.known_groups()
    assert isinstance(groups, list)
    assert all(isinstance(g, str) for g in groups)
    # Verify sorted
    assert groups == sorted(groups)
    # Key groups present
    assert "European Union" in groups
    assert "North Atlantic Treaty Organization" in groups
    assert "Organisation for Economic Co-operation and Development" in groups
    assert "Group of Seven" in groups
