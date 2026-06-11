"""Boundary characterization tests for ThresholdDecisionPolicy.

Pins the exact threshold and gap boundaries. All tests instantiate
``ThresholdDecisionPolicy(confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True)``.
With an empty ``_source_reason_codes`` map, the resolved reason is always ``FTS_MATCH`` —
that behavior is intentional and pinned here.
"""

from __future__ import annotations

from resolvekit.core.engine.decision import TIER_TO_REASON, ThresholdDecisionPolicy
from resolvekit.core.explain import NullTraceSink
from resolvekit.core.model import (
    Candidate,
    CandidateEvidence,
    MatchTier,
    ReasonCode,
    ResolutionStatus,
    RetrievalSummary,
    ScoreSummary,
)


def _cand(entity_id: str, score: float) -> Candidate:
    """Minimal Candidate with calibrated_score == raw_score == *score*."""
    return Candidate(
        entity_id=entity_id,
        sources=[
            CandidateEvidence(
                entity_id=entity_id,
                source_name="x",
                raw_score=score,
            )
        ],
        retrieval=RetrievalSummary(best_source="x"),
        scores=ScoreSummary(raw_score=score, calibrated_score=score),
    )


def _policy() -> ThresholdDecisionPolicy:
    """Return the policy that reproduces _default_decide semantics."""
    return ThresholdDecisionPolicy(
        confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
    )


class TestDefaultDecide:
    """Boundary characterization of ThresholdDecisionPolicy."""

    def setup_method(self) -> None:
        self._policy = _policy()
        self._trace = NullTraceSink()

    def test_at_threshold_single_candidate_resolves(self) -> None:
        """Calibrated score 0.8 (== DEFAULT_CONFIDENCE_THRESHOLD) → RESOLVED."""
        candidates = [_cand("entity/A", 0.8)]
        result = self._policy.decide(
            query=None,  # type: ignore[arg-type]
            context=None,  # type: ignore[arg-type]
            candidates=candidates,
            trace=self._trace,
        )

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "entity/A"
        assert result.confidence == 0.8
        assert ReasonCode.FTS_MATCH in result.reasons

    def test_below_threshold_single_candidate_no_match(self) -> None:
        """Calibrated score 0.79 (< 0.8 threshold) → NO_MATCH."""
        candidates = [_cand("entity/A", 0.79)]
        result = self._policy.decide(
            query=None,  # type: ignore[arg-type]
            context=None,  # type: ignore[arg-type]
            candidates=candidates,
            trace=self._trace,
        )

        assert result.status == ResolutionStatus.NO_MATCH
        assert ReasonCode.BELOW_CONFIDENCE_THRESHOLD in result.reasons

    def test_gap_at_boundary_resolves(self) -> None:
        """Gap >= 0.10 (>= DEFAULT_AMBIGUITY_GAP) → RESOLVED.

        Top=0.80, second=0.70 → float gap = 0.10000000000000009, which satisfies
        ``>= DEFAULT_AMBIGUITY_GAP``.  The code comment reads "Include equality -
        gap at threshold is enough separation" confirming >= is intentional.
        Note: 0.85 - 0.75 = 0.09999... (float rounding), so that pair falls below
        the boundary; 0.80/0.70 is the canonical floating-point-safe boundary case.
        """
        candidates = [_cand("entity/A", 0.80), _cand("entity/B", 0.70)]
        result = self._policy.decide(
            query=None,  # type: ignore[arg-type]
            context=None,  # type: ignore[arg-type]
            candidates=candidates,
            trace=self._trace,
        )

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "entity/A"
        assert ReasonCode.FTS_MATCH in result.reasons

    def test_gap_below_boundary_ambiguous(self) -> None:
        """Gap < 0.10 (< DEFAULT_AMBIGUITY_GAP) → AMBIGUOUS.

        0.85 - 0.76 = 0.08999... in float, clearly below the boundary.
        """
        candidates = [_cand("entity/A", 0.85), _cand("entity/B", 0.76)]
        result = self._policy.decide(
            query=None,  # type: ignore[arg-type]
            context=None,  # type: ignore[arg-type]
            candidates=candidates,
            trace=self._trace,
        )

        assert result.status == ResolutionStatus.AMBIGUOUS
        assert ReasonCode.AMBIGUOUS_LOW_GAP in result.reasons

    def test_no_candidates_no_match(self) -> None:
        """Empty candidate list → NO_MATCH with NO_CANDIDATES reason."""
        result = self._policy.decide(
            query=None,  # type: ignore[arg-type]
            context=None,  # type: ignore[arg-type]
            candidates=[],
            trace=self._trace,
        )

        assert result.status == ResolutionStatus.NO_MATCH
        assert ReasonCode.NO_CANDIDATES in result.reasons


class TestTierToReasonCoverage:
    """Structural guard: TIER_TO_REASON must cover every MatchTier member."""

    def test_tier_to_reason_covers_all_match_tiers(self) -> None:
        """TIER_TO_REASON maps every MatchTier; fails loudly if a new enum member is added without a mapping."""
        assert set(TIER_TO_REASON) == set(MatchTier)
