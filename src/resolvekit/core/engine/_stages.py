"""Pipeline stage functions for the resolution process.

Each function in this module corresponds to a logical phase of the resolution
pipeline.  They are module-level free functions that receive all state they
need as explicit arguments, making them directly callable from tests without
constructing a full PipelineRunner.
"""

import time

from resolvekit.core.engine.config import PipelineConfig
from resolvekit.core.engine.interfaces import (
    CandidateSource,
    Constraint,
    FeatureExtractor,
    Scorer,
)
from resolvekit.core.engine.tier_utils import (
    DEFAULT_FALLBACK_SCORE,
    DEFAULT_TOP_K_RESULTS,
    build_candidate_summary,
)
from resolvekit.core.explain import TraceSink
from resolvekit.core.explain.events import EventType, TraceEvent
from resolvekit.core.model import (
    Candidate,
    CandidateEvidence,
    GenerationContext,
    MatchTier,
    Query,
    ReasonCode,
    ResolutionContext,
    ResolutionResult,
    ResolutionStatus,
    RetrievalSummary,
    ScoreSummary,
)
from resolvekit.core.store import EntityStore

# Type aliases for readability in function signatures
type _EvidenceByEntity = dict[str, list[CandidateEvidence]]


def run_primary_sources(
    query: Query,
    context: ResolutionContext,
    all_evidence: _EvidenceByEntity,
    trace: TraceSink,
    *,
    sources: list[CandidateSource],
    store: EntityStore,
    budget: int,
    config: PipelineConfig | None,
    deadline: float | None = None,
) -> None:
    """Run sources that don't need existing candidates.

    Accumulates evidence into ``all_evidence`` (modified in place).  Skips reranker
    sources (``requires_existing_candidates=True``), applies the fuzzy-skip guard,
    and honours generation-phase stop conditions.

    Args:
        query: The resolution query.
        context: Resolution context.
        all_evidence: Accumulator for evidence, grouped by entity_id.
        trace: Trace sink for event collection.
        sources: Candidate sources to iterate.
        store: EntityStore to pass to each source.
        budget: Maximum candidates budget passed to GenerationContext.
        config: PipelineConfig instance (or None) for stop-condition evaluation.
        deadline: Absolute monotonic deadline; source is skipped if exceeded.
    """
    for source in sources:
        if deadline is not None and time.monotonic() >= deadline:
            break
        if source.requires_existing_candidates:
            continue
        if should_skip_source(source, all_evidence):
            continue
        ctx = GenerationContext(
            query=query,
            context=context,
            store=store,
            budget=budget,
            trace=trace,
            deadline=deadline,
        )
        evidence_list = source.generate(ctx)

        accumulate_evidence(evidence_list, all_evidence)

        if should_stop_generation(source.name, all_evidence, config=config):
            break


def should_skip_source(
    source: CandidateSource,
    all_evidence: _EvidenceByEntity,
) -> bool:
    """Skip a primary source when prior evidence makes it redundant.

    Bypass per-word fuzzy retrieval when whole-query SymSpell already promoted
    a single entity to exact_name tier — running word-level correction next
    never finds a better match than that single hit, but it pays the cost of
    N SymSpell lookups (N = words in query).  Downstream rerankers (FuzzySource)
    still run, so scoring features are unaffected.

    Uses the source's declared ``tier`` property (``MatchTier.FUZZY`` for
    fuzzy-retrieval sources) and per-evidence ``ev.match_tier`` (``EXACT_NAME``
    for synthetic symspell-exact-name evidence) instead of source-name substrings.
    """
    if source.tier == MatchTier.FUZZY:
        promoted_entities: set[str] = set()
        for entity_id, ev_list in all_evidence.items():
            for ev in ev_list:
                if ev.match_tier == MatchTier.EXACT_NAME:
                    promoted_entities.add(entity_id)
                    break
        if len(promoted_entities) == 1:
            return True
    return False


def run_reranker_sources(
    query: Query,
    context: ResolutionContext,
    candidates: list[Candidate],
    trace: TraceSink,
    *,
    sources: list[CandidateSource],
    store: EntityStore,
    budget: int,
    deadline: float | None = None,
) -> None:
    """Run sources that need existing candidates (fuzzy rerankers).

    Adds evidence to existing candidates; does NOT re-merge (no new candidates
    are created).

    Args:
        query: The resolution query.
        context: Resolution context.
        candidates: Existing candidates to augment (modified in place).
        trace: Trace sink for event collection.
        sources: Candidate sources to iterate.
        store: EntityStore to pass to each source.
        budget: Maximum candidates budget passed to GenerationContext.
        deadline: Absolute monotonic deadline; source is skipped if exceeded.
    """
    for source in sources:
        if deadline is not None and time.monotonic() >= deadline:
            break
        if not source.requires_existing_candidates:
            continue
        ctx = GenerationContext(
            query=query,
            context=context,
            store=store,
            budget=budget,
            trace=trace,
            existing_candidates=candidates,
            deadline=deadline,
        )
        evidence_list = source.generate(ctx)

        add_evidence_to_candidates(evidence_list, candidates)


