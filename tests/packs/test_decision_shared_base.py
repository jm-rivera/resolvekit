"""Verify GeoDecisionPolicy and OrgDecisionPolicy produce RESOLVED/AMBIGUOUS/NO_MATCH
outcomes under various confidence and gap conditions.
"""

from resolvekit.core.engine.decision import ThresholdDecisionPolicy
from resolvekit.packs.geo.decision import GeoDecisionPolicy
from resolvekit.packs.org.decision import OrgDecisionPolicy


class TestDecisionPolicyInheritance:
    """Both domain policies are ThresholdDecisionPolicy instances."""

    def test_geo_is_threshold_decision_policy(self):
        assert isinstance(GeoDecisionPolicy(), ThresholdDecisionPolicy)

    def test_org_is_threshold_decision_policy(self):
        assert isinstance(OrgDecisionPolicy(), ThresholdDecisionPolicy)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_candidate(entity_id: str, score: float, source_name: str):
    from resolvekit.core.model import (
        Candidate,
        CandidateEvidence,
        RetrievalSummary,
        ScoreSummary,
    )

    return Candidate(
        entity_id=entity_id,
        sources=[
            CandidateEvidence(
                entity_id=entity_id,
                source_name=source_name,
                raw_score=score,
            )
        ],
        retrieval=RetrievalSummary(best_source=source_name),
        scores=ScoreSummary(raw_score=score, calibrated_score=score),
    )


def _geo_query(text: str = "United States"):
    from resolvekit.core.model import NormalizedText, Query

    return Query(
        raw_text=text,
        normalized=NormalizedText(original=text, normalized=text.lower()),
    )


def _org_query(text: str = "World Bank"):
    from resolvekit.core.model import NormalizedText, Query

    return Query(
        raw_text=text,
        normalized=NormalizedText(original=text, normalized=text.lower()),
    )


# ---------------------------------------------------------------------------
# GeoDecisionPolicy characterization
# ---------------------------------------------------------------------------


