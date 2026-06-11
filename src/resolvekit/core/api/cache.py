"""Query-level LRU cache for ``Resolver.resolve()``.

Thin wrapper over :func:`functools.lru_cache`.  Each ``_QueryCache`` instance
owns a per-instance cached lookup keyed by ``(raw_text, id(context), domains)``.
Two structurally-equal but distinct ``ResolutionContext`` objects produce
distinct cache entries — this is intentional.  The ``auto()`` use-case (one
long-lived resolver, a small number of reused context objects) benefits from
O(1) key construction without paying for structural comparison.

The key uses the *case-preserving* raw text (whitespace-trimmed) rather than
the casefolded normalized form because some pack sources (e.g. the geo
short-input gate) make resolution decisions on raw casing — ``"US"`` and
``"us"`` would normalize to the same form but produce different results.
Whitespace-only variants (``"Italy"`` vs ``"  Italy  "``) still share a cache
entry since whitespace never alters source decisions.

``resolve_explained()`` deliberately bypasses the cache because its scorecard
contract is per-call.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from resolvekit.core.model import ResolutionResult


class CacheInfo(NamedTuple):
    """Snapshot of query-cache statistics.

    Mirrors the shape of :func:`functools.lru_cache`'s ``_CacheInfo`` for
    familiarity.

    Attributes:
        hits: Number of cache hits since creation or last clear.
        misses: Number of cache misses since creation or last clear.
        maxsize: Maximum number of entries (same as the ``cache_size``
            constructor argument).
        currsize: Current number of entries in the cache.
    """

    hits: int
    misses: int
    maxsize: int | None
    currsize: int


def _detach_mutables(result: ResolutionResult) -> ResolutionResult:
    """Return a shallow copy of *result*, preserving the ``_explainer`` back-reference.

    ``candidates``, ``reasons``, and ``refinement_hints`` are now tuple-typed
    (immutable), so no container copying is required.  ``model_copy`` is still
    called to give each caller a distinct identity, and the ``_explainer``
    weakref is re-attached because ``model_copy`` does not carry private attrs.
    """
    copy = result.model_copy()
    copy._explainer = result._explainer
    return copy


class _QueryCache:
    """Per-instance LRU wrapping ``functools.lru_cache``.

    The miss-path callable changes per call (it's a closure capturing the
    current ``Query`` / ``ResolutionContext``), which can't go in the cache
    key.  We stash the pending callable on ``self`` and have the cached
    lookup invoke it.  Single-threaded by design — the ``Resolver``
    documents that concurrent calls require separate instances.
    """

    def __init__(self, *, maxsize: int) -> None:
        self._pending: Callable[[], ResolutionResult] | None = None

        @functools.lru_cache(maxsize=maxsize)
        def lookup(_key: tuple[str, int, frozenset[str]]) -> ResolutionResult:
            assert self._pending is not None  # set by get_or_call
            return self._pending()

        self._lookup = lookup

    def get_or_call(
        self,
        *,
        raw_text: str,
        context: object | None,
        domains: frozenset[str] | set[str] | None,
        inner: Callable[[], ResolutionResult],
    ) -> ResolutionResult:
        """Return a cached result or call *inner* and cache the result.

        Keyed on raw text (not normalized) so case-sensitive source decisions
        don't collide — ``"US"`` and ``"us"`` are distinct cache entries.

        Domains participate in the key so EXPLICIT/HYBRID routing modes don't
        leak a result from one domain set to a sibling call with a different
        domain set.  AUTO callers always pass ``None`` and share the empty
        frozenset.
        """
        self._pending = inner
        domain_key = frozenset(domains) if domains else frozenset()
        key = (raw_text, 0 if context is None else id(context), domain_key)
        try:
            return _detach_mutables(self._lookup(key))
        finally:
            self._pending = None

    def info(self) -> CacheInfo:
        """Return a snapshot of cache statistics."""
        return CacheInfo(*self._lookup.cache_info())

    def clear(self) -> None:
        """Evict all cached entries and reset hit/miss counters."""
        self._lookup.cache_clear()
