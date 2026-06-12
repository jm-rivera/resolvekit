"""Integration tests for Resolver default-output wiring.

Tests use ``Resolver.from_modules(module_ids=["geo.countries",
"geo.continental_unions"])`` unless noted — the continental-unions module is
named explicitly because "European Union" (the canonical iso3-less example) is a
continental union, and module selection is authoritative (no transitive load).

Coverage:
- Return-type matrix for resolve()
- spec active + NO_MATCH → None
- OutputMissingError scalar miss; on_missing="null"; on_missing="raise"
- Fallback chain ["iso3","name"]
- resolve_id immunity (critical guard against pivot leakage)
- Query-cache invariant
- auto(domains=[...], default_to="iso3") exercises both forwarding paths
- Closed resolver still raises before pivot
- snap default cases (spec pivots; to=None → entity_id; miss raises)
- as_result=True combined with to= raises ValueError
"""

from __future__ import annotations

import pytest

from resolvekit import Resolver
from resolvekit.core.errors import OutputMissingError
from resolvekit.core.model import EntityRecord, ResolutionResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def r_geo() -> Resolver:
    """Resolver over geo.countries — no default output (legacy)."""
    return Resolver.from_modules(module_ids=["geo.countries"])


@pytest.fixture(scope="module")
def r_iso3() -> Resolver:
    """Resolver over geo countries + continental unions with default_to='iso3'."""
    return Resolver.from_modules(
        module_ids=["geo.countries", "geo.continental_unions"], default_to="iso3"
    )


@pytest.fixture(scope="module")
def r_null() -> Resolver:
    """Resolver with default_to='iso3', on_missing='null'."""
    return Resolver.from_modules(
        module_ids=["geo.countries", "geo.continental_unions"],
        default_to="iso3",
        on_missing="null",
    )


@pytest.fixture(scope="module")
def r_raise() -> Resolver:
    """Resolver with default_to='iso3', on_missing='raise'."""
    return Resolver.from_modules(
        module_ids=["geo.countries", "geo.continental_unions"],
        default_to="iso3",
        on_missing="raise",
    )


@pytest.fixture(scope="module")
def r_chain() -> Resolver:
    """Resolver with fallback chain ['iso3', 'name']."""
    return Resolver.from_modules(
        module_ids=["geo.countries", "geo.continental_unions"],
        default_to=["iso3", "name"],
    )


# ---------------------------------------------------------------------------
# Return-type matrix
# ---------------------------------------------------------------------------


class TestReturnTypeMatrix:
    def test_no_spec_omitted_returns_result(self, r_geo: Resolver) -> None:
        """no-spec + to omitted → ResolutionResult (legacy, unchanged)."""
        result = r_geo.resolve("United States")
        assert isinstance(result, ResolutionResult)
        assert result.entity_id == "country/USA"

    def test_spec_omitted_returns_str(self, r_iso3: Resolver) -> None:
        """spec(iso3) + to omitted → str."""
        out = r_iso3.resolve("United States")
        assert out == "USA"
        assert isinstance(out, str)

    def test_explicit_to_str(self, r_iso3: Resolver) -> None:
        """Explicit to='iso2' overrides spec → str."""
        out = r_iso3.resolve("United States", to="iso2")
        assert out == "US"
        assert isinstance(out, str)

    def test_explicit_to_none_returns_result(self, r_iso3: Resolver) -> None:
        """Explicit to=None forces ResolutionResult regardless of spec."""
        result = r_iso3.resolve("United States", to=None)
        assert isinstance(result, ResolutionResult)
        assert result.entity_id == "country/USA"

    def test_as_result_true_returns_result(self, r_iso3: Resolver) -> None:
        """as_result=True forces ResolutionResult even with spec active."""
        result = r_iso3.resolve("United States", as_result=True)
        assert isinstance(result, ResolutionResult)
        assert result.entity_id == "country/USA"

    def test_explicit_to_entity_record(self, r_iso3: Resolver) -> None:
        """Explicit to=EntityRecord → EntityRecord."""
        out = r_iso3.resolve("United States", to=EntityRecord)
        assert isinstance(out, EntityRecord)

    def test_as_result_plus_explicit_to_raises_value_error(
        self, r_iso3: Resolver
    ) -> None:
        """as_result=True + explicit non-None to= → ValueError."""
        with pytest.raises(ValueError, match="pass either to= or as_result"):
            r_iso3.resolve("United States", to="iso2", as_result=True)


# ---------------------------------------------------------------------------
# spec active + NO_MATCH
# ---------------------------------------------------------------------------


class TestSpecNoMatch:
    def test_no_match_returns_none(self, r_iso3: Resolver) -> None:
        """spec active + input that does not resolve → None."""
        out = r_iso3.resolve("zzz_not_a_place_xyzzy")
        assert out is None

    def test_no_spec_no_match_returns_result(self, r_geo: Resolver) -> None:
        """no spec + NO_MATCH → ResolutionResult (legacy)."""
        result = r_geo.resolve("zzz_not_a_place_xyzzy")
        assert isinstance(result, ResolutionResult)
        assert not result.is_resolved


# ---------------------------------------------------------------------------
# OutputMissingError + on_missing policy
# ---------------------------------------------------------------------------


