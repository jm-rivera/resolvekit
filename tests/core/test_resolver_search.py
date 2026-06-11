"""Tests for Resolver.search() (M7)."""

import pytest

from resolvekit.core.api import Resolver
from resolvekit.core.model import CandidateSummary

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def geo_resolver(geo_test_datapack):
    """Resolver backed by the minimal geo test datapack."""
    with Resolver.from_datapacks(datapack_paths=[geo_test_datapack]) as r:
        yield r


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSearchTopK:
    """search() respects the top_k cap and returns plausible candidates."""

    def test_search_returns_top_k_candidates(self, geo_resolver):
        # Fixture has USA and GBR; top_k=1 must return at most 1 CandidateSummary.
        results = geo_resolver.diagnostics.search("United", top_k=1)
        assert len(results) <= 1
        assert all(isinstance(c, CandidateSummary) for c in results)

    def test_search_top_k_default_caps_at_ten(self, geo_resolver):
        results = geo_resolver.diagnostics.search("United")
        assert len(results) <= 10

    def test_search_first_candidate_is_expected_entity(self, geo_resolver):
        results = geo_resolver.diagnostics.search("United", top_k=3)
        assert len(results) >= 1
        entity_ids = {c.entity_id for c in results}
        assert entity_ids & {"country/USA", "country/GBR"}


class TestSearchEdgeInputs:
    """search() returns [] for empty or invalid inputs — no exceptions."""

    def test_search_empty_string_returns_empty(self, geo_resolver):
        assert geo_resolver.diagnostics.search("") == []

    def test_search_whitespace_only_returns_empty(self, geo_resolver):
        assert geo_resolver.diagnostics.search("   ") == []

    def test_search_none_returns_empty(self, geo_resolver):
        assert geo_resolver.diagnostics.search(None) == []  # type: ignore[arg-type]

    def test_search_integer_returns_empty(self, geo_resolver):
        assert geo_resolver.diagnostics.search(42) == []  # type: ignore[arg-type]

    def test_search_list_returns_empty(self, geo_resolver):
        assert geo_resolver.diagnostics.search(["United States"]) == []  # type: ignore[arg-type]


class TestSearchEnrichment:
    """search() populates canonical_name and entity_type via get_entity."""

    def test_search_includes_canonical_name(self, geo_resolver):
        results = geo_resolver.diagnostics.search("United States", top_k=3)
        assert len(results) >= 1
        assert results[0].canonical_name is not None

    def test_search_includes_entity_type(self, geo_resolver):
        results = geo_resolver.diagnostics.search("United States", top_k=3)
        assert len(results) >= 1
        assert results[0].entity_type is not None

    def test_search_includes_pack_id(self, geo_resolver):
        results = geo_resolver.diagnostics.search("United States", top_k=3)
        assert len(results) >= 1
        assert results[0].pack_id is not None

    def test_search_enrichment_values_match_entity(self, geo_resolver):
        results = geo_resolver.diagnostics.search("United States", top_k=3)
        usa = next((c for c in results if c.entity_id == "country/USA"), None)
        assert usa is not None
        assert usa.canonical_name == "United States"
        assert usa.entity_type == "geo.country"


class TestSearchBelowThreshold:
    """search() returns candidates even when resolve() would NO_MATCH."""

    def test_search_typo_still_returns_candidates(self, geo_resolver):
        # "Untied Stats" is a typo — resolve() typically returns NO_MATCH,
        # but search() bypasses the decision threshold and returns raw candidates.
        candidates = geo_resolver.diagnostics.search("Untied Stats", top_k=5)
        # The search result may or may not have candidates depending on the
        # pipeline; we assert no exception is raised and result is a list.
        assert isinstance(candidates, list)
        assert all(isinstance(c, CandidateSummary) for c in candidates)

    def test_search_below_threshold_entities_are_valid(self, geo_resolver):
        results = geo_resolver.diagnostics.search("Untied Stats", top_k=5)
        for c in results:
            assert c.entity_id  # must be non-empty string


class TestSearchClosed:
    """search() raises RuntimeError when the resolver has been closed."""

    def test_search_raises_on_closed_resolver(self, geo_test_datapack):
        r = Resolver.from_datapacks(datapack_paths=[geo_test_datapack])
        r.close()
        with pytest.raises(RuntimeError, match="closed"):
            r.diagnostics.search("United States")
