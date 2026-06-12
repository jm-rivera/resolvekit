"""Tests for geo prominence scoring and city/admin2 min_gap policy.

Validates prominence-based scoring with PROMINENCE_TIEBREAK_FACTOR and a lower
min_gap for city/admin2 ties, allowing a dominant city to resolve while
equal-prominence pairs stay AMBIGUOUS.
"""

from __future__ import annotations

from resolvekit.core.model import RetrievalSummary

_STUB_RETRIEVAL = RetrievalSummary(best_source="test")


def _city_candidate(
    entity_id: str,
    *,
    calibrated_score: float,
    prominence: float | None,
    hierarchy_rank: float = 0.70,
):
    """Build a synthetic city-tier candidate with the given calibrated score."""
    from resolvekit.core.model import (
        Candidate,
        CandidateEvidence,
        RetrievalSummary,
        ScoreSummary,
    )
    from resolvekit.packs.geo.features import GeoFeaturesV1

    return Candidate(
        entity_id=entity_id,
        sources=[
            CandidateEvidence(
                entity_id=entity_id,
                source_name="geo_exact_name",
                raw_score=calibrated_score,
            )
        ],
        retrieval=RetrievalSummary(best_source="geo_exact_name"),
        features=GeoFeaturesV1(
            exact_name_hit=True,
            hierarchy_rank=hierarchy_rank,
            candidate_prominence=prominence,
        ),
        scores=ScoreSummary(
            raw_score=calibrated_score, calibrated_score=calibrated_score
        ),
    )


class TestProminenceFactor:
    """Scoring-level assertions for the new PROMINENCE_TIEBREAK_FACTOR=0.12."""

    def test_factor_value(self):
        from resolvekit.packs.geo.scoring import PROMINENCE_TIEBREAK_FACTOR

        assert PROMINENCE_TIEBREAK_FACTOR == 0.12

    def test_dominant_city_outscores_obscure_peer_by_full_factor(self):
        """Dominant city (prom=1.0) outscores obscure peer (prom=0.0) by exactly the factor."""
        from resolvekit.packs.geo.features import GeoFeaturesV1
        from resolvekit.packs.geo.scoring import PROMINENCE_TIEBREAK_FACTOR, GeoScorer

        scorer = GeoScorer()
        dominant = GeoFeaturesV1(exact_name_hit=True, candidate_prominence=1.0)
        obscure = GeoFeaturesV1(exact_name_hit=True, candidate_prominence=0.0)

        gap = scorer.score(dominant, _STUB_RETRIEVAL) - scorer.score(
            obscure, _STUB_RETRIEVAL
        )
        assert abs(gap - PROMINENCE_TIEBREAK_FACTOR) < 1e-9

    def test_equal_prominence_produces_zero_gap(self):
        """Two cities with equal prominence produce no score separation."""
        from resolvekit.packs.geo.features import GeoFeaturesV1
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()
        city_a = GeoFeaturesV1(exact_name_hit=True, candidate_prominence=0.5)
        city_b = GeoFeaturesV1(exact_name_hit=True, candidate_prominence=0.5)

        assert scorer.score(city_a, _STUB_RETRIEVAL) == scorer.score(
            city_b, _STUB_RETRIEVAL
        )

    def test_exact_code_with_max_prominence_beats_exact_name_with_max_prominence(self):
        """Prominence cannot flip exact_code rank below exact_name."""
        from resolvekit.packs.geo.features import GeoFeaturesV1
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()
        exact_code = GeoFeaturesV1(exact_code_hit=True, candidate_prominence=1.0)
        exact_name = GeoFeaturesV1(exact_name_hit=True, candidate_prominence=1.0)

        assert scorer.score(exact_code, _STUB_RETRIEVAL) > scorer.score(
            exact_name, _STUB_RETRIEVAL
        )


