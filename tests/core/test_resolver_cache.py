"""Tests for the Resolver query cache (M1).

All tests use a minimal fake runner so they run offline with no installed
modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from resolvekit.core.api.cache import CacheInfo, _QueryCache
from resolvekit.core.api.resolver import Resolver
from resolvekit.core.engine.interfaces import PipelineResult
from resolvekit.core.model import (
    EntityRecord,
    Query,
    ResolutionContext,
    ResolutionResult,
    ResolutionStatus,
)

# ---------------------------------------------------------------------------
# Minimal fake backend
# ---------------------------------------------------------------------------


@dataclass
class _FakeBackend:
    """Minimal ResolverBackend that counts resolve() calls."""

    call_count: int = 0
    result: ResolutionResult = field(
        default_factory=lambda: ResolutionResult(status=ResolutionStatus.NO_MATCH)
    )
    _available: frozenset[str] = field(default_factory=frozenset)

    # -- ResolverBackend protocol --

    def resolve(
        self,
        query: Query,
        context: ResolutionContext,
        *,
        trace_sink: Any = None,
        deadline: float | None = None,
    ) -> ResolutionResult:
        self.call_count += 1
        return self.result

    def resolve_detailed(
        self,
        query: Query,
        context: ResolutionContext,
        *,
        trace_sink: Any = None,
        deadline: float | None = None,
    ) -> PipelineResult:
        self.call_count += 1
        return PipelineResult(result=self.result)

    def close(self) -> None:
        pass

    def get_entity(self, entity_id: str) -> EntityRecord | None:
        return None

    def lookup_code(self, system: str, value_norm: str) -> list[str]:
        return []

    @property
    def available_packs(self) -> frozenset[str]:
        return self._available


def _make_resolver(*, cache_size: int = 0) -> tuple[Resolver, _FakeBackend]:
    backend = _FakeBackend()
    resolver = Resolver(backend, cache_size=cache_size)
    return resolver, backend


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCacheOff:
    def test_default_cache_off(self) -> None:
        resolver, _ = _make_resolver(cache_size=0)
        assert resolver.diagnostics.cache.info() is None

    def test_cache_clear_noop_when_off(self) -> None:
        resolver, _ = _make_resolver(cache_size=0)
        resolver.diagnostics.cache.clear()  # must not raise

    def test_resolve_without_cache_calls_runner_every_time(self) -> None:
        resolver, backend = _make_resolver(cache_size=0)
        resolver.resolve("hello")
        resolver.resolve("hello")
        assert backend.call_count == 2


class TestCacheOn:
    def test_cache_hit_short_circuits_runner(self) -> None:
        resolver, backend = _make_resolver(cache_size=128)
        resolver.resolve("hello")
        resolver.resolve("hello")
        assert backend.call_count == 1
        info = resolver.diagnostics.cache.info()
        assert info is not None
        assert info.hits == 1
        assert info.misses == 1

    def test_cache_keyed_by_context(self) -> None:
        resolver, backend = _make_resolver(cache_size=128)
        ctx1 = ResolutionContext()
        ctx2 = ResolutionContext()
        resolver.resolve("hello", context=ctx1)
        resolver.resolve("hello", context=ctx2)
        # Two distinct context objects → two misses
        assert backend.call_count == 2
        info = resolver.diagnostics.cache.info()
        assert info is not None
        assert info.misses == 2
        assert info.hits == 0

    def test_same_context_object_gives_cache_hit(self) -> None:
        resolver, backend = _make_resolver(cache_size=128)
        ctx = ResolutionContext()
        resolver.resolve("hello", context=ctx)
        resolver.resolve("hello", context=ctx)
        assert backend.call_count == 1
        info = resolver.diagnostics.cache.info()
        assert info is not None
        assert info.hits == 1

    def test_none_context_is_shared_across_calls(self) -> None:
        resolver, backend = _make_resolver(cache_size=128)
        resolver.resolve("hello", context=None)
        resolver.resolve("hello", context=None)
        assert backend.call_count == 1

    def test_cache_clear_resets_stats(self) -> None:
        resolver, backend = _make_resolver(cache_size=128)
        resolver.resolve("hello")
        info = resolver.diagnostics.cache.info()
        assert info is not None
        assert info.misses == 1
        resolver.diagnostics.cache.clear()
        info = resolver.diagnostics.cache.info()
        assert info is not None
        assert info.hits == 0
        assert info.misses == 0
        assert info.currsize == 0
        resolver.resolve("hello")
        info = resolver.diagnostics.cache.info()
        assert info is not None
        assert info.misses == 1
        assert backend.call_count == 2  # called again after clear

    def test_include_entity_bypasses_cache(self) -> None:
        resolver, backend = _make_resolver(cache_size=128)
        resolver.resolve("hello", include_entity=True)
        resolver.resolve("hello", include_entity=True)
        assert backend.call_count == 2
        # Cache should still report no misses (bypassed entirely)
        info = resolver.diagnostics.cache.info()
        assert info is not None
        assert info.misses == 0

    def test_timeout_bypasses_cache(self) -> None:
        resolver, backend = _make_resolver(cache_size=128)
        resolver.resolve("hello", timeout=10.0)
        resolver.resolve("hello", timeout=10.0)
        assert backend.call_count == 2
        info = resolver.diagnostics.cache.info()
        assert info is not None
        assert info.misses == 0

    def test_maxsize_reflected_in_cache_info(self) -> None:
        resolver, _ = _make_resolver(cache_size=42)
        info = resolver.diagnostics.cache.info()
        assert info is not None
        assert info.maxsize == 42

    def test_currsize_increments_on_miss(self) -> None:
        resolver, _ = _make_resolver(cache_size=128)
        info = resolver.diagnostics.cache.info()
        assert info is not None
        assert info.currsize == 0
        resolver.resolve("hello")
        info = resolver.diagnostics.cache.info()
        assert info is not None
        assert info.currsize == 1
        resolver.resolve("world")
        info = resolver.diagnostics.cache.info()
        assert info is not None
        assert info.currsize == 2

    def test_currsize_resets_after_clear(self) -> None:
        resolver, _ = _make_resolver(cache_size=128)
        resolver.resolve("hello")
        resolver.diagnostics.cache.clear()
        info = resolver.diagnostics.cache.info()
        assert info is not None
        assert info.currsize == 0


class TestResolveExplainedNotCached:
    def test_resolve_explained_does_not_use_cache(self) -> None:
        """resolve_explained() must bypass the cache (scorecard is per-call)."""
        backend = _FakeBackend()
        resolver = Resolver(backend, cache_size=128)
        # Seed with a plain resolve so there is something in the cache.
        resolver.resolve("hello")
        info = resolver.diagnostics.cache.info()
        assert info is not None
        assert info.misses == 1
        initial_call_count = backend.call_count

        # resolve_explained bypasses the cache entirely.
        resolver.resolve_explained("hello")
        # Cache hits/misses must be unchanged (resolve_explained doesn't touch cache).
        info = resolver.diagnostics.cache.info()
        assert info is not None
        assert info.hits == 0  # no new hits
        assert info.misses == 1  # no new misses
        # The backend must be called (resolve_explained always goes to runner).
        assert backend.call_count > initial_call_count


class TestCacheInfoTyping:
    def test_cache_info_is_named_tuple(self) -> None:
        info = CacheInfo(hits=1, misses=2, maxsize=10, currsize=3)
        assert isinstance(info, tuple)
        assert info.hits == 1
        assert info[0] == 1
        assert info.misses == 2
        assert info[1] == 2
        assert info.maxsize == 10
        assert info[2] == 10
        assert info.currsize == 3
        assert info[3] == 3

    def test_resolver_cache_info_returns_cache_info_instance(self) -> None:
        resolver, _ = _make_resolver(cache_size=10)
        info = resolver.diagnostics.cache.info()
        assert isinstance(info, CacheInfo)


class TestCacheKeyPostNormalization:
    def test_whitespace_variants_share_cache_entry(self) -> None:
        """Whitespace-trimmed raw text means whitespace-variant inputs share entries."""
        backend = _FakeBackend()
        resolver = Resolver(backend, cache_size=128)
        resolver.resolve("Italy")
        resolver.resolve("  Italy  ")
        # Both strip to "Italy", so backend should be called only once.
        info = resolver.diagnostics.cache.info()
        assert info is not None
        assert backend.call_count == 1
        assert info.hits == 1

    def test_case_variants_get_distinct_cache_entries(self) -> None:
        """Cache key preserves case so source decisions on raw casing don't collide.

        Regression test: the geo short-input gate treats lowercase ``us`` as a
        degenerate spreadsheet sentinel (no_match) and uppercase ``US`` as a
        valid ISO2 code. A case-folded cache key would let the first call
        poison the second.
        """
        backend = _FakeBackend()
        resolver = Resolver(backend, cache_size=128)
        resolver.resolve("us")
        resolver.resolve("US")
        # Different cases must produce different cache entries.
        assert backend.call_count == 2
        info = resolver.diagnostics.cache.info()
        assert info is not None
        assert info.hits == 0
        assert info.misses == 2


class TestCacheHitAlignsQueryText:
    """Pin: cache hit returns query_text of the CURRENT caller, not the first.

    Regression guard for the weakref-per-batch behavior in
    ``Resolver._resolve_inner``: after a cache hit, the result is
    model_copy'd to overwrite ``query_text`` with the caller's
    ``original_text``. If a refactor drops this realignment, the second
    caller would see the first caller's raw text (e.g. ``"  hello  "``
    instead of ``"hello"``).
    """

    def test_whitespace_variant_cache_hit_keeps_current_query_text(self) -> None:
        resolver, backend = _make_resolver(cache_size=128)
        first = resolver.resolve("  hello  ")
        second = resolver.resolve("hello")
        assert backend.call_count == 1  # confirms second was a cache hit
        assert first.query_text == "  hello  "
        assert second.query_text == "hello"  # NOT "  hello  "


class TestResolveManyInternalDedup:
    """Pin: same (text, context) pair is resolved once across the batch.

    Counts calls via the runner-level _FakeBackend.call_count rather than
    mocking Resolver. The dedup loop key is ``(text, id(ctx))`` — two
    repeats with the same context must hit the runner exactly once.
    """

    def test_repeat_text_same_context_resolves_once(self) -> None:
        resolver, backend = _make_resolver(cache_size=0)  # cache OFF — isolate dedup
        ctx = ResolutionContext()
        results = resolver._resolve_many_internal(
            ["Italy", "Italy", "Germany"], context=ctx
        )
        assert len(results) == 3
        assert backend.call_count == 2

    def test_repeat_text_distinct_context_resolves_twice(self) -> None:
        resolver, backend = _make_resolver(cache_size=0)
        ctx_a = ResolutionContext()
        ctx_b = ResolutionContext()
        resolver._resolve_many_internal(["Italy", "Italy"], context=[ctx_a, ctx_b])
        assert backend.call_count == 2

    def test_none_context_dedup_uses_shared_default(self) -> None:
        """context=None expands to [None]*N — all entries share id(None),
        so repeats dedup just like an explicit shared context."""
        resolver, backend = _make_resolver(cache_size=0)
        resolver._resolve_many_internal(["Italy", "Italy", "Italy"], context=None)
        assert backend.call_count == 1


class TestQueryCacheUnit:
    """Unit tests for _QueryCache directly."""

    def test_lru_eviction(self) -> None:
        cache: _QueryCache = _QueryCache(maxsize=2)
        results = [
            ResolutionResult(status=ResolutionStatus.NO_MATCH),
            ResolutionResult(status=ResolutionStatus.NO_MATCH),
            ResolutionResult(status=ResolutionStatus.NO_MATCH),
        ]
        ctx = ResolutionContext()
        it = iter(results)

        cache.get_or_call(
            raw_text="a", context=ctx, domains=None, inner=lambda: next(it)
        )
        cache.get_or_call(
            raw_text="b", context=ctx, domains=None, inner=lambda: next(it)
        )
        # "a" should be evicted when "c" is inserted (maxsize=2).
        cache.get_or_call(
            raw_text="c", context=ctx, domains=None, inner=lambda: next(it)
        )
        assert cache.info().currsize == 2
        # "b" and "c" remain; "a" was evicted — re-fetching "a" is a miss.
        misses_before = cache.info().misses
        cache.get_or_call(
            raw_text="a",
            context=ctx,
            domains=None,
            inner=lambda: ResolutionResult(status=ResolutionStatus.NO_MATCH),
        )
        assert cache.info().misses == misses_before + 1
