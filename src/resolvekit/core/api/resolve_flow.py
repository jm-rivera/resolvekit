"""ResolveFlow — per-call resolution orchestrator.

Owns ``resolve_inner``, ``resolve_explained``, and ``search_internal``.
Depends on ``ResolverBackend`` (protocol) and collaborators injected at
construction time.

Cache / weakref invariants:
- One ``weakref.ref[Explainer]`` per batch, allocated by the caller.
- Cache enabled only when ``include_entity=False`` and ``timeout is None``.
- Cache-hit ``query_text`` realignment: ``model_copy`` keeps the current
  caller's original_text, not the first caller's.
"""

from __future__ import annotations

import time
import weakref
from typing import TYPE_CHECKING

from resolvekit.core.api.loading import _normalize_domain
from resolvekit.core.model import (
    ReasonCode,
    ResolutionContext,
    ResolutionResult,
    ResolutionStatus,
)

if TYPE_CHECKING:
    from resolvekit.core.api.cache import _QueryCache
    from resolvekit.core.api.group_api import GroupAPI
    from resolvekit.core.api.query_prep import QueryPreparer
    from resolvekit.core.engine.interfaces import ResolverBackend
    from resolvekit.core.explain.protocol import Explainer
    from resolvekit.core.explain.result_types import ExplainedResolution
    from resolvekit.core.explain.scorecard import Verbosity
    from resolvekit.core.model import CandidateSummary, Query


