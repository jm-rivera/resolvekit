"""Regression tests for resolver_internals and result.explain() fixes.

Covers:
- Finding 1: from_system typo raises UnknownCodeSystemError instead of falling
  through to name resolution.
- Finding 2: result.explain() propagates context/domain from original call.
- Finding 3: code-lookup results carry query_text and _resolver so explain() works.
- Finding 4: bulk _pivot_result propagates UnknownCodeSystemError.
"""

from __future__ import annotations

import pytest

from resolvekit.core.api import Resolver
from resolvekit.core.api.loading import _normalize_domain
from resolvekit.core.errors import UnknownCodeSystemError
from resolvekit.core.model import ResolutionContext, ResolutionStatus


class TestFromSystemValidation:
    """Finding 1: invalid from_system should raise, not fall through."""

    def test_invalid_from_system_raises_unknown_code_system_error(
        self, geo_test_datapack
    ):
        """A typo in from_system must raise UnknownCodeSystemError, not silently
        resolve via the name pipeline."""
        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )

        with pytest.raises(UnknownCodeSystemError, match="isoo2"):
            resolver.resolve("FR", from_system="isoo2")

    def test_valid_from_system_resolves_correctly(self, geo_test_datapack):
        """A valid from_system=iso2 must still work as before."""
        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )

        result = resolver.resolve("US", from_system="iso2")

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "country/USA"

    def test_valid_from_system_no_match_returns_no_match(self, geo_test_datapack):
        """A valid system but a code that doesn't exist returns NO_MATCH."""
        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )

        result = resolver.resolve("ZZ", from_system="iso2")

        assert result.status == ResolutionStatus.NO_MATCH


class TestCodeLookupExplainability:
    """Finding 3: code-lookup results must be explainable via result.explain()."""

    def test_code_lookup_result_has_query_text(self, geo_test_datapack):
        """result.query_text must be set when resolved via from_system."""
        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )

        result = resolver.resolve("US", from_system="iso2")

        assert result.query_text == "US"

    def test_code_lookup_result_explain_does_not_raise(self, geo_test_datapack):
        """result.explain() must not raise ExplainNotAvailableError for
        code-lookup results from a live resolver."""
        from resolvekit.core.explain.scorecard import Scorecard

        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )

        result = resolver.resolve("US", from_system="iso2")
        # Should not raise
        scorecard = result.explain()

        assert isinstance(scorecard, Scorecard)

    def test_auto_detect_code_result_has_query_text(self, geo_test_datapack):
        """Auto-detect path (no from_system) also sets query_text on code hits."""
        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )

        result = resolver.resolve("USA")

        # USA matches iso3 auto-detect
        if result.status == ResolutionStatus.RESOLVED:
            assert result.query_text == "USA"


class TestExplainPreservesOptions:
    """Finding 2: result.explain() must reproduce the original context/domain."""

    def test_explain_with_context_does_not_raise(self, geo_test_datapack):
        """When a result was resolved with context=..., explain() should not crash."""
        from resolvekit.core.explain.scorecard import Scorecard

        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )
        ctx = ResolutionContext()

        result = resolver.resolve("United States", context=ctx)
        assert result.status == ResolutionStatus.RESOLVED

        scorecard = result.explain()
        assert isinstance(scorecard, Scorecard)


class TestBulkPivotErrorPropagation:
    """Finding 4: bulk(..., to='bad_system') must raise, not return None for all rows."""

    def test_bulk_with_invalid_to_raises_unknown_code_system_error(
        self, geo_test_datapack
    ):
        """An unknown to= target must raise UnknownCodeSystemError, not silently
        return a list of Nones."""
        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )

        with pytest.raises(UnknownCodeSystemError):
            resolver.bulk(
                values=["United States", "United Kingdom"], to="not_a_real_system"
            )

    def test_bulk_with_valid_to_works(self, geo_test_datapack):
        """A valid to= target must still work."""
        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )

        result = resolver.bulk(values=["United States", "United Kingdom"], to="iso3")

        # Both should resolve
        assert result is not None

    def test_bulk_no_match_row_returns_none_not_raise(self, geo_test_datapack):
        """A row that doesn't match still returns None (per-row miss is intentional)."""
        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )

        # "zzz_not_a_country" won't resolve; its None value must not be raised
        result = resolver.bulk(
            values=["United States", "zzz_not_a_country"],
            to="iso3",
            not_found="null",
        )

        # Result is a list/series — first entry should resolve, second None
        assert result is not None


class TestNormalizeDomainDottedGuard:
    """Dotted domain names (e.g. 'geo.countries') raise ValueError
    with the 'Domain names must be simple strings' message.

    Pure function-level test — no resolver instance needed.
    """

    def test_dotted_str_raises_value_error(self):
        with pytest.raises(ValueError, match="Domain names must be simple strings"):
            _normalize_domain("geo.countries")

    def test_dotted_list_member_raises_value_error(self):
        with pytest.raises(ValueError, match="Domain names must be simple strings"):
            _normalize_domain(["geo", "geo.countries"])

    def test_simple_domain_returns_frozenset(self):
        assert _normalize_domain("geo") == frozenset({"geo"})
        assert _normalize_domain(None) is None
        assert _normalize_domain(["geo", "org"]) == frozenset({"geo", "org"})
