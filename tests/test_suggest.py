"""End-to-end tests for Resolver.suggest() against real bundled data.

All tests use ``Resolver.auto()`` so they exercise the full stack:
normalization → suggest_prefix fan-out → candidate promotion → display render.
These tests run against the bundled tiers (countries, regions, continental
unions, orgs) that ship inside the wheel.
"""

from __future__ import annotations

import pytest

from resolvekit import Resolver
from resolvekit.core.model import MatchClass, SuggestionResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def resolver() -> Resolver:
    """Single auto-loaded resolver shared across all tests in this module."""
    return Resolver.auto()


# ---------------------------------------------------------------------------
# Basic ranked-list assertions
# ---------------------------------------------------------------------------


def test_suggest_unit_returns_ranked_list_including_usa(resolver: Resolver) -> None:
    results = resolver.suggest("unit", top_k=20)
    assert isinstance(results, list)
    assert len(results) > 0
    assert all(isinstance(r, SuggestionResult) for r in results)
    entity_ids = [r.entity_id for r in results]
    assert "country/USA" in entity_ids, (
        f"Expected country/USA in suggest('unit') results; got: {entity_ids}"
    )


def test_suggest_empty_returns_empty_list(resolver: Resolver) -> None:
    assert resolver.suggest("") == []


def test_suggest_whitespace_returns_empty_list(resolver: Resolver) -> None:
    assert resolver.suggest("   ") == []


def test_suggest_single_char_prefix_does_not_error(resolver: Resolver) -> None:
    # Single-char prefix is at the floor and should return a list (possibly empty).
    result = resolver.suggest("u", top_k=5)
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Fuzzy matching
# ---------------------------------------------------------------------------


def test_suggest_typo_fuzzy_always_surfaces_usa(resolver: Resolver) -> None:
    results = resolver.suggest("untied stat", top_k=10, fuzzy="always")
    entity_ids = [r.entity_id for r in results]
    assert "country/USA" in entity_ids, (
        f"Expected country/USA in fuzzy suggest('untied stat'); got {entity_ids}"
    )


def test_suggest_fuzzy_never_yields_no_fuzzy_class_results(resolver: Resolver) -> None:
    results = resolver.suggest("untied stat", top_k=10, fuzzy="never")
    fuzzy_results = [r for r in results if r.match_class == MatchClass.FUZZY]
    assert fuzzy_results == [], (
        f"fuzzy='never' should produce no FUZZY-class results; got: {fuzzy_results}"
    )


def test_suggest_fuzzy_results_carry_score(resolver: Resolver) -> None:
    results = resolver.suggest("untied stat", top_k=10, fuzzy="always")
    fuzzy_results = [r for r in results if r.match_class == MatchClass.FUZZY]
    if fuzzy_results:
        for r in fuzzy_results:
            assert r.fuzzy_score is not None
            assert 0.0 <= r.fuzzy_score <= 100.0


def test_suggest_non_fuzzy_results_have_none_fuzzy_score(resolver: Resolver) -> None:
    results = resolver.suggest("united", top_k=10, fuzzy="never")
    for r in results:
        assert r.match_class != MatchClass.FUZZY
        assert r.fuzzy_score is None


# ---------------------------------------------------------------------------
# Diacritic fold
# ---------------------------------------------------------------------------


def test_suggest_cote_finds_cote_divoire(resolver: Resolver) -> None:
    results = resolver.suggest("cote", top_k=10)
    entity_ids = [r.entity_id for r in results]
    assert "country/CIV" in entity_ids, (
        f"Expected country/CIV in suggest('cote') via diacritic fold; got: {entity_ids}"
    )


# ---------------------------------------------------------------------------
# Token-infix
# ---------------------------------------------------------------------------