class TestOnMissingPolicy:
    def test_scalar_miss_raises_output_missing_error(self, r_raise: Resolver) -> None:
        """on_missing='raise' + entity lacking iso3 → OutputMissingError."""
        # European Union entity lacks iso3.
        with pytest.raises(OutputMissingError) as exc_info:
            r_raise.resolve("European Union")
        err = exc_info.value
        assert err.entity_id is not None
        assert "iso3" in err.requested

    def test_on_missing_null_returns_none(self, r_null: Resolver) -> None:
        """on_missing='null' + entity lacking iso3 → None."""
        out = r_null.resolve("European Union")
        assert out is None

    def test_on_missing_auto_scalar_raises(self, r_iso3: Resolver) -> None:
        """on_missing='auto' scalar → raises OutputMissingError for missing code."""
        with pytest.raises(OutputMissingError):
            r_iso3.resolve("European Union")


# ---------------------------------------------------------------------------
# Fallback chain
# ---------------------------------------------------------------------------


class TestFallbackChain:
    def test_chain_falls_through_to_name(self, r_chain: Resolver) -> None:
        """chain ['iso3','name'] → iso3 for normal country."""
        assert r_chain.resolve("United States") == "USA"

    def test_chain_falls_through_for_iso3_less_entity(self, r_chain: Resolver) -> None:
        """chain falls through to name when iso3 absent (European Union)."""
        out = r_chain.resolve("European Union")
        # Should return a name string, not None and not raise.
        assert isinstance(out, str)
        assert len(out) > 0


# ---------------------------------------------------------------------------
# resolve_id immunity (critical: prevent pivot leakage)
# ---------------------------------------------------------------------------


class TestResolveIdImmunity:
    def test_resolve_id_ignores_default_to(self, r_iso3: Resolver) -> None:
        """resolve_id always returns entity_id regardless of default_to spec."""
        entity_id = r_iso3.resolve_id("United States")
        assert entity_id == "country/USA"

    def test_resolve_id_no_spec_baseline(self, r_geo: Resolver) -> None:
        """resolve_id on no-spec resolver returns entity_id (regression guard)."""
        assert r_geo.resolve_id("France") == "country/FRA"


# ---------------------------------------------------------------------------
# Query-cache invariant
# ---------------------------------------------------------------------------


class TestQueryCacheInvariant:
    def test_cache_hits_and_spec_still_pivots(self, r_iso3: Resolver) -> None:
        """resolve twice; both return 'USA'; cache hit observed."""
        r_iso3.diagnostics.cache.clear()
        first = r_iso3.resolve("United States")
        second = r_iso3.resolve("United States")
        assert first == "USA"
        assert second == "USA"
        info = r_iso3.diagnostics.cache.info()
        assert info is not None
        assert info.hits >= 1


# ---------------------------------------------------------------------------
# auto() with different parameter combinations
# ---------------------------------------------------------------------------


class TestAutoTwoForwardingSites:
    @pytest.mark.requires_remote_data
    def test_auto_with_domains_and_default_to_builds(self) -> None:
        """auto(domains=[...], default_to='iso3') exercises the domain-filter path."""
        r = Resolver.auto(domains=["geo"], default_to="iso3")
        out = r.resolve("France")
        assert out == "FRA"

    def test_auto_without_domains_and_default_to_builds(self) -> None:
        """auto(default_to='iso3') works without domain filters."""
        r = Resolver.auto(default_to="iso3")
        out = r.resolve("Germany")
        assert out == "DEU"


# ---------------------------------------------------------------------------
# Closed resolver raises before pivot
# ---------------------------------------------------------------------------


def test_closed_resolver_raises_runtime_error(r_iso3: Resolver) -> None:
    """Closed resolver raises RuntimeError before any spec pivot."""
    with Resolver.from_modules(
        module_ids=["geo.countries"], default_to="iso3"
    ) as r_tmp:
        pass  # closes on __exit__
    with pytest.raises(RuntimeError, match="closed"):
        r_tmp.resolve("United States")


# ---------------------------------------------------------------------------
# snap default cases
# ---------------------------------------------------------------------------


class TestSnapDefaultOutput:
    def test_snap_with_default_spec_pivots(self, r_iso3: Resolver) -> None:
        """snap with default spec returns pivoted code."""
        candidates = [
            "country/USA",
            "country/GBR",
            "country/FRA",
        ]
        out = r_iso3.snap(query="United States", candidates=candidates)
        assert out == "USA"

    def test_snap_explicit_to_none_returns_entity_id(self, r_iso3: Resolver) -> None:
        """snap with explicit to=None returns entity_id (pre-spec behavior)."""
        candidates = ["country/USA", "country/GBR"]
        out = r_iso3.snap(query="United States", candidates=candidates, to=None)
        assert out == "country/USA"

    def test_snap_no_spec_returns_entity_id(self, r_geo: Resolver) -> None:
        """snap without spec returns entity_id (unchanged legacy behavior)."""
        candidates = ["country/USA", "country/GBR"]
        out = r_geo.snap(query="United States", candidates=candidates)
        assert out == "country/USA"

    def test_snap_miss_raises_output_missing_error(self, r_iso3: Resolver) -> None:
        """snap with iso3 spec + entity lacking iso3 → OutputMissingError (on_missing='auto')."""
        # European Union resolves but has no iso3 code.
        with pytest.raises(OutputMissingError):
            r_iso3.snap(query="European Union", candidates=["EuropeanUnion"])
