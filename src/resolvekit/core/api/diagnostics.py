"""Diagnostics namespace classes for ``Resolver.diagnostics``."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resolvekit.core.api.cache import CacheInfo
    from resolvekit.core.api.resolver import Resolver
    from resolvekit.core.model import CandidateSummary, EntityRecord, ResolutionContext
    from resolvekit.core.model.inspection import InspectionReport


class _CacheNamespace:
    """Cache sub-namespace accessible as ``resolver.diagnostics.cache``."""

    __slots__ = ("_resolver",)

    def __init__(self, resolver: Resolver) -> None:
        self._resolver = resolver

    def info(self) -> CacheInfo | None:
        """Return cache statistics, or None when the cache is off.

        Returns:
            A :class:`~resolvekit.core.api.cache.CacheInfo` named-tuple
            with fields ``(hits, misses, maxsize, currsize)``, or ``None``
            when no cache was configured (``cache_size=0``).
        """
        if self._resolver._query_cache is None:
            return None
        return self._resolver._query_cache.info()

    def clear(self) -> None:
        """Evict all query-cache entries and reset hit/miss counters.

        No-op when the cache is off (``cache_size=0``).
        """
        if self._resolver._query_cache is not None:
            self._resolver._query_cache.clear()


class _DiagnosticsNamespace:
    """Diagnostics namespace accessible as ``resolver.diagnostics``.

    Provides ``inspect``, ``search``, and the ``cache`` sub-namespace.
    """

    __slots__ = ("_cache_ns", "_resolver")

    def __init__(self, resolver: Resolver) -> None:
        self._resolver = resolver
        self._cache_ns = _CacheNamespace(resolver)

    @property
    def cache(self) -> _CacheNamespace:
        """Cache sub-namespace with ``info()`` and ``clear()``."""
        return self._cache_ns

    def inspect(
        self,
        text: str,
        *,
        domain: str | list[str] | None = None,
    ) -> InspectionReport:
        """Diagnostic helper: report how *text* matches across known data.

        Returns an :class:`~resolvekit.InspectionReport` showing exact code
        matches, exact name matches, and the top-5 fuzzy candidates
        (unfiltered by the decision-policy confidence threshold).

        This is a debugging tool. Use ``resolver.resolve()`` for production
        resolution.

        Args:
            text: Query text to inspect.
            domain: Optional domain filter (same semantics as
                ``resolver.resolve()``).

        Returns:
            InspectionReport with match details.  Always returns a report
            — invalid or empty input yields an empty-match report rather
            than raising.

        Raises:
            RuntimeError: If the resolver has been closed.
        """
        from resolvekit.core.api.inspect import _run_inspection

        if self._resolver._closed:
            raise RuntimeError("Resolver has been closed")
        return _run_inspection(resolver=self._resolver, text=text, domain=domain)

    def search(
        self,
        text: str,
        *,
        top_k: int = 10,
        domain: str | list[str] | None = None,
        context: ResolutionContext | None = None,
    ) -> list[CandidateSummary]:
        """Return top-K candidates regardless of confidence threshold.

        Search runs the full pipeline (no decision step) plus per-candidate
        enrichment lookups.  The query cache does NOT apply — every call
        re-runs retrieval and scoring.

        Args:
            text: Text to search for candidates.
            top_k: Maximum number of candidates to return (default 10).
            domain: Optional domain(s) to route to.
            context: Optional resolution context.

        Returns:
            List of enriched :class:`~resolvekit.core.model.CandidateSummary`
            objects ordered by confidence descending.  May be shorter than
            ``top_k``.  Returns ``[]`` for empty or non-string input.

        Raises:
            RuntimeError: If the resolver has been closed.
        """
        return self._resolver._search_internal(
            text, top_k=top_k, domain=domain, context=context
        )

    def unresolved_relations(
        self,
        entity_or_id: str | EntityRecord,
        *,
        relation: str | None = None,
    ) -> list[dict[str, object]]:
        """Return relation edges whose target_id does not resolve in loaded packs.

        Each dict has keys: ``"relation_type"``, ``"target_id"``,
        ``"valid_from"``, ``"valid_until"``.

        Diagnostics-only: there is no ``as_of`` filter — all edges (including
        temporally expired ones) are reported so nothing is hidden during
        debugging.  Filter ``"valid_until"`` yourself if needed.

        Args:
            entity_or_id: An EntityRecord, entity ID string, or exact
                canonical name/alias string.  Resolved deterministically via
                the same no-fuzzy path as ``Resolver.related()``.
            relation: When given, only inspect edges of this type.  ``None``
                inspects all edge types.

        Returns:
            List of dicts for edges whose ``target_id`` is absent from the
            loaded packs, in the original edge order.

        Raises:
            EntityNotFoundError: String *entity_or_id* matches no entity.
            AmbiguousResolutionError: String *entity_or_id* matches >1 entity.
            RuntimeError: If the resolver has been closed.
        """
        if self._resolver._closed:
            raise RuntimeError("Resolver has been closed")

        entity = self._resolver._resolve_entity_arg(entity_or_id)
        runner = self._resolver._runner

        result: list[dict[str, object]] = []
        for rel in entity.relations:
            if relation is not None and rel.relation_type != relation:
                continue
            if runner.get_entity(rel.target_id) is None:
                result.append(
                    {
                        "relation_type": rel.relation_type,
                        "target_id": rel.target_id,
                        "valid_from": rel.valid_from,
                        "valid_until": rel.valid_until,
                    }
                )
        return result