@pytest.mark.requires_remote_data
def test_suggest_york_returns_new_york_admin1(resolver: Resolver) -> None:
    """'york' is a non-leading token in 'New York'; should surface via token-infix.

    Places literally named 'York' have exact_match=True so they rank ahead of New
    York (which only contains 'york' as a non-leading token).  A top_k=30 window
    is enough to see New York while leaving room for the higher-ranked Yorks.
    """
    results = resolver.suggest("york", top_k=30)
    entity_ids = [r.entity_id for r in results]
    # New York admin1 entity is geoId/36
    assert "geoId/36" in entity_ids, (
        f"Expected geoId/36 (New York admin1) in suggest('york') top_k=30; got: {entity_ids}"
    )


# ---------------------------------------------------------------------------
# to= rendering
# ---------------------------------------------------------------------------


def test_suggest_to_iso3_sets_display(resolver: Resolver) -> None:
    results = resolver.suggest("unit", top_k=10, to="iso3", entity_type="geo.country")
    usa = next((r for r in results if r.entity_id == "country/USA"), None)
    assert usa is not None
    assert usa.display == "USA", f"Expected display='USA' for iso3; got: {usa.display}"


def test_suggest_default_display_is_canonical_name(resolver: Resolver) -> None:
    results = resolver.suggest("unit", top_k=10, entity_type="geo.country")
    usa = next((r for r in results if r.entity_id == "country/USA"), None)
    assert usa is not None
    # No to= → display should be the canonical_name of the entity
    assert usa.display is not None


@pytest.mark.requires_remote_data
def test_suggest_default_to_with_on_missing_raise_does_not_raise() -> None:
    """A resolver configured ``default_to=..., on_missing='raise'`` must not
    raise from suggest() when a result lacks that code — the suggest contract
    coerces display misses to None regardless of the resolver's miss policy."""
    r = Resolver.auto(default_to="iso3", on_missing="raise")
    # 'york' surfaces New York (a region) which has no iso3 code.  Use a
    # larger window because cities literally named 'York' (exact_match=True)
    # now rank above the token-infix hit for New York.
    results = r.suggest("york", top_k=30, fuzzy="auto")
    assert results, "expected at least one suggestion for 'york'"
    ny = next((s for s in results if s.entity_id == "geoId/36"), None)
    assert ny is not None, "expected New York (geoId/36) in results (top_k=30)"
    assert ny.display is None, f"expected None display on iso3 miss; got {ny.display!r}"


# ---------------------------------------------------------------------------
# highlight_ranges
# ---------------------------------------------------------------------------


def test_suggest_highlight_ranges_correct_for_prefix_hit(resolver: Resolver) -> None:
    """For a prefix match, highlight_ranges should cover the query span in display."""
    # Use "unit" (longer prefix) with a large top_k so USA / GBR surface as exact_prefix.
    results = resolver.suggest("unit", top_k=50)
    prefix_results = [
        r
        for r in results
        if r.match_class in (MatchClass.EXACT_PREFIX, MatchClass.TOKEN_PREFIX)
        and r.highlight_ranges
        and r.display is not None
    ]
    assert prefix_results, "Expected at least one prefix result with highlight_ranges"
    for r in prefix_results:
        start, end = r.highlight_ranges[0]
        assert r.display is not None
        snippet = r.display[start:end]
        # The highlighted span should fold to something starting with the query "unit"
        from resolvekit.core.util.normalization import fold_for_match

        assert fold_for_match(snippet).startswith(fold_for_match("unit")), (
            f"highlight span {snippet!r} does not fold to start of 'unit'; "
            f"display={r.display!r}, ranges={r.highlight_ranges}"
        )


def test_suggest_fuzzy_highlight_ranges_are_empty(resolver: Resolver) -> None:
    """Fuzzy matches have no reliable literal span — highlight_ranges must be empty."""
    results = resolver.suggest("untied stat", top_k=10, fuzzy="always")
    for r in results:
        if r.match_class == MatchClass.FUZZY:
            assert r.highlight_ranges == [], (
                f"Fuzzy result {r.entity_id} should have empty highlight_ranges; "
                f"got: {r.highlight_ranges}"
            )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_suggest_two_identical_calls_produce_identical_lists(
    resolver: Resolver,
) -> None:
    results_a = resolver.suggest("unit", top_k=10)
    results_b = resolver.suggest("unit", top_k=10)
    assert [r.entity_id for r in results_a] == [r.entity_id for r in results_b], (
        "Two identical suggest() calls returned different entity_id orderings"
    )