class TestGeoDecisionPolicyOutcomes:
    """Verify RESOLVED/AMBIGUOUS/NO_MATCH outcomes for geo policy."""

    def test_resolves_single_candidate_above_threshold(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            ReasonCode,
            ResolutionContext,
            ResolutionStatus,
        )

        policy = GeoDecisionPolicy()
        candidates = [_make_candidate("country/USA", 0.9, "geo_exact_name")]
        result = policy.decide(
            _geo_query(), ResolutionContext(), candidates, NullTraceSink()
        )

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "country/USA"
        assert ReasonCode.EXACT_NAME_MATCH in result.reasons

    def test_no_match_below_threshold(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            ReasonCode,
            ResolutionContext,
            ResolutionStatus,
        )

        policy = GeoDecisionPolicy()
        candidates = [_make_candidate("country/USA", 0.5, "geo_fts")]
        result = policy.decide(
            _geo_query(), ResolutionContext(), candidates, NullTraceSink()
        )

        assert result.status == ResolutionStatus.NO_MATCH
        assert ReasonCode.BELOW_CONFIDENCE_THRESHOLD in result.reasons

    def test_ambiguous_when_gap_too_small(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            ReasonCode,
            ResolutionContext,
            ResolutionStatus,
        )

        policy = GeoDecisionPolicy()
        # gap = 0.01 < DEFAULT_MIN_GAP (0.10)
        candidates = [
            _make_candidate("country/USA", 0.80, "geo_fts"),
            _make_candidate("country/GBR", 0.79, "geo_fts"),
        ]
        result = policy.decide(
            _geo_query(), ResolutionContext(), candidates, NullTraceSink()
        )

        assert result.status == ResolutionStatus.AMBIGUOUS
        assert ReasonCode.AMBIGUOUS_LOW_GAP in result.reasons

    def test_resolves_with_clear_gap(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import ResolutionContext, ResolutionStatus

        policy = GeoDecisionPolicy()
        # gap = 0.20 > DEFAULT_MIN_GAP (0.10)
        candidates = [
            _make_candidate("country/USA", 0.90, "geo_fts"),
            _make_candidate("country/GBR", 0.70, "geo_fts"),
        ]
        result = policy.decide(
            _geo_query(), ResolutionContext(), candidates, NullTraceSink()
        )

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "country/USA"

    def test_early_accept_exact_code(self):
        """Exact-code evidence with score >= 0.9 triggers early accept."""
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            Candidate,
            CandidateEvidence,
            MatchTier,
            NormalizedText,
            Query,
            ReasonCode,
            ResolutionContext,
            ResolutionStatus,
            RetrievalSummary,
            ScoreSummary,
        )

        policy = GeoDecisionPolicy()
        query = Query(
            raw_text="US",
            normalized=NormalizedText(original="US", normalized="us"),
        )
        candidates = [
            Candidate(
                entity_id="country/USA",
                sources=[
                    CandidateEvidence(
                        entity_id="country/USA",
                        source_name="geo_exact_code",
                        raw_score=1.0,
                        match_tier=MatchTier.EXACT_CODE,
                    )
                ],
                retrieval=RetrievalSummary(best_source="geo_exact_code"),
                scores=ScoreSummary(raw_score=1.0, calibrated_score=1.0),
            ),
            # A close runner-up that would normally cause AMBIGUOUS
            Candidate(
                entity_id="country/GBR",
                sources=[
                    CandidateEvidence(
                        entity_id="country/GBR",
                        source_name="geo_fts",
                        raw_score=0.99,
                    )
                ],
                retrieval=RetrievalSummary(best_source="geo_fts"),
                scores=ScoreSummary(raw_score=0.99, calibrated_score=0.99),
            ),
        ]
        result = policy.decide(query, ResolutionContext(), candidates, NullTraceSink())

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "country/USA"
        assert ReasonCode.EXACT_CODE_MATCH in result.reasons

    def test_no_candidates_returns_no_match(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            ReasonCode,
            ResolutionContext,
            ResolutionStatus,
        )

        policy = GeoDecisionPolicy()
        result = policy.decide(_geo_query(), ResolutionContext(), [], NullTraceSink())

        assert result.status == ResolutionStatus.NO_MATCH
        assert ReasonCode.NO_CANDIDATES in result.reasons


# ---------------------------------------------------------------------------
# OrgDecisionPolicy characterization
# ---------------------------------------------------------------------------


