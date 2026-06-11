"""Shared threshold-based decision policy base for all domain packs."""

from resolvekit.core.engine.interfaces import DecisionPolicy
from resolvekit.core.engine.tier_utils import (
    DEFAULT_TOP_K_RESULTS,
    build_candidate_summary,
)
from resolvekit.core.explain import TraceSink
from resolvekit.core.explain.events import EventType, TraceEvent
from resolvekit.core.model import (
    Candidate,
    CandidateSummary,
    MatchTier,
    Query,
    ReasonCode,
    ResolutionContext,
    ResolutionResult,
    ResolutionStatus,
)

# Hand-authored tier → reason mapping.  Non-injective REASON_TO_MATCH_TIER in tier_utils
# makes the inverse unreliable; this table is authoritative for _resolved_reason.
TIER_TO_REASON: dict[MatchTier, ReasonCode] = {
    MatchTier.EXACT_CODE: ReasonCode.EXACT_CODE_MATCH,
    MatchTier.EXACT_NAME: ReasonCode.EXACT_NAME_MATCH,
    MatchTier.ACRONYM: ReasonCode.ACRONYM_MATCH,
    MatchTier.FUZZY: ReasonCode.FUZZY_MATCH,
    MatchTier.FTS: ReasonCode.FTS_MATCH,
    MatchTier.FALLBACK: ReasonCode.FTS_MATCH,
}

# Tiers at or below the FTS floor: NOT early-return cases in _resolved_reason
# (they fall through to the FTS_MATCH default, matching both packs today).
_FLOOR_TIERS: frozenset[MatchTier] = frozenset({MatchTier.FTS, MatchTier.FALLBACK})

# Source-name fallback tokens — used ONLY for un-stamped evidence (match_tier is None).
# No "fts" token: un-matched names fall to the FTS_MATCH default (preserves both packs).
_SOURCE_NAME_REASON_TOKENS: tuple[tuple[str, ReasonCode], ...] = (
    ("exact_code", ReasonCode.EXACT_CODE_MATCH),
    ("exact_name", ReasonCode.EXACT_NAME_MATCH),
    ("acronym", ReasonCode.ACRONYM_MATCH),
    ("fuzzy", ReasonCode.FUZZY_MATCH),
)


