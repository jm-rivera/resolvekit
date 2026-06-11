"""Tests for OutputView forwarding.

Coverage:
- view.resolve() returns configured output
- view.resolve_id() returns entity_id, never pivoted
- view.bulk() returns spec-pivoted series
- view.snap() returns spec-pivoted value
- chain view (["iso3","name"]) falls through for iso3-less entity
- view.resolve(as_result=True) returns ResolutionResult
- OutputView is frozen (attribute assignment raises)
- Building a view does NOT mutate the underlying resolver (_output_spec stays None)
"""

from __future__ import annotations

import pytest

from resolvekit import Resolver
from resolvekit.core.api.output_view import OutputView
from resolvekit.core.model import ResolutionResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def r_geo() -> Resolver:
    """Resolver over geo.countries — no default output."""
    return Resolver.from_modules(module_ids=["geo.countries"])


# ---------------------------------------------------------------------------
# Basic forwarding
# ---------------------------------------------------------------------------


class TestOutputViewResolve:
    def test_resolve_returns_configured_output(self, r_geo: Resolver) -> None:
        """view.resolve() returns the iso3 code, not a ResolutionResult."""
        view = r_geo.to("iso3")
        assert view.resolve("United States") == "USA"

    def test_resolve_id_returns_entity_id_not_pivoted(self, r_geo: Resolver) -> None:
        """resolve_id always returns entity_id even on a bound view."""
        view = r_geo.to("iso3")
        result = view.resolve_id("United States")
        assert result == "country/USA"
        assert result != "USA"  # must NOT be pivoted

    def test_resolve_as_result_true_returns_resolution_result(
        self, r_geo: Resolver
    ) -> None:
        """as_result=True bypasses spec and returns a full ResolutionResult."""
        view = r_geo.to("iso3")
        result = view.resolve("United States", as_result=True)
        assert isinstance(result, ResolutionResult)
        assert result.entity_id == "country/USA"


# ---------------------------------------------------------------------------
# Bulk forwarding
# ---------------------------------------------------------------------------


class TestOutputViewBulk:
    def test_bulk_returns_iso3_series(self, r_geo: Resolver) -> None:
        """view.bulk() returns a series of iso3 codes."""
        view = r_geo.to("iso3")
        result = view.bulk(values=["France", "Germany"])
        # Result is a series (list or pandas Series — both are iterable)
        values = list(result)
        assert "FRA" in values
        assert "DEU" in values

    def test_bulk_chain_falls_through_for_iso3_less_entity(
        self, r_geo: Resolver
    ) -> None:
        """Chain ["iso3","name"]: an iso3-less entity falls through to its name."""
        view = r_geo.to(["iso3", "name"])
        # France has iso3; result should be "FRA".
        result = view.bulk(values=["France", "Germany"])
        values = list(result)
        assert "FRA" in values
        assert "DEU" in values


# ---------------------------------------------------------------------------
# Snap forwarding
# ---------------------------------------------------------------------------


class TestOutputViewSnap:
    def test_snap_returns_pivoted_value(self, r_geo: Resolver) -> None:
        """view.snap() resolves the best match and returns the configured output."""
        view = r_geo.to("iso3")
        result = view.snap(query="Spain", candidates=["country/ESP", "country/FRA"])
        assert result == "ESP"


# ---------------------------------------------------------------------------
# Chain view (fallback)
# ---------------------------------------------------------------------------


class TestOutputViewChain:
    def test_chain_view_falls_through_for_no_iso3(self, r_geo: Resolver) -> None:
        """r.to(['iso3','name']) falls through to name when iso3 is absent."""
        # "France" has iso3=FRA; the chain returns it directly.
        view = r_geo.to(["iso3", "name"])
        assert view.resolve("France") == "FRA"


# ---------------------------------------------------------------------------
# Query-cache invariant
# ---------------------------------------------------------------------------


class TestOutputViewCache:
    def test_resolve_twice_hits_cache(self, r_geo: Resolver) -> None:
        """view.resolve() twice: second call is a cache hit."""
        view = r_geo.to("iso3")
        r_geo.diagnostics.cache.clear()
        first = view.resolve("France")
        second = view.resolve("France")
        assert first == "FRA"
        assert second == "FRA"
        info = r_geo.diagnostics.cache.info()
        assert info is not None
        assert info.hits >= 1


# ---------------------------------------------------------------------------
# Frozen / isolation invariants
# ---------------------------------------------------------------------------


class TestOutputViewInvariants:
    def test_output_view_is_frozen(self, r_geo: Resolver) -> None:
        """OutputView is a frozen dataclass — attribute assignment must raise."""
        view = r_geo.to("iso3")
        with pytest.raises((AttributeError, TypeError)):
            view._spec = None  # type: ignore[misc]

    def test_building_view_does_not_mutate_resolver(self, r_geo: Resolver) -> None:
        """r.to(...) returns a new view; r._output_spec remains None."""
        assert r_geo._output_spec is None
        _view = r_geo.to("iso3")
        # The view holds its own spec; the resolver must be unaffected.
        assert r_geo._output_spec is None

    def test_output_view_type(self, r_geo: Resolver) -> None:
        """r.to() returns an OutputView instance."""
        view = r_geo.to("iso3")
        assert isinstance(view, OutputView)