class ResolveFlow:
    """Per-call resolution orchestrator.

    Constructed once in ``Resolver.__init__`` and reused across all calls.

    Args:
        runner: ``ResolverBackend`` for the hot resolve/get_entity paths.
        query_preparer: ``QueryPreparer`` for normalize/prepare/invalid helpers.
        group_api: ``GroupAPI`` for the group-preference tiebreak step.
        query_cache: Optional ``_QueryCache`` instance; ``None`` disables caching.
        max_query_length: Truncation limit forwarded to ``resolve_explained``.
        default_timeout: Per-resolver default; per-call ``timeout=`` overrides.
    """

    def __init__(
        self,
        *,
        runner: ResolverBackend,
        query_preparer: QueryPreparer,
        group_api: GroupAPI,
        query_cache: _QueryCache | None,
        max_query_length: int,
        default_timeout: float | None,
    ) -> None:
        self._runner = runner
        self._query_preparer = query_preparer
        self._group_api = group_api
        self._query_cache = query_cache
        self._max_query_length = max_query_length
        self._default_timeout = default_timeout

    def resolve_inner(
        self,
        text: str,
        *,
        normalized_domain: frozenset[str] | None,
        context: ResolutionContext | None,
        include_entity: bool,
        timeout: float | None,
        _self_ref: weakref.ref[Explainer] | None = None,
    ) -> ResolutionResult:
        """Per-call resolve path that skips _normalize_domain re-validation.

        Callers that already validated domains at batch start (e.g.
        ``BatchResolver.resolve_many_internal``) take this entry point.  The
        public ``Resolver.resolve()`` validates once then delegates here.

        ``_self_ref`` is always provided by the caller:
        - Single-call paths: ``weakref.ref(resolver)`` allocated once per call.
        - Batch paths: one ref allocated at batch start and reused (per-batch
          invariant pinned by TestResolveManyInternalDedup).

        Cache invariants:
        - Cache enabled iff ``self._query_cache is not None and not
          include_entity and timeout is None``.
        - Timeout is per-call: each call computes its own deadline from
          ``time.monotonic()``, so no batch-level budget is introduced.

        The nested ``_do_resolve`` closure captures ``query``, ``ctx``,
        ``deadline``, ``original_text``, ``include_entity``, and ``ref`` from
        the enclosing scope to enable weakref-per-batch reuse and cache-hit
        ``query_text`` realignment.
        """
        from resolvekit.core.util.normalization import NormalizationError

        original_text = text
        if not text or not text.strip():
            return self._query_preparer.invalid_query_result()
        deadline = time.monotonic() + timeout if timeout is not None else None
        try:
            query, ctx = self._query_preparer.prepare_query(
                text, context, normalized_domain
            )
        except NormalizationError:
            return self._query_preparer.invalid_query_result()

        # _self_ref is always non-None at runtime: the facade passes weakref.ref(self)
        # for single calls and BatchResolver passes a pre-allocated ref for batches.
        assert _self_ref is not None, "caller must supply _self_ref"
        ref: weakref.ref[Explainer] = _self_ref

        def _do_resolve() -> ResolutionResult:
            res = self._runner.resolve(query, ctx, deadline=deadline)
            res = res.model_copy(update={"query_text": original_text})
            # Pydantic v2 model_copy may not preserve PrivateAttr — set explicitly.
            res._explainer = ref
            res = self._group_api.apply_group_preference_tiebreak(res)
            if (
                include_entity
                and res.entity_id
                and res.status == ResolutionStatus.RESOLVED
            ):
                entity = self._runner.get_entity(res.entity_id)
                if entity:
                    res = res.model_copy(update={"entity": entity})
                    res._explainer = ref
            return res

        # Cache applies only when no per-call options complicate the result.
        # include_entity and timeout both produce call-specific results, so
        # they bypass the cache.
        if self._query_cache is not None and not include_entity and timeout is None:
            cached = self._query_cache.get_or_call(
                raw_text=query.raw_text.strip(),
                context=ctx,
                domains=query.domains,
                inner=_do_resolve,
            )
            # Keep the user-visible query_text aligned with THIS caller's input
            # rather than the first caller's raw text (e.g. "us" vs "US").
            if cached.query_text != original_text:
                cached = cached.model_copy(update={"query_text": original_text})
                cached._explainer = ref
            return cached
        return _do_resolve()

    def resolve_explained(
        self,
        text: object,
        *,
        domain: str | list[str] | None = None,
        context: ResolutionContext | None = None,
        verbosity: Verbosity | str,
        timeout: float | None = None,
        default_timeout: float | None,
        _self_ref: weakref.ref[Explainer] | None = None,
    ) -> ExplainedResolution:
        """Resolve with full tracing; returns ``ExplainedResolution``.

        Three early-return paths construct a stub ``Scorecard`` directly for
        inputs that never reach the runner (non-string, empty, normalization
        failure).  The hot path collects trace events via ``MemoryTraceSink``
        and hands them to ``ScorecardBuilder``.

        Args:
            text: The text to resolve.
            domain: Optional domain filter.
            context: Optional resolution context.
            verbosity: Scorecard verbosity level.
            timeout: Per-call timeout override.
            default_timeout: Resolver-level default timeout.
        """
        from resolvekit.core.explain import MemoryTraceSink, Scorecard, ScorecardBuilder
        from resolvekit.core.explain.result_types import ExplainedResolution
        from resolvekit.core.explain.scorecard import Verbosity as _Verbosity
        from resolvekit.core.util.normalization import NormalizationError

        effective_timeout = timeout if timeout is not None else default_timeout
        if effective_timeout is not None and effective_timeout <= 0:
            raise ValueError("timeout must be positive")

        def _stub_explained(
            result: ResolutionResult, query_text: str
        ) -> ExplainedResolution:
            """Wrap a result in an ExplainedResolution with a no-runner stub scorecard."""
            scorecard = Scorecard(
                query_text=query_text,
                normalized_text="",
                status=result.status,
                reasons=list(result.reasons),
            )
            return ExplainedResolution(result, scorecard)

        if not isinstance(text, str):
            return _stub_explained(
                self._query_preparer.invalid_query_result(
                    ReasonCode.INVALID_INPUT_TYPE
                ),
                "",
            )

        original_text = text
        if not text or not text.strip():
            return _stub_explained(
                self._query_preparer.invalid_query_result(), text or ""
            )

        deadline = (
            time.monotonic() + effective_timeout
            if effective_timeout is not None
            else None
        )
        raw_text = text[: self._max_query_length]
        try:
            query, ctx = self._query_preparer.prepare_query(
                raw_text, context, _normalize_domain(domain)
            )
        except NormalizationError:
            return _stub_explained(
                self._query_preparer.invalid_query_result(), raw_text
            )

        if isinstance(verbosity, str):
            verbosity = _Verbosity(verbosity)

        assert _self_ref is not None, (
            "caller must supply _self_ref (Explainer back-reference)"
        )
        ref: weakref.ref[Explainer] = _self_ref

        call_sink = MemoryTraceSink()
        pipeline_result = self._runner.resolve_detailed(
            query, ctx, trace_sink=call_sink, deadline=deadline
        )
        result = pipeline_result.result
        candidates = pipeline_result.candidates
        pack_id = pipeline_result.pack_id
        result = result.model_copy(update={"query_text": original_text})
        result = self._group_api.apply_group_preference_tiebreak(result)
        # Pydantic v2 model_copy may not preserve PrivateAttr — set explicitly.
        result._explainer = ref
        trace_events = call_sink.get_events()

        builder = ScorecardBuilder(verbosity=verbosity)
        scorecard = builder.build(
            query=query,
            result=result,
            trace_events=trace_events,
            candidates=candidates,
            pack_id=pack_id or result.pack_id,
        )
        return ExplainedResolution(result, scorecard)

    def search_internal(
        self,
        text: str,
        *,
        top_k: int = 10,
        domain: str | list[str] | None = None,
        context: ResolutionContext | None = None,
    ) -> list[CandidateSummary]:
        """Internal search returning enriched candidate summaries.

        Delegated to by ``diagnostics.search``.
        """
        from resolvekit.core.engine import build_candidate_summary
        from resolvekit.core.util.normalization import NormalizationError

        if not isinstance(text, str) or not text or not text.strip():
            return []
        try:
            query, ctx = self._query_preparer.prepare_query(
                text, context, _normalize_domain(domain)
            )
        except NormalizationError:
            return []
        pipeline_result = self._runner.resolve_detailed(query, ctx)
        result = pipeline_result.result
        candidates = pipeline_result.candidates
        pack_id = pipeline_result.pack_id
        # The pipeline already enriched up to DEFAULT_TOP_K_RESULTS (5) candidates
        # with canonical_name/entity_type/pack_id; reuse them when top_k is in range.
        if top_k <= len(result.candidates):
            return list(result.candidates[:top_k])
        if not candidates:
            return list(result.candidates)
        # Slow path: top_k exceeds the enriched-candidates cap.
        fallback_pack_id = pack_id or self._runner.lookup_pack_id()
        enriched_count = len(result.candidates)
        extras = [
            _enrich_summary(
                build_candidate_summary(c), fallback_pack_id, runner=self._runner
            )
            for c in candidates[enriched_count:top_k]
        ]
        return list(result.candidates) + extras


