"""Tests for 3A: NO_MATCH-by-threshold carries calibrated confidence.
Tests for 3B: confidence_threshold is a public lever on Resolver / classmethods.
"""

from __future__ import annotations

import pytest

from resolvekit.core.api import Resolver
from resolvekit.core.engine import PipelineRunner
from resolvekit.core.engine.decision import ThresholdDecisionPolicy
from resolvekit.core.engine.interfaces import CandidateSource
from resolvekit.core.explain import NullTraceSink
from resolvekit.core.model import (
    Candidate,
    CandidateEvidence,
    GenerationContext,
    NormalizedText,
    Query,
    ReasonCode,
    ResolutionContext,
    ResolutionStatus,
    RetrievalSummary,
    ScoreSummary,
)
from resolvekit.core.util import TextNormalizer
from tests.conftest import MockEntityStore

# ---------------------------------------------------------------------------
# Helpers shared across all tests in this file
# ---------------------------------------------------------------------------


def _cand(entity_id: str, score: float, source: str = "geo_fts") -> Candidate:
    """Minimal Candidate with calibrated_score == raw_score == *score*."""
    return Candidate(
        entity_id=entity_id,
        sources=[
            CandidateEvidence(
                entity_id=entity_id,
                source_name=source,
                raw_score=score,
            )
        ],
        retrieval=RetrievalSummary(best_source=source),
        scores=ScoreSummary(raw_score=score, calibrated_score=score),
    )


def _query(text: str = "test") -> Query:
    return Query(
        raw_text=text,
        normalized=NormalizedText(original=text, normalized=text.lower()),
    )


def _ctx() -> ResolutionContext:
    return ResolutionContext()


def _trace() -> NullTraceSink:
    return NullTraceSink()


# ---------------------------------------------------------------------------
# 3A: NO_MATCH-by-threshold carries calibrated confidence
# ---------------------------------------------------------------------------


class TestNoMatchBelowThresholdCarriesConfidence:
    """BELOW_CONFIDENCE_THRESHOLD results must include the top calibrated score."""

    def test_near_miss_confidence_equals_top_calibrated_score(self):
        """A near-miss at 0.66 → NO_MATCH with confidence=0.66."""
        policy = ThresholdDecisionPolicy(
            confidence_threshold=0.70, min_gap=0.1, gap_inclusive=True
        )
        candidates = [_cand("country/USA", 0.66)]

        result = policy.decide(_query(), _ctx(), candidates, _trace())

        assert result.status == ResolutionStatus.NO_MATCH
        assert ReasonCode.BELOW_CONFIDENCE_THRESHOLD in result.reasons
        assert result.confidence is not None
        assert abs(result.confidence - 0.66) < 1e-9

    def test_true_no_candidate_confidence_is_none(self):
        """NO_CANDIDATES (empty list) must NOT attach a confidence."""
        policy = ThresholdDecisionPolicy(
            confidence_threshold=0.70, min_gap=0.1, gap_inclusive=True
        )
        result = policy.decide(_query(), _ctx(), [], _trace())

        assert result.status == ResolutionStatus.NO_MATCH
        assert ReasonCode.NO_CANDIDATES in result.reasons
        assert result.confidence is None  # no candidate → nothing to attach

    def test_resolved_result_also_has_confidence(self):
        """Sanity check: RESOLVED results continue to carry confidence."""
        policy = ThresholdDecisionPolicy(
            confidence_threshold=0.70, min_gap=0.1, gap_inclusive=True
        )
        candidates = [_cand("country/USA", 0.90)]
        result = policy.decide(_query(), _ctx(), candidates, _trace())

        assert result.status == ResolutionStatus.RESOLVED
        assert result.confidence is not None
        assert abs(result.confidence - 0.90) < 1e-9

    def test_confidence_on_no_match_is_calibrated_not_raw(self):
        """Attached confidence is the calibrated score (same scale as RESOLVED)."""
        policy = ThresholdDecisionPolicy(
            confidence_threshold=0.80, min_gap=0.1, gap_inclusive=True
        )
        calibrated_score = 0.72
        candidates = [_cand("country/USA", calibrated_score)]

        result = policy.decide(_query(), _ctx(), candidates, _trace())

        assert result.status == ResolutionStatus.NO_MATCH
        assert result.confidence == pytest.approx(calibrated_score)

    def test_multi_candidate_below_threshold_uses_top_score(self):
        """When all candidates are below threshold, top score is attached."""
        policy = ThresholdDecisionPolicy(
            confidence_threshold=0.70, min_gap=0.1, gap_inclusive=True
        )
        # top=0.68, second=0.50 — both below 0.70
        candidates = [
            _cand("country/USA", 0.68),
            _cand("country/GBR", 0.50),
        ]
        result = policy.decide(_query(), _ctx(), candidates, _trace())

        assert result.status == ResolutionStatus.NO_MATCH
        assert ReasonCode.BELOW_CONFIDENCE_THRESHOLD in result.reasons
        assert result.confidence == pytest.approx(0.68)

    def test_no_match_via_runner_carries_confidence(self):
        """End-to-end: PipelineRunner produces NO_MATCH with confidence via decision policy."""

        class LowConfidenceSource(CandidateSource):
            @property
            def name(self) -> str:
                return "geo_fts"

            def supports(self, domain_pack_id: str) -> bool:
                return True

            def generate(self, ctx: GenerationContext) -> list[CandidateEvidence]:
                return [
                    CandidateEvidence(
                        entity_id="country/USA",
                        source_name=self.name,
                        raw_score=0.63,
                        rank=1,
                    )
                ]

        store = MockEntityStore()
        runner = PipelineRunner(
            trace_sink=NullTraceSink(),
            store=store,
            sources=[LowConfidenceSource()],
            decision_policy=ThresholdDecisionPolicy(
                confidence_threshold=0.70, min_gap=0.1
            ),
        )
        query = Query(
            raw_text="something",
            normalized=NormalizedText(original="something", normalized="something"),
        )
        result = runner.resolve(query, ResolutionContext())

        assert result.status == ResolutionStatus.NO_MATCH
        assert ReasonCode.BELOW_CONFIDENCE_THRESHOLD in result.reasons
        assert result.confidence == pytest.approx(0.63)

    def test_no_candidates_via_runner_confidence_is_none(self):
        """End-to-end: when pipeline finds no candidates, confidence stays None."""

        class EmptySource(CandidateSource):
            @property
            def name(self) -> str:
                return "geo_fts"

            def supports(self, domain_pack_id: str) -> bool:
                return True

            def generate(self, ctx: GenerationContext) -> list[CandidateEvidence]:
                return []

        store = MockEntityStore()
        runner = PipelineRunner(
            trace_sink=NullTraceSink(),
            store=store,
            sources=[EmptySource()],
            decision_policy=ThresholdDecisionPolicy(
                confidence_threshold=0.70, min_gap=0.1
            ),
        )
        query = Query(
            raw_text="nothing",
            normalized=NormalizedText(original="nothing", normalized="nothing"),
        )
        result = runner.resolve(query, ResolutionContext())

        assert result.status == ResolutionStatus.NO_MATCH
        assert ReasonCode.NO_CANDIDATES in result.reasons
        assert result.confidence is None