class ThresholdDecisionPolicy(DecisionPolicy):
    """Parametrized threshold-and-gap decision policy.

    Subclasses override hooks to inject domain-specific behaviour without
    duplicating the threshold/gap dispatch loop.

    Args:
        confidence_threshold: Minimum calibrated score to consider RESOLVED.
        min_gap: Minimum gap between top-1 and top-2 scores to consider a
            clear winner.
        gap_inclusive: When True, the clear-winner branch uses ``>=``; the
            ambiguous branch uses ``<``.  When False, the resolve branch
            uses ``>`` (strict) and the ambiguous branch uses ``<=``.
        max_candidates: Maximum number of candidate summaries to include in
            the returned result.
    """

    def __init__(
        self,
        *,
        confidence_threshold: float,
        min_gap: float,
        gap_inclusive: bool = False,
        max_candidates: int = DEFAULT_TOP_K_RESULTS,
    ) -> None:
        self._confidence_threshold = confidence_threshold
        self._min_gap = min_gap
        self._gap_inclusive = gap_inclusive
        self._max_candidates = max_candidates

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def decide(
        self,
        query: Query,
        context: ResolutionContext,
        candidates: list[Candidate],
        trace: TraceSink,
    ) -> ResolutionResult:
        """Make the final resolution decision.

        Decision flow:
        1. Empty candidates → NO_MATCH / NO_CANDIDATES.
        2. Sort by calibrated score (descending).
        3. ``_early_accept`` hook — if it returns a reason, RESOLVED immediately.
        4. Top score < threshold → NO_MATCH / BELOW_CONFIDENCE_THRESHOLD.
        5. Gap check (``>= min_gap`` when gap_inclusive else ``> min_gap``).
           Single-candidate case treated as clear winner when score ≥ threshold.
        6. ``_tiebreak`` hook — if it returns a winner, RESOLVED.
        7. RESOLVED via ``_resolved_reason`` hook.
        """
        if not candidates:
            return ResolutionResult(
                status=ResolutionStatus.NO_MATCH,
                reasons=[ReasonCode.NO_CANDIDATES],
            )

        candidates = sorted(
            candidates, key=lambda c: c.scores.calibrated_score, reverse=True
        )
        top = candidates[0]
        top_score = top.scores.calibrated_score

        # Step 3: early-accept hook
        early_reason = self._early_accept(top, candidates)
        if early_reason is not None:
            result = self._make_resolved(top, candidates, early_reason)
            trace.emit(
                TraceEvent(
                    event_type=EventType.DECIDED,
                    data={"status": result.status.value, "reason": early_reason.value},
                )
            )
            return result

        # Step 4: threshold check — attach calibrated score so callers can
        # distinguish a near-miss ("NO_MATCH, confidence=0.66") from a true
        # no-candidate ("NO_MATCH, confidence=None").
        if top_score < self._confidence_threshold:
            result = ResolutionResult(
                status=ResolutionStatus.NO_MATCH,
                confidence=top_score,
                candidates=self._make_summaries(candidates),
                reasons=[ReasonCode.BELOW_CONFIDENCE_THRESHOLD],
            )
            trace.emit(
                TraceEvent(
                    event_type=EventType.DECIDED,
                    data={"status": result.status.value},
                )
            )
            return result

        # Step 5: gap check — single candidate ≥ threshold is always a clear winner
        effective_gap = self._effective_gap(query)
        if len(candidates) == 1:
            has_clear_winner = True
        else:
            gap = top_score - candidates[1].scores.calibrated_score
            if self._gap_inclusive:
                has_clear_winner = gap >= effective_gap
            else:
                has_clear_winner = gap > effective_gap

        if not has_clear_winner:
            # Step 6: tiebreak hook
            winner = self._tiebreak(candidates, context, effective_gap)
            if winner is not None:
                result = self._make_resolved(
                    winner, candidates, self._resolved_reason(winner)
                )
                trace.emit(
                    TraceEvent(
                        event_type=EventType.DECIDED,
                        data={"status": result.status.value},
                    )
                )
                return result

            # Ambiguous
            result = ResolutionResult(
                status=ResolutionStatus.AMBIGUOUS,
                candidates=self._make_summaries(candidates),
                reasons=[ReasonCode.AMBIGUOUS_LOW_GAP],
            )
            trace.emit(
                TraceEvent(
                    event_type=EventType.DECIDED,
                    data={"status": result.status.value},
                )
            )
            return result

        # Step 7: resolved
        result = self._make_resolved(top, candidates, self._resolved_reason(top))
        trace.emit(
            TraceEvent(
                event_type=EventType.DECIDED,
                data={"status": result.status.value},
            )
        )
        return result

    # ------------------------------------------------------------------
    # Public threshold access
    # ------------------------------------------------------------------

    @property
    def confidence_threshold(self) -> float:
        """Minimum calibrated score for a RESOLVED result.

        Scores below this value produce NO_MATCH with the calibrated score
        attached so callers can distinguish near-misses from true no-candidates.
        """
        return self._confidence_threshold

    @confidence_threshold.setter
    def confidence_threshold(self, value: float) -> None:
        """Override the confidence threshold after construction.

        Args:
            value: New threshold in [0, 1].
        """
        self._confidence_threshold = value

    # ------------------------------------------------------------------
    # Override hooks
    # ------------------------------------------------------------------

    def _early_accept(
        self, top: Candidate, all_candidates: list[Candidate]
    ) -> ReasonCode | None:
        """Return a ReasonCode for an immediate RESOLVED, or None to continue.

        Override in subclasses to implement domain-specific early-accept rules
        (e.g., exact-code match for geo).
        """
        return None

    def _effective_gap(self, query: Query) -> float:
        """Return the effective gap threshold for this query.

        Override in subclasses that apply query-dependent gap adjustments
        (e.g., a stricter gap for acronym queries in org resolution).
        """
        return self._min_gap

    def _tiebreak(
        self,
        candidates: list[Candidate],
        context: ResolutionContext,
        gap: float,
    ) -> Candidate | None:
        """Attempt to break an ambiguous tie.  Return the winner, or None.

        Override in subclasses that have context-aware tiebreak logic
        (e.g., parent-org context in org resolution).
        """
        return None

    def _resolved_reason(self, top: Candidate) -> ReasonCode:
        """Return the ReasonCode to attach when the decision is RESOLVED.

        Two-pass derivation:
        - Pass 1: first stamped tier above the FTS floor (EXACT_CODE, EXACT_NAME,
          ACRONYM, FUZZY), in source order.  FTS and FALLBACK are NOT early-return
          cases — they fall through to the default, matching both packs today.
        - Pass 2: for un-stamped evidence (match_tier is None), match source-name
          substring tokens.  No "fts" token; un-matched names fall to the default.
        - Default: FTS_MATCH.
        """
        # Pass 1 — stamped tiers above the FTS floor, source order
        for ev in top.sources:
            tier = ev.match_tier
            if tier is not None and tier not in _FLOOR_TIERS:
                reason = TIER_TO_REASON.get(tier)
                if reason is not None:
                    return reason
        # Pass 2 — source-name fallback ONLY for un-stamped evidence (match_tier is None)
        for ev in top.sources:
            if ev.match_tier is None:
                for token, reason in _SOURCE_NAME_REASON_TOKENS:
                    if token in ev.source_name:
                        return reason
        return ReasonCode.FTS_MATCH

    # ------------------------------------------------------------------
    # Helpers shared by all subclasses
    # ------------------------------------------------------------------

    def _make_resolved(
        self,
        top: Candidate,
        all_candidates: list[Candidate],
        reason: ReasonCode,
    ) -> ResolutionResult:
        return ResolutionResult(
            status=ResolutionStatus.RESOLVED,
            entity_id=top.entity_id,
            confidence=top.scores.calibrated_score,
            candidates=self._make_summaries(all_candidates),
            reasons=[reason],
        )

    def _make_summaries(self, candidates: list[Candidate]) -> list[CandidateSummary]:
        return [build_candidate_summary(c) for c in candidates[: self._max_candidates]]