class TestCityAdminDecision:
    """Decision-policy assertions for city/admin2 per-tier min_gap."""

    def test_city_admin_min_gap_is_below_default(self):
        from resolvekit.packs.geo.decision import CITY_ADMIN_MIN_GAP, DEFAULT_MIN_GAP

        assert CITY_ADMIN_MIN_GAP < DEFAULT_MIN_GAP
        assert CITY_ADMIN_MIN_GAP == 0.03

    def test_dominant_city_resolves_over_obscure_peer(self):
        """Dominant city (prom=1.0) resolves over obscure same-named peer (prom=0.0).

        Score gap ≈ PROMINENCE_TIEBREAK_FACTOR = 0.12, which clears CITY_ADMIN_MIN_GAP=0.03.
        """
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            NormalizedText,
            Query,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.packs.geo.decision import GeoDecisionPolicy
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()

        from resolvekit.packs.geo.features import GeoFeaturesV1

        feats_fr = GeoFeaturesV1(
            exact_name_hit=True, hierarchy_rank=0.70, candidate_prominence=1.0
        )
        feats_tx = GeoFeaturesV1(
            exact_name_hit=True, hierarchy_rank=0.70, candidate_prominence=0.0
        )
        score_fr = scorer.score(feats_fr, _STUB_RETRIEVAL)
        score_tx = scorer.score(feats_tx, _STUB_RETRIEVAL)

        paris_fr = _city_candidate(
            "city/Paris_FR", calibrated_score=score_fr, prominence=1.0
        )
        paris_tx = _city_candidate(
            "city/Paris_TX", calibrated_score=score_tx, prominence=0.0
        )

        policy = GeoDecisionPolicy()
        query = Query(
            raw_text="Paris",
            normalized=NormalizedText(original="Paris", normalized="paris"),
        )
        result = policy.decide(
            query, ResolutionContext(), [paris_fr, paris_tx], NullTraceSink()
        )

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "city/Paris_FR"

    def test_equal_prominence_cities_stay_ambiguous(self):
        """Two same-named equal-prominence cities remain AMBIGUOUS (coin-flip preserved)."""
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            NormalizedText,
            Query,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.packs.geo.decision import GeoDecisionPolicy
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()

        from resolvekit.packs.geo.features import GeoFeaturesV1

        feats = GeoFeaturesV1(
            exact_name_hit=True, hierarchy_rank=0.70, candidate_prominence=0.5
        )
        score = scorer.score(feats, _STUB_RETRIEVAL)

        candidates = [
            _city_candidate(
                "city/Springfield_IL", calibrated_score=score, prominence=0.5
            ),
            _city_candidate(
                "city/Springfield_MO", calibrated_score=score, prominence=0.5
            ),
        ]

        policy = GeoDecisionPolicy()
        query = Query(
            raw_text="Springfield",
            normalized=NormalizedText(original="Springfield", normalized="springfield"),
        )
        result = policy.decide(query, ResolutionContext(), candidates, NullTraceSink())

        assert result.status == ResolutionStatus.AMBIGUOUS

    def test_country_tier_uses_default_min_gap(self):
        """Country-tier candidates are not subject to city_admin_min_gap.

        A gap of 0.05 (between CITY_ADMIN_MIN_GAP=0.03 and DEFAULT_MIN_GAP=0.07)
        stays AMBIGUOUS for country-tier entities — city-tier leniency does not apply.
        """
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            Candidate,
            CandidateEvidence,
            NormalizedText,
            Query,
            ResolutionContext,
            ResolutionStatus,
            RetrievalSummary,
            ScoreSummary,
        )
        from resolvekit.packs.geo.decision import GeoDecisionPolicy
        from resolvekit.packs.geo.features import GeoFeaturesV1

        policy = GeoDecisionPolicy()
        query = Query(
            raw_text="Georgia",
            normalized=NormalizedText(original="Georgia", normalized="georgia"),
        )

        # hierarchy_rank=0.85 is country tier (> _CITY_RANK=0.70), so default min_gap applies
        candidates = [
            Candidate(
                entity_id="country/GEO",
                sources=[
                    CandidateEvidence(
                        entity_id="country/GEO",
                        source_name="geo_exact_name",
                        raw_score=0.85,
                    )
                ],
                retrieval=RetrievalSummary(best_source="geo_exact_name"),
                features=GeoFeaturesV1(exact_name_hit=True, hierarchy_rank=0.85),
                scores=ScoreSummary(raw_score=0.85, calibrated_score=0.85),
            ),
            Candidate(
                entity_id="admin1/USA_GA",
                sources=[
                    CandidateEvidence(
                        entity_id="admin1/USA_GA",
                        source_name="geo_exact_name",
                        raw_score=0.80,
                    )
                ],
                retrieval=RetrievalSummary(best_source="geo_exact_name"),
                features=GeoFeaturesV1(exact_name_hit=True, hierarchy_rank=0.85),
                scores=ScoreSummary(raw_score=0.80, calibrated_score=0.80),
            ),
        ]
        # Gap = 0.05, above CITY_ADMIN_MIN_GAP (0.03) but below DEFAULT_MIN_GAP (0.07) → AMBIGUOUS
        result = policy.decide(query, ResolutionContext(), candidates, NullTraceSink())

        assert result.status == ResolutionStatus.AMBIGUOUS

    def test_city_gap_above_city_threshold_resolves(self):
        """A city-tier score gap > CITY_ADMIN_MIN_GAP resolves the top candidate."""
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            NormalizedText,
            Query,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.packs.geo.decision import CITY_ADMIN_MIN_GAP, GeoDecisionPolicy

        policy = GeoDecisionPolicy()
        query = Query(
            raw_text="Paris",
            normalized=NormalizedText(original="Paris", normalized="paris"),
        )

        top_score = 0.96
        runner_up_score = top_score - (
            CITY_ADMIN_MIN_GAP + 0.02
        )  # gap=0.08 > threshold

        candidates = [
            _city_candidate(
                "city/Paris_FR", calibrated_score=top_score, prominence=None
            ),
            _city_candidate(
                "city/Paris_TX", calibrated_score=runner_up_score, prominence=None
            ),
        ]
        result = policy.decide(query, ResolutionContext(), candidates, NullTraceSink())

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "city/Paris_FR"