# ---------------------------------------------------------------------------
# Closed resolver
# ---------------------------------------------------------------------------


def test_suggest_raises_runtime_error_when_closed() -> None:
    r = Resolver.auto()
    r.close()
    with pytest.raises(RuntimeError, match="closed"):
        r.suggest("test")


# ---------------------------------------------------------------------------
# Cache bypass
# ---------------------------------------------------------------------------


def test_suggest_does_not_update_query_cache(resolver: Resolver) -> None:
    """suggest() must bypass _QueryCache; hit/miss counters must not change."""
    cache = resolver._query_cache
    if cache is None:
        pytest.skip("cache disabled on this resolver")

    before = cache.info()
    resolver.suggest("unit", top_k=5)
    after = cache.info()

    assert before.hits == after.hits, (
        f"Cache hits changed after suggest(): {before.hits} → {after.hits}"
    )
    assert before.misses == after.misses, (
        f"Cache misses changed after suggest(): {before.misses} → {after.misses}"
    )


# ---------------------------------------------------------------------------
# ranking_quality
# ---------------------------------------------------------------------------


def test_suggest_geo_country_results_ranked(resolver: Resolver) -> None:
    results = resolver.suggest("unit", top_k=20, entity_type="geo.country")
    for r in results:
        assert r.ranking_quality == "ranked", (
            f"geo.country result {r.entity_id} should have ranking_quality='ranked'; "
            f"got: {r.ranking_quality}"
        )


def test_suggest_continent_results_unranked(resolver: Resolver) -> None:
    """Continents have no prominence and report ranking_quality='unranked'.

    Region tiers carry containment-derived prominence and report 'ranked'.
    """
    results = resolver.suggest("afri", top_k=20, entity_type="geo.continent")
    assert results, "expected a continent result for 'afri'"
    for r in results:
        assert r.ranking_quality == "unranked", (
            f"geo.continent result {r.entity_id} should have ranking_quality='unranked'; "
            f"got: {r.ranking_quality}"
        )


def test_suggest_subregion_results_ranked(resolver: Resolver) -> None:
    """Region tiers carry containment-derived prominence → ranking_quality='ranked'."""
    results = resolver.suggest("afri", top_k=20, entity_type="geo.subregion")
    assert results, "expected a subregion result for 'afri'"
    for r in results:
        assert r.ranking_quality == "ranked", (
            f"geo.subregion result {r.entity_id} should have ranking_quality='ranked'; "
            f"got: {r.ranking_quality}"
        )


# ---------------------------------------------------------------------------
# top_k clamping
# ---------------------------------------------------------------------------


def test_suggest_top_k_clamped_to_100(resolver: Resolver) -> None:
    results = resolver.suggest("a", top_k=9999)
    assert len(results) <= 100


def test_suggest_top_k_clamped_to_1(resolver: Resolver) -> None:
    results = resolver.suggest("unit", top_k=0)
    assert len(results) <= 1


# ---------------------------------------------------------------------------
# entity_type filter
# ---------------------------------------------------------------------------


def test_suggest_entity_type_filter_restricts_results(resolver: Resolver) -> None:
    results = resolver.suggest("unit", top_k=20, entity_type="geo.country")
    for r in results:
        assert r.entity_type is not None
        assert r.entity_type.startswith("geo.country"), (
            f"entity_type filter 'geo.country' leaked type: {r.entity_type}"
        )


# ---------------------------------------------------------------------------
# domain= pack routing
# ---------------------------------------------------------------------------


def test_suggest_domain_geo_returns_no_org_entities(resolver: Resolver) -> None:
    """domain='geo' must route only to the geo pack; no org entities should surface."""
    results = resolver.suggest("un", top_k=30, domain="geo")
    org_results = [
        r
        for r in results
        if r.pack_id == "org" or (r.entity_type or "").startswith("org.")
    ]
    assert org_results == [], (
        f"domain='geo' leaked org entities: {[(r.entity_id, r.entity_type) for r in org_results]}"
    )


