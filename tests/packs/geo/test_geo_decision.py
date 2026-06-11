"""Characterization tests for GeoDecisionPolicy reason-code derivation."""

from __future__ import annotations


def _fuzzy_candidate(entity_id: str = "geo/X", score: float = 0.85):
    from resolvekit.core.model import (
        Candidate,
        CandidateEvidence,
        MatchTier,
        RetrievalSummary,
        ScoreSummary,
    )

    return Candidate(
        entity_id=entity_id,
        sources=[
            CandidateEvidence(
                entity_id=entity_id,
                source_name="geo_fuzzy_retrieval",
                raw_score=score,
                match_tier=MatchTier.FUZZY,
            )
        ],
        retrieval=RetrievalSummary(best_source="geo_fuzzy_retrieval"),
        scores=ScoreSummary(raw_score=score, calibrated_score=score),
    )


class TestGeoResolvedReason:
    """Pin reason-code derivation for the FUZZY tier on current HEAD."""

    def test_fuzzy_tier_win_returns_fuzzy_match(self) -> None:
        """FUZZY evidence resolves to FUZZY_MATCH via the base tier-map."""
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            NormalizedText,
            Query,
            ReasonCode,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.packs.geo.decision import GeoDecisionPolicy

        policy = GeoDecisionPolicy()
        query = Query(
            raw_text="springfeld",
            normalized=NormalizedText(original="springfeld", normalized="springfeld"),
        )
        result = policy.decide(
            query, ResolutionContext(), [_fuzzy_candidate()], NullTraceSink()
        )

        assert result.status == ResolutionStatus.RESOLVED
        assert result.reasons == (ReasonCode.FUZZY_MATCH,)

    def test_geo_fuzzy_reranker_source_returns_fuzzy_match(self) -> None:
        """Both geo fuzzy sources (geo_fuzzy and geo_fuzzy_retrieval) report FUZZY_MATCH."""
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
        from resolvekit.packs.geo.decision import GeoDecisionPolicy

        score = 0.85
        entity_id = "geo/X"
        candidate = Candidate(
            entity_id=entity_id,
            sources=[
                CandidateEvidence(
                    entity_id=entity_id,
                    source_name="geo_fuzzy",
                    raw_score=score,
                    match_tier=MatchTier.FUZZY,
                )
            ],
            retrieval=RetrievalSummary(best_source="geo_fuzzy"),
            scores=ScoreSummary(raw_score=score, calibrated_score=score),
        )
        policy = GeoDecisionPolicy()
        query = Query(
            raw_text="springfeld",
            normalized=NormalizedText(original="springfeld", normalized="springfeld"),
        )
        result = policy.decide(query, ResolutionContext(), [candidate], NullTraceSink())

        assert result.status == ResolutionStatus.RESOLVED
        assert result.reasons == (ReasonCode.FUZZY_MATCH,)

    def test_fuzzy_tier_win_is_resolved(self) -> None:
        """Sanity: FUZZY-tier single candidate reaches RESOLVED with the expected entity_id."""
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            NormalizedText,
            Query,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.packs.geo.decision import GeoDecisionPolicy

        policy = GeoDecisionPolicy()
        query = Query(
            raw_text="springfeld",
            normalized=NormalizedText(original="springfeld", normalized="springfeld"),
        )
        candidate = _fuzzy_candidate(entity_id="geo/Springfield_IL")
        result = policy.decide(query, ResolutionContext(), [candidate], NullTraceSink())

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "geo/Springfield_IL"