def apply_constraints(
    query: Query,
    context: ResolutionContext,
    candidates: list[Candidate],
    trace: TraceSink,
    *,
    constraints: list[Constraint],
    store: EntityStore,
    deadline: float | None = None,
) -> list[Candidate]:
    """Apply all constraints to filter candidates.

    Args:
        query: The resolution query.
        context: Resolution context.
        candidates: Candidates to filter.
        trace: Trace sink for event collection.
        constraints: Constraint instances to apply in order.
        store: EntityStore to pass to each constraint.
        deadline: Absolute monotonic deadline; constraint is skipped if exceeded.

    Returns:
        Filtered list of candidates.
    """
    for constraint in constraints:
        if deadline is not None and time.monotonic() >= deadline:
            break
        candidates = constraint.apply(
            query=query,
            context=context,
            candidates=candidates,
            store=store,
            trace=trace,
        )

    return candidates


def score_candidates(
    query: Query,
    context: ResolutionContext,
    candidates: list[Candidate],
    trace: TraceSink,
    *,
    store: EntityStore,
    feature_extractor: FeatureExtractor | None,
    scorer: Scorer | None,
    deadline: float | None = None,
) -> None:
    """Extract features and score each candidate.

    Args:
        query: The resolution query.
        context: Resolution context.
        candidates: Candidates to score (modified in place).
        trace: Trace sink for event collection.
        store: EntityStore to pass to the feature extractor.
        feature_extractor: FeatureExtractor instance, or None.
        scorer: Scorer instance, or None.
        deadline: Absolute monotonic deadline; scoring stops if exceeded
            (checked every 8 candidates).
    """
    for i, candidate in enumerate(candidates):
        if i % 8 == 0 and deadline is not None and time.monotonic() >= deadline:
            break
        if feature_extractor:
            features = feature_extractor.extract(
                query=query,
                context=context,
                candidate=candidate,
                store=store,
                trace=trace,
            )
            candidate.features = features

        if scorer and candidate.features is not None:
            raw_score = scorer.score(candidate.features, candidate.retrieval)
            calibrated = scorer.calibrate(raw_score, query, candidate)
            calibrated = min(max(calibrated, 0.0), 1.0)
        else:
            raw_score = (
                candidate.retrieval.best_raw_score
                if candidate.retrieval.best_raw_score is not None
                else DEFAULT_FALLBACK_SCORE
            )
            calibrated = min(max(raw_score, 0.0), 1.0)

        candidate.scores = ScoreSummary(
            raw_score=raw_score,
            calibrated_score=calibrated,
        )
        trace.emit(
            TraceEvent(
                event_type=EventType.SCORED,
                data={"entity_id": candidate.entity_id, "score": calibrated},
            )
        )


def accumulate_evidence(
    evidence_list: list[CandidateEvidence],
    all_evidence: _EvidenceByEntity,
) -> None:
    """Add evidence entries to the accumulator dict, grouped by entity_id.

    Args:
        evidence_list: New evidence to add.
        all_evidence: Accumulator dict (modified in place).
    """
    for ev in evidence_list:
        all_evidence[ev.entity_id].append(ev)


def add_evidence_to_candidates(
    evidence_list: list[CandidateEvidence],
    candidates: list[Candidate],
) -> None:
    """Add new evidence to existing candidates without re-merging.

    Preserves constraint outcomes and features already computed.  Evidence for
    unknown entity IDs (not in ``candidates``) is silently dropped.

    Args:
        evidence_list: New evidence from reranker sources.
        candidates: Existing candidates to update.
    """
    candidate_map = {c.entity_id: c for c in candidates}

    for ev in evidence_list:
        candidate = candidate_map.get(ev.entity_id)
        if candidate is None:
            continue

        candidate.sources = [*candidate.sources, ev]
        merged_signals = {**candidate.retrieval.signals, **ev.signals}

        # Check if new evidence has better score
        current_best = candidate.retrieval.best_raw_score or 0
        is_better = ev.raw_score is not None and ev.raw_score > current_best

        candidate.retrieval = RetrievalSummary(
            best_source=ev.source_name
            if is_better
            else candidate.retrieval.best_source,
            best_rank=ev.rank if is_better else candidate.retrieval.best_rank,
            best_raw_score=ev.raw_score
            if is_better
            else candidate.retrieval.best_raw_score,
            signals=merged_signals,
        )