# ---------------------------------------------------------------------------
# 3B: confidence_threshold as a public lever on Resolver
# ---------------------------------------------------------------------------


class MockScoreSource(CandidateSource):
    """Source that always returns a candidate with a fixed score."""

    def __init__(self, entity_id: str, score: float) -> None:
        self._entity_id = entity_id
        self._score = score

    @property
    def name(self) -> str:
        return "mock_fts"

    def supports(self, domain_pack_id: str) -> bool:
        return True

    def generate(self, ctx: GenerationContext) -> list[CandidateEvidence]:
        return [
            CandidateEvidence(
                entity_id=self._entity_id,
                source_name=self.name,
                raw_score=self._score,
                rank=1,
            )
        ]


def _make_resolver(
    source_score: float, *, confidence_threshold: float | None = None
) -> Resolver:
    """Build a minimal Resolver with a single source returning *source_score*."""
    store = MockEntityStore()
    policy = ThresholdDecisionPolicy(confidence_threshold=0.70, min_gap=0.1)
    runner = PipelineRunner(
        trace_sink=NullTraceSink(),
        store=store,
        sources=[MockScoreSource("country/USA", source_score)],
        decision_policy=policy,
    )
    return Resolver(
        runner=runner,
        normalizer=TextNormalizer(),
        confidence_threshold=confidence_threshold,
        sentinel_blocklist=None,  # not under test here
    )


class TestConfidenceThresholdKwarg:
    """confidence_threshold kwarg on Resolver changes the accept/reject boundary."""

    def test_default_threshold_rejects_below_070(self):
        """With default threshold (0.70), score 0.65 → NO_MATCH."""
        resolver = _make_resolver(0.65)
        result = resolver.resolve("test")
        assert result.status == ResolutionStatus.NO_MATCH

    def test_lower_threshold_accepts_near_miss(self):
        """Setting threshold=0.55 promotes a 0.65-score result to RESOLVED."""
        resolver = _make_resolver(0.65, confidence_threshold=0.55)
        result = resolver.resolve("test")
        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "country/USA"

    def test_higher_threshold_rejects_previously_accepted(self):
        """Setting threshold=0.85 rejects a 0.75-score result that default would accept."""
        resolver = _make_resolver(0.75, confidence_threshold=0.85)
        result = resolver.resolve("test")
        assert result.status == ResolutionStatus.NO_MATCH
        assert result.confidence == pytest.approx(0.75)

    def test_none_threshold_uses_pack_default(self):
        """confidence_threshold=None (default) leaves pack threshold unchanged."""
        # Pack default is 0.70; score 0.80 should resolve.
        resolver = _make_resolver(0.80, confidence_threshold=None)
        result = resolver.resolve("test")
        assert result.status == ResolutionStatus.RESOLVED

    def test_confidence_threshold_property_on_policy(self):
        """ThresholdDecisionPolicy.confidence_threshold is readable and settable."""
        policy = ThresholdDecisionPolicy(confidence_threshold=0.70, min_gap=0.1)
        assert policy.confidence_threshold == pytest.approx(0.70)

        policy.confidence_threshold = 0.55
        assert policy.confidence_threshold == pytest.approx(0.55)

        # After lowering, a score that was previously below threshold now resolves.
        candidates = [_cand("country/USA", 0.62)]
        result = policy.decide(_query(), _ctx(), candidates, _trace())
        assert result.status == ResolutionStatus.RESOLVED
