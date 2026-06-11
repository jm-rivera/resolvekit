"""Regression tests for query-cache mutation leakage .

In-place mutation of a returned result's list fields must not poison the
query cache: a cache hit must return a result whose mutable containers are not
shared with the cached entry.
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
    def test_lists_are_fresh_objects(self) -> None:
        original = _make_result()
        detached = _detach_mutables(original)
        assert detached.reasons == original.reasons
        assert detached.reasons is not original.reasons
        assert detached.candidates is not original.candidates
        assert detached.refinement_hints is not original.refinement_hints

    def test_mutating_detached_does_not_touch_original(self) -> None:
        original = _make_result()
        detached = _detach_mutables(original)
        detached.reasons.append(ReasonCode.INTERNAL_ERROR)
        assert ReasonCode.INTERNAL_ERROR not in original.reasons


class TestQueryCacheNoLeak:
    def test_cache_hit_returns_detached_lists(self) -> None:
        cache = _QueryCache(maxsize=8)
        result = _make_result()

        first = cache.get_or_call(
            raw_text="France", context=None, domains=None, inner=lambda: result
        )
        # Poison the FIRST returned result's reasons in place.
        first.reasons.append(ReasonCode.INTERNAL_ERROR)

        # A subsequent hit must not see the poison.
        second = cache.get_or_call(
            raw_text="France",
            context=None,
            domains=None,
            inner=lambda: pytest.fail("inner should not run on a cache hit"),
        )
        assert ReasonCode.INTERNAL_ERROR not in second.reasons
        assert second.reasons == [ReasonCode.EXACT_NAME_MATCH]


class TestResolverEndToEnd:
    @pytest.fixture
    def resolver(self, geo_test_datapack: Any) -> Any:
        from resolvekit.core.api.resolver import Resolver

        r = Resolver.from_datapacks(datapack_paths=[geo_test_datapack])
        yield r
        r.close()

    def test_reasons_mutation_does_not_poison_cache(self, resolver: Any) -> None:
        first = resolver.resolve("United States")
        if not first.reasons:
            pytest.skip("fixture resolution carries no reasons to mutate")
        first.reasons.append("CORRUPTED")
        second = resolver.resolve("United States")
        assert "CORRUPTED" not in second.reasons

    def test_candidates_mutation_does_not_poison_cache(self, resolver: Any) -> None:
        first = resolver.resolve("United States")
        before = len(first.candidates)
        first.candidates.clear()
        second = resolver.resolve("United States")
        assert len(second.candidates) == before
