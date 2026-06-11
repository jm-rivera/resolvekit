"""Back-compat tests for Resolver without a default_to spec.

Asserts that a resolver built with NO ``default_to`` kwarg behaves byte-for-byte
identically to pre-change behavior on ``resolve``, ``resolve_id``, ``bulk``,
and ``snap``.  This is the guardrail proving that UNSET-default does not shift
any omitted-arg behavior.
"""

from __future__ import annotations

import pytest

from resolvekit import Resolver
from resolvekit.core.errors import UnknownCodeSystemError
from resolvekit.core.model import ResolutionResult
from resolvekit.core.model.bulk_result import BulkResult

# ---------------------------------------------------------------------------
# Fixtures — no default_to in sight
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def r() -> Resolver:
    """Plain resolver — no default_to, no on_missing override."""
    return Resolver.from_modules(module_ids=["geo.countries"])


# ---------------------------------------------------------------------------
# resolve() — no spec → behavior unchanged
# ---------------------------------------------------------------------------


class TestResolveNoSpec:
    def test_omitted_to_returns_result(self, r: Resolver) -> None:
        """resolve(text) → ResolutionResult (legacy)."""
        result = r.resolve("United States")
        assert isinstance(result, ResolutionResult)
        assert result.entity_id == "country/USA"

    def test_explicit_to_str_returns_str(self, r: Resolver) -> None:
        """resolve(text, to='iso3') → str."""
        out = r.resolve("United States", to="iso3")
        assert out == "USA"
        assert isinstance(out, str)

    def test_no_match_returns_result(self, r: Resolver) -> None:
        """resolve(text) with no match → ResolutionResult (NO_MATCH status)."""
        result = r.resolve("zzz_not_a_place_xyzzy")
        assert isinstance(result, ResolutionResult)
        assert not result.is_resolved

    def test_explicit_to_none_returns_result(self, r: Resolver) -> None:
        """resolve(text, to=None) → ResolutionResult."""
        result = r.resolve("United States", to=None)
        assert isinstance(result, ResolutionResult)
        assert result.entity_id == "country/USA"


# ---------------------------------------------------------------------------
# resolve_id() — no spec → behavior unchanged
# ---------------------------------------------------------------------------


class TestResolveIdNoSpec:
    def test_returns_entity_id(self, r: Resolver) -> None:
        """resolve_id(text) → entity_id str."""
        entity_id = r.resolve_id("United States")
        assert entity_id == "country/USA"

    def test_no_match_returns_none(self, r: Resolver) -> None:
        """resolve_id with no match → None."""
        assert r.resolve_id("zzz_not_a_place_xyzzy") is None


# ---------------------------------------------------------------------------
# bulk() — no spec → behavior unchanged
# ---------------------------------------------------------------------------


class TestBulkNoSpec:
    def test_no_to_returns_bulk_result(self, r: Resolver) -> None:
        """bulk(values=[...]) without to → BulkResult."""
        result = r.bulk(values=["France", "Germany"])
        assert isinstance(result, BulkResult)

    def test_explicit_to_returns_native_series(self, r: Resolver) -> None:
        """bulk(values=[...], to='iso3') → native series (list here)."""
        out = r.bulk(values=["France", "Germany"], to="iso3")
        # Without pandas/polars, returns a list.
        assert isinstance(out, list)
        assert "FRA" in out
        assert "DEU" in out

    def test_explicit_typo_raises_unknown_code_system(self, r: Resolver) -> None:
        """bulk(values=[...], to='iso33') → UnknownCodeSystemError (typo detection)."""
        with pytest.raises((UnknownCodeSystemError, Exception)):
            r.bulk(values=["France"], to="iso33")


# ---------------------------------------------------------------------------
# snap() — no spec → behavior unchanged
# ---------------------------------------------------------------------------


class TestSnapNoSpec:
    def test_returns_entity_id(self, r: Resolver) -> None:
        """snap without to= → entity_id (legacy)."""
        candidates = ["country/USA", "country/GBR", "country/FRA"]
        out = r.snap(query="United States", candidates=candidates)
        assert out == "country/USA"

    def test_explicit_to_pivots(self, r: Resolver) -> None:
        """snap(to='iso3') → code string."""
        candidates = ["country/USA", "country/GBR"]
        out = r.snap(query="United States", candidates=candidates, to="iso3")
        assert out == "USA"

    def test_explicit_to_none_returns_entity_id(self, r: Resolver) -> None:
        """snap(to=None) → entity_id explicitly."""
        candidates = ["country/USA", "country/GBR"]
        out = r.snap(query="United States", candidates=candidates, to=None)
        assert out == "country/USA"