class TestOrgDecisionPolicyOutcomes:
    """Verify RESOLVED/AMBIGUOUS/NO_MATCH outcomes for org policy."""

    def test_resolves_single_candidate_above_threshold(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import ResolutionContext, ResolutionStatus

        policy = OrgDecisionPolicy()
        candidates = [_make_candidate("org/WorldBank", 0.85, "org_exact_name")]
        result = policy.decide(
            _org_query(), ResolutionContext(), candidates, NullTraceSink()
        )

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "org/WorldBank"

    def test_no_match_below_threshold(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            ReasonCode,
            ResolutionContext,
            ResolutionStatus,
        )

        policy = OrgDecisionPolicy()
        candidates = [_make_candidate("org/WorldBank", 0.4, "org_fts")]
        result = policy.decide(
            _org_query(), ResolutionContext(), candidates, NullTraceSink()
        )

        assert result.status == ResolutionStatus.NO_MATCH
        assert ReasonCode.BELOW_CONFIDENCE_THRESHOLD in result.reasons

    def test_ambiguous_non_acronym_small_gap(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            ReasonCode,
            ResolutionContext,
            ResolutionStatus,
        )

        policy = OrgDecisionPolicy()
        # gap = 0.01 < DEFAULT_MIN_GAP (0.10)
        candidates = [
            _make_candidate("org/A", 0.80, "org_fts"),
            _make_candidate("org/B", 0.79, "org_fts"),
        ]
        result = policy.decide(
            _org_query(), ResolutionContext(), candidates, NullTraceSink()
        )

        assert result.status == ResolutionStatus.AMBIGUOUS
        assert ReasonCode.AMBIGUOUS_LOW_GAP in result.reasons

    def test_acronym_ambiguous_uses_acronym_reason_code(self):
        """Acronym query with gap < ACRONYM_MIN_GAP → ACRONYM_MATCH_AMBIGUOUS."""
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            NormalizedText,
            Query,
            ReasonCode,
            ResolutionContext,
            ResolutionStatus,
        )

        policy = OrgDecisionPolicy()
        query = Query(
            raw_text="IDA",
            normalized=NormalizedText(original="IDA", normalized="ida"),
        )
        # gap = 0.01 < ACRONYM_MIN_GAP (0.15)
        candidates = [
            _make_candidate("org/A", 0.85, "org_acronym"),
            _make_candidate("org/B", 0.84, "org_acronym"),
        ]
        result = policy.decide(query, ResolutionContext(), candidates, NullTraceSink())

        assert result.status == ResolutionStatus.AMBIGUOUS
        assert ReasonCode.ACRONYM_MATCH_AMBIGUOUS in result.reasons

    def test_resolves_with_clear_gap(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import ResolutionContext, ResolutionStatus

        policy = OrgDecisionPolicy()
        # gap = 0.20 > DEFAULT_MIN_GAP (0.10)
        candidates = [
            _make_candidate("org/WorldBank", 0.90, "org_fts"),
            _make_candidate("org/IMF", 0.70, "org_fts"),
        ]
        result = policy.decide(
            _org_query(), ResolutionContext(), candidates, NullTraceSink()
        )

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "org/WorldBank"

    def test_no_candidates_returns_no_match(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            ReasonCode,
            ResolutionContext,
            ResolutionStatus,
        )

        policy = OrgDecisionPolicy()
        result = policy.decide(_org_query(), ResolutionContext(), [], NullTraceSink())

        assert result.status == ResolutionStatus.NO_MATCH
        assert ReasonCode.NO_CANDIDATES in result.reasons


# ---------------------------------------------------------------------------
# Gap-boundary semantics (gap == min_gap is inclusive → clear winner)
# ---------------------------------------------------------------------------


class TestGapInclusiveBoundary:
    """At gap == min_gap the top candidate is a clear winner (RESOLVED).

    Both policies treat ``gap < min_gap`` as AMBIGUOUS, so the threshold
    itself resolves. ``min_gap`` is set to the exact float the policy computes
    so the boundary is hit precisely regardless of float representation.
    """

    def test_geo_resolves_when_gap_exactly_equals_min_gap(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import ResolutionContext, ResolutionStatus

        top, second = 0.90, 0.80
        exact_gap = top - second  # same arithmetic the policy uses internally
        policy = GeoDecisionPolicy(min_gap=exact_gap)
        candidates = [
            _make_candidate("country/USA", top, "geo_fts"),
            _make_candidate("country/GBR", second, "geo_fts"),
        ]
        result = policy.decide(
            _geo_query(), ResolutionContext(), candidates, NullTraceSink()
        )

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "country/USA"

    def test_org_resolves_when_gap_exactly_equals_min_gap(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import ResolutionContext, ResolutionStatus

        top, second = 0.90, 0.80
        exact_gap = top - second
        policy = OrgDecisionPolicy(min_gap=exact_gap)
        # Non-acronym query so the standard min_gap (not acronym_gap) applies.
        candidates = [
            _make_candidate("org/A", top, "org_fts"),
            _make_candidate("org/B", second, "org_fts"),
        ]
        result = policy.decide(
            _org_query("World Bank"), ResolutionContext(), candidates, NullTraceSink()
        )

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "org/A"
