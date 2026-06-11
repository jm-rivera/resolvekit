"""Regression tests for query-cache mutation leakage.

``ResolutionResult.reasons``, ``.candidates``, and ``.refinement_hints`` are
now tuple-typed (immutable), so in-place mutation raises ``AttributeError``.
The cache-integrity invariant is preserved as a structural property rather than
a defensive-copy concern.
"""

from __future__ import annotations

from typing import Any

import pytest

from resolvekit.core.api.cache import _detach_mutables, _QueryCache
from resolvekit.core.model import (
    CandidateSummary,
    ReasonCode,
    ResolutionResult,
    ResolutionStatus,
)


def _make_result() -> ResolutionResult:
    return ResolutionResult(
        query_text="France",
        status=ResolutionStatus.RESOLVED,
        entity_id="country/FRA",
        confidence=0.93,
        reasons=[ReasonCode.EXACT_NAME_MATCH],
        candidates=[CandidateSummary(entity_id="country/FRA", confidence=0.93)],
    )


class TestDetachMutables:
    def test_copy_has_equal_values(self) -> None:
        original = _make_result()
        detached = _detach_mutables(original)
        assert detached.reasons == original.reasons
        assert detached.candidates == original.candidates
        assert detached.refinement_hints == original.refinement_hints

    def test_fields_are_tuples(self) -> None:
        result = _make_result()
        assert isinstance(result.reasons, tuple)
        assert isinstance(result.candidates, tuple)
        assert isinstance(result.refinement_hints, tuple)

    def test_mutation_raises(self) -> None:
        result = _make_result()
        with pytest.raises(AttributeError):
            result.reasons.append(ReasonCode.INTERNAL_ERROR)  # type: ignore[attr-defined]
        with pytest.raises(AttributeError):
            result.candidates.clear()  # type: ignore[attr-defined]


class TestQueryCacheNoLeak:
    def test_cache_hit_returns_detached_copy(self) -> None:
        cache = _QueryCache(maxsize=8)
        result = _make_result()

        first = cache.get_or_call(
            raw_text="France", context=None, domains=None, inner=lambda: result
        )
        assert first.reasons == (ReasonCode.EXACT_NAME_MATCH,)

        second = cache.get_or_call(
            raw_text="France",
            context=None,
            domains=None,
            inner=lambda: pytest.fail("inner should not run on a cache hit"),
        )
        assert second.reasons == first.reasons

    def test_tuple_fields_prevent_cache_poisoning(self) -> None:
        cache = _QueryCache(maxsize=8)
        result = _make_result()

        first = cache.get_or_call(
            raw_text="France", context=None, domains=None, inner=lambda: result
        )
        # Tuple fields are immutable — mutation is impossible, cache is safe by type.
        with pytest.raises(AttributeError):
            first.reasons.append(ReasonCode.INTERNAL_ERROR)  # type: ignore[attr-defined]

        second = cache.get_or_call(
            raw_text="France",
            context=None,
            domains=None,
            inner=lambda: pytest.fail("inner should not run on a cache hit"),
        )
        assert second.reasons == (ReasonCode.EXACT_NAME_MATCH,)


class TestResolverEndToEnd:
    @pytest.fixture
    def resolver(self, geo_test_datapack: Any) -> Any:
        from resolvekit.core.api.resolver import Resolver

        r = Resolver.from_datapacks(datapack_paths=[geo_test_datapack])
        yield r
        r.close()

    def test_reasons_is_tuple(self, resolver: Any) -> None:
        first = resolver.resolve("United States")
        assert isinstance(first.reasons, tuple)

    def test_candidates_is_tuple(self, resolver: Any) -> None:
        first = resolver.resolve("United States")
        assert isinstance(first.candidates, tuple)

    def test_reasons_mutation_raises(self, resolver: Any) -> None:
        first = resolver.resolve("United States")
        with pytest.raises(AttributeError):
            first.reasons.append("CORRUPTED")  # type: ignore[attr-defined]

    def test_candidates_mutation_raises(self, resolver: Any) -> None:
        first = resolver.resolve("United States")
        with pytest.raises(AttributeError):
            first.candidates.clear()  # type: ignore[attr-defined]

    def test_cache_returns_consistent_reasons(self, resolver: Any) -> None:
        first = resolver.resolve("United States")
        second = resolver.resolve("United States")
        assert first.reasons == second.reasons
