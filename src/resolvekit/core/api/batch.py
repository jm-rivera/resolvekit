"""BatchResolver — bulk resolution and Series deduplication collaborator.

Owns ``resolve_many_internal`` and ``resolve_series_dedup``.
Depends on the ``ResolverBackend`` protocol and ``QueryPreparer``, not the
concrete ``Resolver`` facade.

The weakref-per-batch invariant is owned by the per-call orchestrator
(``Resolver._resolve_inner``), which is injected as a callable here.  This
keeps the closure structure in exactly one place and lets ``BatchResolver``
remain ignorant of the Resolver.
"""

from __future__ import annotations

import weakref
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from resolvekit.core.api.loading import _normalize_domain
from resolvekit.core.engine import RoutingMode
from resolvekit.core.model import (
    ReasonCode,
    ResolutionContext,
    ResolutionResult,
    ResolutionResultList,
)

if TYPE_CHECKING:
    import pandas

    from resolvekit.core.engine.interfaces import ResolverBackend
    from resolvekit.core.explain.protocol import Explainer

    from .query_prep import QueryPreparer


class BatchResolver:
    """Owns bulk resolution and pandas Series deduplication.

    Constructed once in ``Resolver.__init__`` and reused across all calls.
    Depends on:
    - ``runner``: ``ResolverBackend`` for closed-check (via caller's delegate)
    - ``query_preparer``: ``QueryPreparer`` for ``invalid_query_result``
    - ``resolve_inner_fn``: ``Resolver._resolve_inner`` bound method
    - ``default_timeout``: forwarded from ``Resolver.__init__``
    - ``routing_mode``: for Series domain-routing validation
    """

    def __init__(
        self,
        *,
        runner: ResolverBackend,
        query_preparer: QueryPreparer,
        routing_mode: RoutingMode | None,
        default_timeout: float | None,
    ) -> None:
        self._runner = runner
        self._query_preparer = query_preparer
        self._routing_mode = routing_mode
        self._default_timeout = default_timeout

    def resolve_many_internal(
        self,
        texts: list[str],
        *,
        domain: str | list[str] | None = None,
        context: ResolutionContext | Sequence[ResolutionContext | None] | None = None,
        include_entity: bool = False,
        timeout: float | None = None,
        resolve_inner_fn: Callable[..., ResolutionResult],
        explainer_ref_factory: Callable[[], weakref.ref[Explainer]],
    ) -> ResolutionResultList:
        """Resolve multiple texts — internal bulk path used by ``bulk()``.

        Runs a serial loop with per-batch deduplication.  Identical
        ``(text, context)`` pairs are resolved once and reused.

        ``resolve_inner_fn`` is ``Resolver._resolve_inner`` (bound method).
        ``explainer_ref_factory`` is ``lambda: weakref.ref(resolver)`` — called
        once to produce the per-batch weakref.
        """
        effective_timeout = timeout if timeout is not None else self._default_timeout
        if effective_timeout is not None and effective_timeout <= 0:
            raise ValueError("timeout must be positive")

        from resolvekit.core.model import ResolutionContext as _ResolutionContext

        if context is None:
            contexts: list[ResolutionContext | None] = [None] * len(texts)
        elif isinstance(context, _ResolutionContext):
            contexts = [context] * len(texts)
        else:
            if len(context) != len(texts):
                raise ValueError(
                    f"contexts length ({len(context)}) must match "
                    f"texts length ({len(texts)})"
                )
            contexts = list(context)

        normalized_domain = _normalize_domain(domain)

        # One weakref reused across all results in the batch — avoids per-result allocation.
        _self_ref: weakref.ref[Explainer] = explainer_ref_factory()

        dedup_cache: dict[tuple[str, int], ResolutionResult] = {}
        results: list[ResolutionResult] = []
        for text, ctx in zip(texts, contexts, strict=True):
            cache_key = (text, id(ctx)) if isinstance(text, str) else None
            if cache_key is not None and cache_key in dedup_cache:
                results.append(dedup_cache[cache_key])
                continue
            result = resolve_inner_fn(
                text,
                normalized_domain=normalized_domain,
                context=ctx,
                include_entity=include_entity,
                timeout=effective_timeout,
                _self_ref=_self_ref,
            )
            if cache_key is not None:
                dedup_cache[cache_key] = result
            results.append(result)
        return ResolutionResultList(results)

    def resolve_series_dedup(
        self,
        series: pandas.Series,
        *,
        domain: str | list[str] | None,
        context: ResolutionContext | None,
        resolve_many_fn: Callable[..., ResolutionResultList],
    ) -> tuple[pandas.Index, list[ResolutionResult]]:
        """Deduplicate a Series, resolve unique values, broadcast back.

        ``resolve_many_fn`` is ``Resolver._resolve_many_internal`` (bound method).
        """
        import pandas as pd

        if domain is not None and self._routing_mode == RoutingMode.AUTO:
            raise ValueError(
                "Cannot specify domains with AUTO routing mode. "
                "Use RoutingMode.EXPLICIT for caller-controlled pack selection, "
                "or remove domain to let AUTO mode decide."
            )

        mask_na_arr = series.isna().to_numpy()
        # Cast to object before filling: typed (e.g. Int64, categorical) Series
        # reject ``fillna("")`` because the sentinel violates the dtype.
        str_values = (
            series.astype(object).map(lambda v: "" if pd.isna(v) else str(v)).to_numpy()
        )

        uniques: list[str] = list(pd.unique(str_values[~mask_na_arr]))
        resolved = resolve_many_fn(uniques, domain=domain, context=context)
        by_value: dict[str, ResolutionResult] = dict(
            zip(uniques, resolved, strict=True)
        )

        sentinel = self._query_preparer.invalid_query_result(ReasonCode.INVALID_QUERY)
        results: list[ResolutionResult] = [
            sentinel if mask_na_arr[i] else by_value[str_values[i]]
            for i in range(len(series))
        ]
        return series.index, results