def merge_candidates(
    evidence_by_entity: _EvidenceByEntity,
) -> list[Candidate]:
    """Merge evidence into Candidate objects.

    Creates candidates with placeholder scores — real scoring happens in the
    main pipeline after feature extraction.

    Args:
        evidence_by_entity: Evidence grouped by entity_id.

    Returns:
        List of Candidate objects.
    """
    candidates = []

    for entity_id, evidence_list in evidence_by_entity.items():
        # Find best evidence
        best = max(evidence_list, key=lambda e: e.raw_score or 0)

        # Aggregate signals from all evidence
        aggregated_signals: dict[str, float] = {}
        for ev in evidence_list:
            aggregated_signals.update(ev.signals)

        # Create retrieval summary
        retrieval = RetrievalSummary(
            best_source=best.source_name,
            best_rank=best.rank,
            best_raw_score=best.raw_score,
            signals=aggregated_signals,
        )

        # Placeholder scores - will be overwritten during scoring step
        placeholder_score = best.raw_score or DEFAULT_FALLBACK_SCORE

        candidates.append(
            Candidate(
                entity_id=entity_id,
                sources=evidence_list,
                retrieval=retrieval,
                scores=ScoreSummary(
                    raw_score=placeholder_score,
                    calibrated_score=min(placeholder_score, 1.0),
                ),
            )
        )

    return candidates


def should_stop_generation(
    source_name: str,
    evidence_by_entity: _EvidenceByEntity,
    *,
    config: PipelineConfig | None,
) -> bool:
    """Check generation-phase stop conditions against current evidence.

    Only evaluates conditions with phase="generation".  These use raw scores
    since calibrated scores aren't available yet.

    Args:
        source_name: Name of the source that just ran.
        evidence_by_entity: Current accumulated evidence.
        config: PipelineConfig instance, or None (returns False when None).

    Returns:
        True if pipeline should stop generating candidates.
    """
    if not config:
        return False

    candidate_count = len(evidence_by_entity)
    best_raw_score = 0.0
    for evidence_list in evidence_by_entity.values():
        for ev in evidence_list:
            if ev.raw_score is not None and ev.raw_score > best_raw_score:
                best_raw_score = ev.raw_score

    for cond in config.stop_conditions:
        # Only check generation-phase conditions here
        if cond.phase != "generation":
            continue
        if cond.source_name and cond.source_name != source_name:
            continue
        if cond.min_candidates is not None and candidate_count < cond.min_candidates:
            continue
        if cond.max_candidates is not None and candidate_count > cond.max_candidates:
            continue
        if cond.min_confidence is not None and best_raw_score < cond.min_confidence:
            continue
        return True
    return False


def check_post_scoring_stop(
    candidates: list[Candidate],
    *,
    config: PipelineConfig | None,
    source_reason_codes: dict[str, ReasonCode],
) -> ResolutionResult | None:
    """Check post-scoring stop conditions with calibrated scores.

    Evaluates conditions with phase="post_scoring" (the default).  These use
    calibrated scores after full pipeline processing.

    IMPORTANT: Only auto-resolves if min_confidence is explicitly set.  Conditions
    without min_confidence fall through to decision policy to avoid bypassing
    threshold/ambiguity checks.

    Args:
        candidates: Scored and sorted candidates.
        config: PipelineConfig instance, or None (returns None when None).
        source_reason_codes: Mapping from source name to ReasonCode for the decision.

    Returns:
        ResolutionResult if a stop condition triggers, None otherwise.
    """
    if not config or not candidates:
        return None

    top = candidates[0]  # Already sorted by calibrated_score
    candidate_count = len(candidates)

    for cond in config.stop_conditions:
        # Only check post-scoring conditions here
        if cond.phase != "post_scoring":
            continue
        # Only auto-resolve if min_confidence is explicitly set.
        # Without it, fall through to decision policy to apply
        # threshold/ambiguity checks.
        if cond.min_confidence is None:
            continue
        if cond.min_candidates is not None and candidate_count < cond.min_candidates:
            continue
        if cond.max_candidates is not None and candidate_count > cond.max_candidates:
            continue
        if top.scores.calibrated_score < cond.min_confidence:
            continue

        # All conditions met (including explicit min_confidence) - return RESOLVED
        reason = source_reason_codes.get(
            top.retrieval.best_source, ReasonCode.FTS_MATCH
        )
        return ResolutionResult(
            status=ResolutionStatus.RESOLVED,
            entity_id=top.entity_id,
            confidence=top.scores.calibrated_score,
            candidates=[
                build_candidate_summary(c) for c in candidates[:DEFAULT_TOP_K_RESULTS]
            ],
            reasons=[reason],
        )
    return None