def test_suggest_domain_org_returns_no_geo_entities(resolver: Resolver) -> None:
    """domain='org' must route only to the org pack; no geo entities should surface."""
    results = resolver.suggest("un", top_k=30, domain="org")
    geo_results = [
        r
        for r in results
        if r.pack_id == "geo" or (r.entity_type or "").startswith("geo.")
    ]
    assert geo_results == [], (
        f"domain='org' leaked geo entities: {[(r.entity_id, r.entity_type) for r in geo_results]}"
    )


# ---------------------------------------------------------------------------
# Exact-match acronym / short-name boosting
# ---------------------------------------------------------------------------


def test_suggest_eu_surfaces_european_union_at_rank1(resolver: Resolver) -> None:
    """An exact query for 'EU' must surface the European Union entity at rank 1.

    Without exact-match boosting, high-prominence cities/countries whose names
    merely *start with* 'eu' (e.g. United States via alias 'EUA') outrank the
    European Union even though the user typed the complete short name.
    """
    results = resolver.suggest("EU", top_k=5)
    assert results, "expected at least one result for 'EU'"
    assert results[0].entity_id == "EuropeanUnion", (
        f"Expected EuropeanUnion at rank 1 for suggest('EU'); "
        f"got: {[r.entity_id for r in results]}"
    )


def test_suggest_nato_surfaces_nato_at_rank1(resolver: Resolver) -> None:
    """Typing 'NATO' must surface the NATO entity at rank 1."""
    results = resolver.suggest("NATO", top_k=5)
    assert results, "expected at least one result for 'NATO'"
    assert results[0].entity_id == "groups/NATO", (
        f"Expected groups/NATO at rank 1 for suggest('NATO'); "
        f"got: {[r.entity_id for r in results]}"
    )


def test_suggest_un_surfaces_united_nations_at_rank1(resolver: Resolver) -> None:
    """Typing 'UN' must surface the United Nations entity at rank 1."""
    results = resolver.suggest("UN", top_k=5)
    assert results, "expected at least one result for 'UN'"
    assert results[0].entity_id == "groups/UN", (
        f"Expected groups/UN at rank 1 for suggest('UN'); "
        f"got: {[r.entity_id for r in results]}"
    )


def test_suggest_oecd_surfaces_oecd_at_rank1(resolver: Resolver) -> None:
    """Typing 'OECD' must surface the OECD entity at rank 1."""
    results = resolver.suggest("OECD", top_k=5)
    assert results, "expected at least one result for 'OECD'"
    assert results[0].entity_id == "groups/OECD", (
        f"Expected groups/OECD at rank 1 for suggest('OECD'); "
        f"got: {[r.entity_id for r in results]}"
    )


def test_suggest_exact_acronym_does_not_perturb_country_ordering(
    resolver: Resolver,
) -> None:
    """Country results must not be displaced by the exact-match boost.

    'germny' (with a typo) should still surface Germany first via fuzzy, and
    'germany' (exact) should still surface Germany at rank 1.
    """
    # Exact canonical name prefix — Germany must be first.
    results_exact = resolver.suggest("germany", top_k=5)
    assert results_exact, "expected results for 'germany'"
    assert results_exact[0].entity_id == "country/DEU", (
        f"Expected Germany (country/DEU) at rank 1 for suggest('germany'); "
        f"got: {[r.entity_id for r in results_exact]}"
    )

    # Typo variant — fuzzy must still find Germany first.
    results_typo = resolver.suggest("germny", top_k=5, fuzzy="always")
    assert results_typo, "expected results for 'germny'"
    assert results_typo[0].entity_id == "country/DEU", (
        f"Expected Germany (country/DEU) at rank 1 for suggest('germny', fuzzy='always'); "
        f"got: {[r.entity_id for r in results_typo]}"
    )