def _enrich_summary(
    summary: CandidateSummary,
    pack_id: str | None,
    *,
    runner: ResolverBackend,
) -> CandidateSummary:
    """Enrich a CandidateSummary with entity data from the runner."""
    entity = runner.get_entity(summary.entity_id)
    return summary.model_copy(
        update={
            "canonical_name": entity.canonical_name if entity else None,
            "entity_type": entity.entity_type if entity else None,
            "pack_id": summary.pack_id or pack_id,
        }
    )


def prepare_detailed_call(
    *,
    text: str,
    context: ResolutionContext | None,
    domain: str | list[str] | None,
    effective_timeout: float | None,
    query_preparer: QueryPreparer,
) -> tuple[Query, ResolutionContext, float | None] | None:
    """Validate, prepare, and compute the deadline for a resolve_detailed call.

    Shared query-prep logic factored out of ``Resolver.resolve_detailed`` so it
    is single-sourced alongside ``ResolveFlow.resolve_inner``.

    Returns ``None`` to signal the invalid-query path (caller should return an
    empty ``PipelineResult``).  On success returns ``(query, ctx, deadline)``.

    Args:
        text: The text to resolve (callers must already have checked non-str /
            empty before calling; this function handles the ``NormalizationError``
            guard only).
        context: Optional resolution context.
        domain: Optional domain filter; passed through ``_normalize_domain``.
        effective_timeout: Resolved timeout (per-call override or resolver
            default), already validated ``> 0`` by the caller.
        query_preparer: ``QueryPreparer`` instance to call ``prepare_query`` on.

    Returns:
        ``(query, ctx, deadline)`` on success, or ``None`` on
        ``NormalizationError`` (invalid query).
    """
    from resolvekit.core.util.normalization import NormalizationError

    try:
        query, ctx = query_preparer.prepare_query(
            text, context, _normalize_domain(domain)
        )
    except NormalizationError:
        return None

    deadline = (
        time.monotonic() + effective_timeout if effective_timeout is not None else None
    )
    return query, ctx, deadline
