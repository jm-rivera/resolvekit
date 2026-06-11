"""Org decision policy - ambiguity-aware."""

from typing import override

from resolvekit.core.engine.decision import ThresholdDecisionPolicy
from resolvekit.core.explain import TraceSink
from resolvekit.core.model import (
    Candidate,
    ConstraintRole,
    Query,
    ReasonCode,
    ResolutionContext,
    ResolutionResult,
    ResolutionStatus,
)
from resolvekit.packs.org._acronym import is_acronym_like

# Decision policy defaults
DEFAULT_CONFIDENCE_THRESHOLD = 0.7
DEFAULT_MIN_GAP = 0.1
ACRONYM_MIN_GAP = 0.15  # Stricter gap for acronym queries
DEFAULT_MAX_CANDIDATES = 5


class OrgDecisionPolicy(ThresholdDecisionPolicy):
    """Decision policy for org resolution.

    Key differences from geo:
    - Acronym queries require higher gap to resolve
    - Parent org context can break ties
    - More conservative on ambiguous results
    """

    def __init__(
        self,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        min_gap: float = DEFAULT_MIN_GAP,
        acronym_min_gap: float = ACRONYM_MIN_GAP,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
    ):
        super().__init__(
            confidence_threshold=confidence_threshold,
            min_gap=min_gap,
            gap_inclusive=True,
            max_candidates=max_candidates,
        )
        self._acronym_gap = acronym_min_gap
        self._tiebreak_winner_id: str | None = None

    # ------------------------------------------------------------------
    # Hook overrides
    # ------------------------------------------------------------------

    @override
    def _effective_gap(self, query: Query) -> float:
        """Use stricter gap for acronym-like queries."""
        if self._is_acronym_like(query.normalized.original):
            return self._acronym_gap
        return self._min_gap

    @override
    def _tiebreak(
        self,
        candidates: list[Candidate],
        context: ResolutionContext,
        gap: float,
    ) -> Candidate | None:
        """Attempt to break a tie using parent org context.

        Reads outcome.role == ConstraintRole.PARENT_SCOPE (not constraint_name).
        Stores the winner's entity_id so _resolved_reason can emit the correct code.
        """
        self._tiebreak_winner_id = None
        if not context.parent_ids:
            return None

        top_score = candidates[0].scores.calibrated_score
        close_candidates = [
            c for c in candidates if top_score - c.scores.calibrated_score < gap
        ]

        with_parent = [
            c for c in close_candidates if self._has_parent_match(c, context)
        ]

        if len(with_parent) == 1:
            self._tiebreak_winner_id = with_parent[0].entity_id
            return with_parent[0]
        return None

    @override
    def _resolved_reason(self, top: Candidate) -> ReasonCode:
        """Emit PARENT_CONTEXT_TIEBREAK when tiebreak won; else delegate to base."""
        if self._tiebreak_winner_id == top.entity_id:
            self._tiebreak_winner_id = None  # clear after use
            return ReasonCode.PARENT_CONTEXT_TIEBREAK
        return super()._resolved_reason(top)

    # ------------------------------------------------------------------
    # decide() override: patch acronym-ambiguous reason code
    # ------------------------------------------------------------------

    def decide(
        self,
        query: Query,
        context: ResolutionContext,
        candidates: list[Candidate],
        trace: TraceSink,
    ) -> ResolutionResult:
        """Delegate to base, then fix the AMBIGUOUS reason for acronym queries."""
        result = super().decide(query, context, candidates, trace)

        if (
            result.status == ResolutionStatus.AMBIGUOUS
            and self._is_acronym_like(query.normalized.original)
            and result.reasons == [ReasonCode.AMBIGUOUS_LOW_GAP]
        ):
            return ResolutionResult(
                status=result.status,
                entity_id=result.entity_id,
                confidence=result.confidence,
                candidates=result.candidates,
                reasons=[ReasonCode.ACRONYM_MATCH_AMBIGUOUS],
            )

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _has_parent_match(
        self, candidate: Candidate, context: ResolutionContext
    ) -> bool:
        """Check if candidate has a PARENT_SCOPE constraint that passed."""
        if not context.parent_ids:
            return False
        return any(
            co.role == ConstraintRole.PARENT_SCOPE and co.passed is True
            for co in candidate.constraint_outcomes
        )

    def _is_acronym_like(self, text: str) -> bool:
        return is_acronym_like(text)
