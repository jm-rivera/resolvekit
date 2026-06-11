"""Multi-pack pipeline runner for cross-domain resolution."""

from __future__ import annotations

import contextlib
import time
import traceback
from collections.abc import Iterator
from datetime import date
from itertools import islice
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from resolvekit.core.engine.suggest_rank import SuggestCandidate

from resolvekit.core.engine.interfaces import (
    _TIMEOUT_RESULT,
    ConfidenceBand,
    PipelineResult,
)
from resolvekit.core.engine.router import Router
from resolvekit.core.engine.runner import PipelineRunner
from resolvekit.core.engine.tier_utils import match_tier_rank
from resolvekit.core.explain import NullTraceSink, TraceSink
from resolvekit.core.explain.events import EventType, TraceEvent
from resolvekit.core.linking import BaseNormalizer, Normalizer
from resolvekit.core.model import (
    Candidate,
    CandidateSummary,
    EntityRecord,
    Query,
    ReasonCode,
    RefinementHint,
    ResolutionContext,
    ResolutionResult,
    ResolutionStatus,
)
from resolvekit.core.registry import DomainPack
from resolvekit.core.store import EntityStore
from resolvekit.core.store.store_view import StoreView
from resolvekit.core.util.normalization import NormalizationError, TextNormalizer

# Cross-pack ambiguity threshold - when top results from different packs
# are within this gap, we return AMBIGUOUS
CROSS_PACK_AMBIGUITY_GAP: Final[float] = 0.1

# Maximum candidates to take from each pack when interleaving
MAX_CANDIDATES_PER_PACK: Final[int] = 3

# Maximum total candidates to return in ambiguous cross-pack results
MAX_AMBIGUOUS_CANDIDATES: Final[int] = 5


class MultiPackRunner:
    """Orchestrates multi-domain resolution.

    1. Routes query to target pack(s)
    2. Runs each pack's pipeline
    3. Merges results across packs
    4. Returns best result or AMBIGUOUS
    """

    def __init__(
        self,
        router: Router,
        packs: dict[str, DomainPack],
        stores: dict[str, EntityStore],
        trace_sink: TraceSink | None = None,
        budget_per_pack: int = 20,
        pack_normalizers: dict[str, TextNormalizer] | None = None,
        pack_code_normalizers: dict[str, Normalizer] | None = None,
    ) -> None:
        """Initialize MultiPackRunner.

        Args:
            router: Router to determine which packs to query
            packs: Mapping of pack_id to DomainPack instances
            stores: Mapping of pack_id to EntityStore instances
            trace_sink: Optional trace sink for event collection
            budget_per_pack: Maximum candidates per pack (default: 20)
            pack_normalizers: Per-pack text normalizers for domain-specific normalization
            pack_code_normalizers: Per-pack code normalizers (``merge_normalizer`` from
                each pack) used by ``normalize_code_value`` to match the builder's
                normalization at query time.

        Raises:
            ValueError: If a pack has no corresponding store configured
        """
        self._router = router
        self._packs = packs
        self._stores = stores
        self._trace = trace_sink or NullTraceSink()
        self._budget = budget_per_pack
        self._pack_normalizers = pack_normalizers or {}
        self._pack_code_normalizers: dict[str, Normalizer] = pack_code_normalizers or {}
        self._confidence_bands: dict[str, ConfidenceBand] = {}

        # Pre-build runners for each pack
        self._runners: dict[str, PipelineRunner] = {}
        for pack_id, pack in packs.items():
            if pack_id not in stores:
                raise ValueError(f"No store configured for pack '{pack_id}'")
            ordering_fn = getattr(pack, "candidate_ordering_key", None)
            hints = pack.routing_hints
            type_prefixes: frozenset[str] = (
                frozenset(hints.type_prefixes) if hints is not None else frozenset()
            )
            country_relation_prefixes: frozenset[str] = (
                frozenset(hints.country_relation_prefixes)
                if hints is not None
                else frozenset()
            )
            country_scoped_type_prefixes: frozenset[str] = (
                frozenset(hints.country_scoped_type_prefixes)
                if hints is not None
                else frozenset()
            )
            group_entity_types: frozenset[str] = getattr(
                pack, "group_entity_types", frozenset()
            )
            self._runners[pack_id] = PipelineRunner(
                trace_sink=self._trace,
                store=stores[pack_id],
                sources=pack.sources,
                constraints=pack.constraints,
                feature_extractor=pack.feature_extractor,
                scorer=pack.scorer,
                decision_policy=pack.decision_policy,
                config=pack.config,
                budget=self._budget,
                pack_id=pack_id,
                candidate_ordering_key=ordering_fn if callable(ordering_fn) else None,
                group_entity_types=group_entity_types,
                type_prefixes=type_prefixes,
                country_relation_prefixes=country_relation_prefixes,
                country_scoped_type_prefixes=country_scoped_type_prefixes,
            )
            scorer = pack.scorer
            if scorer is not None and scorer.confidence_band is not None:
                self._confidence_bands[pack_id] = scorer.confidence_band

        # Collect country-scoped type prefixes across all packs for refinement hints.
        # A COUNTRY refinement hint is only actionable for these types, so
        # non-country domains (e.g. org) are excluded.
        all_country_scoped_type_prefixes: set[str] = set()
        for pack in packs.values():
            h = pack.routing_hints
            if h is not None:
                all_country_scoped_type_prefixes.update(h.country_scoped_type_prefixes)
        self._all_country_scoped_type_prefixes: frozenset[str] = frozenset(
            all_country_scoped_type_prefixes
        )
        self._view = StoreView(list(self._stores.items()))

    def close(self) -> None:
        """Close all stores owned by this runner."""
        for store in self._stores.values():
            store.close()

    def apply_confidence_threshold(self, *, threshold: float) -> bool:
        """Set confidence_threshold on all sub-runner decision policies that support one.

        Args:
            threshold: New minimum calibrated score for RESOLVED results.

        Returns:
            True if at least one sub-runner updated its policy, False if none did
            (caller may wish to warn).
        """
        results = [
            runner.apply_confidence_threshold(threshold=threshold)
            for runner in self._runners.values()
        ]
        return any(results)

    @property
    def trace_sink(self) -> TraceSink:
        """Return the trace sink for event collection."""
        return self._trace

    @property
    def available_packs(self) -> frozenset[str]:
        """Return the set of valid pack IDs for explicit routing."""
        return frozenset(self._packs)

    def get_entity(self, entity_id: str) -> EntityRecord | None:
        """Fetch a fully hydrated entity record from any backing store."""
        return self._view.get_entity(entity_id)

    def normalize_code_value(
        self, system: str, value: str, *, pack_filter: frozenset[str] | None = None
    ) -> str:
        """Normalize *value* for *system* using the owning pack's code normalizer.

        Walks the in-scope packs (``pack_filter`` when provided, otherwise all
        loaded packs) and returns the normalization from the first pack whose
        ``available_code_systems`` declares *system*.  Falls back to
        ``BaseNormalizer().normalize_code`` when no pack owns the system.

        This mirrors how ``pack_normalizers`` wires the text normalizer through
        the runner — the code normalizer is resolved per-domain so that
        content transforms (e.g. DUNS dash-strip in ``OrgNormalizer``) are
        applied on the query side exactly as they were on the build side.

        Args:
            system: Code system name (e.g., ``"iso3"``, ``"duns"``).
            value: Raw query value.
            pack_filter: When set, restrict pack search to those pack IDs.

        Returns:
            Normalized code value ready for a single ``lookup_code`` call.
        """
        candidate_ids = (
            pack_filter if pack_filter is not None else frozenset(self._runners)
        )
        for pack_id in candidate_ids:
            runner = self._runners.get(pack_id)
            if runner is None:
                continue
            if system in runner.available_code_systems:
                normalizer = self._pack_code_normalizers.get(pack_id)
                if normalizer is not None:
                    return normalizer.normalize_code(system, value)
                # Pack owns the system but has no registered code normalizer —
                # fall through to the default below.
                break
        return BaseNormalizer().normalize_code(system, value)

    def lookup_code(
        self,
        system: str,
        value_norm: str,
        *,
        pack_filter: frozenset[str] | None = None,
    ) -> list[str]:
        """Look up entity IDs by code across all (or filtered) backing stores.

        Args:
            system: Code system name (e.g., "iso2").
            value_norm: Already-normalized lookup value.
            pack_filter: When set, restrict the lookup to those pack ids. None
                aggregates across every loaded pack (current behaviour).
        """
        return self._view.lookup_code(system, value_norm, pack_filter=pack_filter)

    def lookup_code_attributed(
        self,
        *,
        system: str,
        value_norm: str,
        pack_filter: frozenset[str] | None = None,
    ) -> list[tuple[str, str]]:
        """Return (pack_id, entity_id) pairs for a code lookup across stores.

        Deduplicates by entity_id; the first store (in load order) that holds a
        given entity supplies its pack attribution.
        """
        return self._view.lookup_code_attributed(
            system=system, value_norm=value_norm, pack_filter=pack_filter
        )

    def resolve(
        self,
        query: Query,
        context: ResolutionContext,
        *,
        trace_sink: TraceSink | None = None,
        deadline: float | None = None,
    ) -> ResolutionResult:
        """Resolve query across domain packs.

        Args:
            query: The resolution query
            context: Resolution context with hints and constraints
            trace_sink: Optional per-call trace sink (falls back to self._trace)
            deadline: Absolute monotonic deadline; returns ERROR/TIMEOUT if exceeded
                before entering a pack's runner.

        Returns:
            ResolutionResult with explicit status (RESOLVED, AMBIGUOUS, NO_MATCH, or ERROR)
        """
        return self._run(
            query, context, trace_sink=trace_sink, deadline=deadline
        ).result

    def resolve_detailed(
        self,
        query: Query,
        context: ResolutionContext,
        *,
        trace_sink: TraceSink | None = None,
        deadline: float | None = None,
    ) -> PipelineResult:
        """Resolve query across domain packs, returning full pipeline data.

        Args:
            query: The resolution query
            context: Resolution context with hints and constraints
            trace_sink: Optional per-call trace sink (falls back to self._trace)
            deadline: Absolute monotonic deadline; returns ERROR/TIMEOUT if exceeded
                before entering a pack's runner.

        Returns:
            PipelineResult with result and full candidate list
        """
        return self._run(query, context, trace_sink=trace_sink, deadline=deadline)

    def _run(
        self,
        query: Query,
        context: ResolutionContext,
        *,
        trace_sink: TraceSink | None = None,
        deadline: float | None = None,
    ) -> PipelineResult:
        """Internal implementation: run resolution and return a PipelineResult."""
        trace = trace_sink or self._trace
        try:
            decision = self._router.route(query, context)

            trace.emit(
                TraceEvent(
                    event_type=EventType.DECIDED,
                    source="router",
                    data={
                        "target_packs": decision.target_packs,
                        "confidence": decision.confidence,
                        "reason": decision.reason,
                    },
                )
            )

            results: dict[str, ResolutionResult] = {}
            candidates_by_pack: dict[str, list[Candidate]] = {}

            for pack_id in decision.target_packs:
                if deadline is not None and time.monotonic() >= deadline:
                    return PipelineResult(result=_TIMEOUT_RESULT, candidates=None)

                if pack_id not in self._runners:
                    trace.emit(
                        TraceEvent(
                            event_type=EventType.ERROR,
                            source="multi_runner",
                            data={
                                "error": f"Router returned unknown pack_id: {pack_id}"
                            },
                        )
                    )
                    continue

                # Re-normalize query for this pack if pack-specific normalizer exists
                pack_query = query
                if pack_id in self._pack_normalizers:
                    try:
                        normalized = self._pack_normalizers[
                            pack_id
                        ].normalize_with_original(query.raw_text)
                    except NormalizationError:
                        # The pack's normalizer emptied the input (e.g. a
                        # punctuation-only query like '.'): unmatchable in
                        # this pack, not a pipeline error.
                        continue
                    pack_query = Query(
                        raw_text=query.raw_text,
                        normalized=normalized,
                        domains=query.domains,
                    )

                runner = self._runners[pack_id]
                run_result = runner.resolve_detailed(
                    pack_query,
                    context,
                    trace_sink=trace,
                    deadline=deadline,
                )
                results[pack_id] = run_result.result
                if run_result.candidates:
                    candidates_by_pack[pack_id] = run_result.candidates

            merged_result, winning_pack_id = self._merge_results(
                results, trace, context
            )

            winning_candidates = self._find_winning_candidates(
                merged_result, candidates_by_pack
            )
            return PipelineResult(
                result=merged_result,
                candidates=winning_candidates,
                pack_id=winning_pack_id,
            )

        except Exception as e:
            trace.emit(
                TraceEvent(
                    event_type=EventType.ERROR,
                    data={
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "traceback": traceback.format_exc(),
                    },
                )
            )
            error_result = ResolutionResult(
                status=ResolutionStatus.ERROR,
                reasons=(ReasonCode.INTERNAL_ERROR,),
            )
            return PipelineResult(result=error_result, candidates=None)

    # ------------------------------------------------------------------
    # suggest_prefix — autocomplete path (bypasses resolution pipeline)
    # ------------------------------------------------------------------

    def suggest_prefix(
        self,
        *,
        query_norm: str,
        top_k: int,
        entity_type_prefixes: frozenset[str] | None = None,
        fuzzy: Literal["auto", "always", "never"] = "auto",
        deadline: float | None = None,
        pack_filter: frozenset[str] | None = None,
    ) -> list[SuggestCandidate]:
        """Return a ranked list of suggest candidates across all loaded packs.

        Fans out to each pack's ``PipelineRunner.suggest_prefix``, re-normalizing
        the query per pack (mirroring the resolve loop), then merges the results:
        deduplicates by entity_id (first-store-in-load-order wins attribution),
        sorts by ``suggest_rank.sort_key``, and truncates to ``top_k``.

        Each pack is asked for ``top_k * 3`` candidates so the merge has enough
        headroom to surface globally-top entries that might be ranked lower in
        their own pack.

        MUST NOT reuse ``_merge_results``, ``_normalize_confidence``, or
        ``_build_ambiguous_result`` — the cascade comparator is pack-agnostic.

        Args:
            query_norm: Already-normalized prefix (callers may supply the
                global-normalizer form; this method re-normalizes per pack).
            top_k: Maximum number of candidates to return.
            entity_type_prefixes: Optional entity type filter.
            fuzzy: Fuzzy policy propagated to each pack.
            deadline: Absolute ``time.monotonic()`` deadline; checks after each
                pack's fan-out and returns partial rather than raising.
            pack_filter: When set, only query packs whose ID is in this set
                (mirrors the resolve loop's domain routing).

        Returns:
            Sorted ``list[SuggestCandidate]``, at most ``top_k`` entries.
        """
        from resolvekit.core.engine.suggest_rank import sort_key

        pool_per_pack = top_k * 3

        # Collect candidates from all in-scope packs (load order preserved).
        all_candidates: list[SuggestCandidate] = []
        seen_entity_ids: set[str] = set()

        for pack_id, runner in self._runners.items():
            # Skip packs excluded by the domain/pack filter.
            if pack_filter is not None and pack_id not in pack_filter:
                continue

            if deadline is not None and time.monotonic() >= deadline:
                break

            # Re-normalize the query for this pack when a pack-specific
            # normalizer is registered (mirrors the resolve loop).
            pack_query_norm = query_norm
            if pack_id in self._pack_normalizers:
                with contextlib.suppress(Exception):
                    pack_query_norm = self._pack_normalizers[pack_id].normalize(
                        query_norm
                    )

            pack_cands = runner.suggest_prefix(
                query_norm=pack_query_norm,
                top_k=pool_per_pack,
                entity_type_prefixes=entity_type_prefixes,
                fuzzy=fuzzy,
                deadline=deadline,
            )

            for c in pack_cands:
                if c.entity_id not in seen_entity_ids:
                    seen_entity_ids.add(c.entity_id)
                    all_candidates.append(c)

        all_candidates.sort(key=sort_key)
        return all_candidates[:top_k]

    def _find_winning_candidates(
        self,
        merged_result: ResolutionResult,
        candidates_by_pack: dict[str, list[Candidate]],
    ) -> list[Candidate] | None:
        """Find candidates from the pack containing the winning entity.

        For RESOLVED results: returns candidates from the pack containing the winner.
        For AMBIGUOUS results: builds a lookup across all packs and returns candidates
        that match merged_result.candidates in order.
        """
        if merged_result.entity_id:
            # RESOLVED case - find candidates from winning pack
            for cands in candidates_by_pack.values():
                if any(c.entity_id == merged_result.entity_id for c in cands):
                    return cands
        elif merged_result.candidates and candidates_by_pack:
            # AMBIGUOUS case - match merged_result.candidates across all packs
            candidate_lookup = {
                c.entity_id: c for cands in candidates_by_pack.values() for c in cands
            }
            matched = [
                candidate_lookup[c.entity_id]
                for c in merged_result.candidates
                if c.entity_id in candidate_lookup
            ]
            return matched if matched else None
        return None

    def _merge_results(
        self,
        results: dict[str, ResolutionResult],
        trace: TraceSink,
        context: ResolutionContext,
    ) -> tuple[ResolutionResult, str | None]:
        """Merge results from multiple packs.

        Args:
            results: Mapping of pack_id to resolution results
            trace: Trace sink for event collection

        Returns:
            Tuple of (merged ResolutionResult, winning pack_id or None)
        """
        if not results:
            return (
                ResolutionResult(
                    status=ResolutionStatus.NO_MATCH,
                    reasons=(ReasonCode.NO_CANDIDATES,),
                ),
                None,
            )

        successful_results = self._filter_successful_results(results, trace)

        # If all packs failed, return first error
        if not successful_results:
            first_pack_id = next(iter(results.keys()))
            return results[first_pack_id], first_pack_id

        # Single pack → return directly
        if len(successful_results) == 1:
            pack_id = next(iter(successful_results.keys()))
            return successful_results[pack_id], pack_id

        return self._merge_multiple_results(successful_results, context)

    def _filter_successful_results(
        self,
        results: dict[str, ResolutionResult],
        trace: TraceSink,
    ) -> dict[str, ResolutionResult]:
        """Filter out ERROR results and emit trace for failures.

        Args:
            results: All results from pack runs
            trace: Trace sink for event collection

        Returns:
            Dict containing only non-ERROR results
        """
        successful = {
            pack_id: r
            for pack_id, r in results.items()
            if r.status != ResolutionStatus.ERROR
        }
        failed_packs = [
            pack_id
            for pack_id, r in results.items()
            if r.status == ResolutionStatus.ERROR
        ]

        if failed_packs:
            trace.emit(
                TraceEvent(
                    event_type=EventType.ERROR,
                    source="multi_runner",
                    data={"failed_packs": failed_packs},
                )
            )

        return successful

    def _merge_multiple_results(
        self,
        successful_results: dict[str, ResolutionResult],
        context: ResolutionContext,
    ) -> tuple[ResolutionResult, str | None]:
        """Merge results when multiple packs succeeded.

        Args:
            successful_results: Results from packs that didn't error

        Returns:
            Tuple of (best result or AMBIGUOUS, winning pack_id or None)
        """
        resolved_results = [
            (pack_id, r)
            for pack_id, r in successful_results.items()
            if r.status == ResolutionStatus.RESOLVED
        ]

        if not resolved_results:
            return self._find_best_non_resolved(successful_results, context)

        if len(resolved_results) == 1:
            pack_id, result = resolved_results[0]
            # If any other pack is AMBIGUOUS and its top candidate normalizes
            # at or above the RESOLVED pack's normalized confidence, the query
            # is genuinely cross-domain ambiguous (e.g. "Republic of China"
            # resolves as a geo entity in both packs but the org match is a
            # containment hit on a longer name).  Merge them as AMBIGUOUS so
            # the caller sees all candidates rather than the weaker org hit.
            ambiguous_results = [
                (apid, ar)
                for apid, ar in successful_results.items()
                if ar.status == ResolutionStatus.AMBIGUOUS and ar.candidates
            ]
            resolved_norm = self._normalize_confidence(
                pack_id, result.confidence or 0.0
            )
            for apid, ar in ambiguous_results:
                top_amb_conf = ar.candidates[0].confidence or 0.0
                if self._normalize_confidence(apid, top_amb_conf) >= resolved_norm:
                    all_results = [*resolved_results, (apid, ar)]
                    return self._build_ambiguous_result(all_results, context), None
            return result, pack_id

        return self._compare_resolved_results(resolved_results, context)

    def _find_best_non_resolved(
        self,
        successful_results: dict[str, ResolutionResult],
        context: ResolutionContext,
    ) -> tuple[ResolutionResult, str | None]:
        """Find best result when no pack resolved successfully.

        Status priority: AMBIGUOUS > NO_MATCH > any other.

        Args:
            successful_results: Results from packs that didn't error

        Returns:
            Tuple of (best non-resolved result, pack_id or None for AMBIGUOUS)
        """
        # Prefer AMBIGUOUS over NO_MATCH (user can see options)
        status_priority = (ResolutionStatus.AMBIGUOUS, ResolutionStatus.NO_MATCH)

        ambiguous_results = [
            (pack_id, result)
            for pack_id, result in successful_results.items()
            if result.status == ResolutionStatus.AMBIGUOUS
        ]
        if len(ambiguous_results) > 1:
            return self._build_ambiguous_result(ambiguous_results, context), None

        for status in status_priority:
            for pack_id, result in successful_results.items():
                if result.status == status:
                    # For AMBIGUOUS, pack_id is None (cross-pack)
                    return (
                        result,
                        None if status == ResolutionStatus.AMBIGUOUS else pack_id,
                    )

        # Fallback to first available result
        first_pack_id = next(iter(successful_results.keys()))
        return successful_results[first_pack_id], first_pack_id

    def _normalize_confidence(self, pack_id: str, raw_confidence: float) -> float:
        """Normalize pack-specific confidence to a comparable scale using declared bands."""
        band = self._confidence_bands.get(pack_id)
        if band is None:
            return raw_confidence  # No band declared — use raw score

        # Piecewise linear normalization: map pack-specific bands to standard ranges.
        # Each tuple is (floor_threshold, target_start, target_size, ceiling).
        segments = [
            (band.high_confidence_floor, 0.85, 0.15, 1.0),
            (band.medium_confidence_floor, 0.6, 0.25, band.high_confidence_floor),
            (band.low_confidence_floor, 0.3, 0.3, band.medium_confidence_floor),
        ]

        for floor, target_start, target_size, ceiling in segments:
            if raw_confidence >= floor:
                range_size = ceiling - floor
                t = (raw_confidence - floor) / range_size if range_size > 0 else 0
                return target_start + t * target_size

        # Below low floor
        if band.low_confidence_floor > 0:
            return raw_confidence * (0.3 / band.low_confidence_floor)
        return 0.0

    def _result_sort_key(self, item: tuple[str, ResolutionResult]) -> tuple[int, float]:
        """Sort key for results: tier-first, then normalized confidence."""
        pack_id, result = item
        return (
            match_tier_rank(result.match_tier),
            self._normalize_confidence(pack_id, result.confidence or 0.0),
        )

    def _compare_resolved_results(
        self,
        resolved_results: list[tuple[str, ResolutionResult]],
        context: ResolutionContext,
    ) -> tuple[ResolutionResult, str | None]:
        """Compare multiple resolved results and return best or AMBIGUOUS.

        Args:
            resolved_results: List of (pack_id, result) tuples for resolved packs

        Returns:
            Tuple of (best result or AMBIGUOUS, winning pack_id or None)
        """
        ranked_results = sorted(
            resolved_results, key=self._result_sort_key, reverse=True
        )
        top_pack_id, top_result = ranked_results[0]
        runner_up_pack_id, runner_up_result = ranked_results[1]

        top_tier_rank = match_tier_rank(top_result.match_tier)
        runner_up_tier_rank = match_tier_rank(runner_up_result.match_tier)
        if top_tier_rank > runner_up_tier_rank:
            return top_result, top_pack_id

        top_confidence = self._normalize_confidence(
            top_pack_id, top_result.confidence or 0.0
        )
        runner_up_confidence = self._normalize_confidence(
            runner_up_pack_id, runner_up_result.confidence or 0.0
        )
        if (top_confidence - runner_up_confidence) < CROSS_PACK_AMBIGUITY_GAP:
            return self._build_ambiguous_result(ranked_results, context), None

        return top_result, top_pack_id

    def _build_ambiguous_result(
        self,
        resolved_results: list[tuple[str, ResolutionResult]],
        context: ResolutionContext,
    ) -> ResolutionResult:
        """Build ambiguous result by interleaving candidates from multiple packs.

        Candidates are round-robin interleaved from each pack (sorted by normalized
        confidence), taking up to MAX_CANDIDATES_PER_PACK from each pack.

        Args:
            resolved_results: List of (pack_id, result) tuples

        Returns:
            AMBIGUOUS result with interleaved candidates
        """
        sorted_results = sorted(
            resolved_results, key=self._result_sort_key, reverse=True
        )

        # Interleave candidates round-robin style
        interleaved = list(
            islice(
                self._interleave_candidates(sorted_results),
                MAX_AMBIGUOUS_CANDIDATES,
            )
        )

        hints: list[RefinementHint] = []
        if not context.entity_types:
            hints.append(RefinementHint.ENTITY_TYPES)
        if not context.country and self._any_candidate_matches_country_scoped_prefix(
            interleaved
        ):
            hints.append(RefinementHint.COUNTRY)

        top_tier = max(
            (result.match_tier for _, result in sorted_results),
            key=match_tier_rank,
            default=None,
        )

        return ResolutionResult(
            status=ResolutionStatus.AMBIGUOUS,
            candidates=tuple(interleaved),
            match_tier=top_tier,
            reasons=(ReasonCode.AMBIGUOUS_DOMAIN_COLLISION,),
            refinement_hints=tuple(hints),
        )

    def _any_candidate_matches_country_scoped_prefix(
        self, candidates: list[CandidateSummary]
    ) -> bool:
        """Return True when any candidate's entity_type is country-scoped.

        Uses the aggregate ``_all_country_scoped_type_prefixes`` across all loaded
        packs, so a COUNTRY refinement hint is only offered when at least one
        candidate belongs to a type for which country context is actionable.
        """
        if not self._all_country_scoped_type_prefixes:
            return False
        for candidate in candidates:
            if not candidate.entity_type:
                continue
            for prefix in self._all_country_scoped_type_prefixes:
                if candidate.entity_type.startswith(f"{prefix}.") or (
                    candidate.entity_type == prefix
                ):
                    return True
        return False

    def _interleave_candidates(
        self, sorted_results: list[tuple[str, ResolutionResult]]
    ) -> Iterator[CandidateSummary]:
        """Yield candidates round-robin from each pack.

        Takes up to MAX_CANDIDATES_PER_PACK from each result set.
        """
        for position in range(MAX_CANDIDATES_PER_PACK):
            for _, result in sorted_results:
                if position < len(result.candidates):
                    yield result.candidates[position]

    # -------------------------------------------------------------------------
    # ResolverBackend introspection methods
    # -------------------------------------------------------------------------

    @property
    def available_entity_types(self) -> frozenset[str]:
        """Return all entity type prefixes declared across loaded packs."""
        types: set[str] = set()
        for pack in self._packs.values():
            hints = pack.routing_hints
            if hints is not None:
                types.update(hints.type_prefixes)
        return frozenset(types)

    @property
    def available_code_systems(self) -> frozenset[str]:
        """Return all code systems available across loaded stores."""
        return self._view.available_code_systems()

    @property
    def available_group_types(self) -> frozenset[str]:
        """Return all group entity types declared across loaded packs."""
        types: set[str] = set()
        for pack in self._packs.values():
            types.update(getattr(pack, "group_entity_types", frozenset()))
        return frozenset(types)

    def get_reverse_relations(
        self,
        *,
        entity_id: str,
        relation_type: str,
        as_of: date | None = None,
    ) -> list[str]:
        """Return entity IDs that have a relation of relation_type pointing to entity_id.

        Aggregates across all loaded stores and returns a sorted, deduplicated list.

        Args:
            entity_id: Target entity ID (the group or subject of the relation).
            relation_type: Relation type to filter by (e.g. "member_of").
            as_of: When provided, only includes relations active on that date.
        """
        return sorted(
            self._view.get_reverse_relations(
                entity_id=entity_id, relation_type=relation_type, as_of=as_of
            )
        )

    def get_relations_as_of(
        self,
        *,
        entity_id: str,
        relation_type: str,
        as_of: date,
    ) -> frozenset[str]:
        """Return the set of target entity IDs for a relation active on as_of.

        Unions results across all loaded stores.

        Args:
            entity_id: Source entity ID.
            relation_type: Relation type to filter by.
            as_of: Reference date for the temporal filter.
        """
        return self._view.get_relations_as_of(
            entity_id=entity_id, relation_type=relation_type, as_of=as_of
        )

    def list_entities_by_type(
        self,
        *,
        entity_type: str,
    ) -> list[EntityRecord]:
        """Return all entities with the given entity_type across loaded stores.

        Args:
            entity_type: Entity type string to filter by (e.g. "org.igo").
        """
        return self._view.list_entities_by_type(entity_type=entity_type)

    def get_pack_group_types(
        self,
        *,
        pack_id: str,
    ) -> frozenset[str]:
        """Return the group entity types declared by the given pack.

        Returns an empty frozenset when the pack is not loaded or declares none.

        Args:
            pack_id: Pack identifier (e.g. "geo", "org").
        """
        pack = self._packs.get(pack_id)
        if pack is None:
            return frozenset()
        return getattr(pack, "group_entity_types", frozenset())

    def is_snapshot_entity(
        self,
        *,
        entity_id: str,
    ) -> bool:
        """Return True when any store reports attributes['snapshot'] = True.

        Args:
            entity_id: Entity ID to check.
        """
        return self._view.is_snapshot_entity(entity_id=entity_id)

    def lookup_pack_id(self) -> str | None:
        """Return None — multi-pack runners do not resolve to a single pack ID."""
        return None

    def store_for_domain(self, domain: str) -> EntityStore:
        """Return the EntityStore for *domain*.

        Checks for an exact key match first, then falls back to the first store
        whose pack ID starts with *domain* (e.g. ``"geo"`` matches ``"geo_v2"``).

        Args:
            domain: Domain pack ID (e.g. ``"geo"`` or ``"org"``).

        Raises:
            ValueError: If no store is found for the given domain.
        """
        if domain in self._stores:
            return self._stores[domain]
        for pack_id, store in self._stores.items():
            if pack_id.startswith(domain):
                return store
        raise ValueError(
            f"Cannot find EntityStore for domain '{domain}'. "
            f"Available packs: {list(self._stores)}"
        )

    def lookup_name_exact(
        self,
        *,
        value: str,
        pack_filter: frozenset[str] | None = None,
    ) -> list[tuple[str, str]]:
        """Return (pack_id, entity_id) pairs matching the given name exactly.

        Fans across all (or filtered) stores and deduplicates by entity_id,
        preserving pack attribution for the first store that reports each entity.

        Args:
            value: Normalized name value to look up.
            pack_filter: When set, restrict lookup to those pack IDs.
        """
        return self._view.lookup_name_exact(value=value, pack_filter=pack_filter)
