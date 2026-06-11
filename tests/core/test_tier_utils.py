"""Tests for core/engine/tier_utils.py — symbols importable and behaviors correct."""

from resolvekit.core.engine.tier_utils import (
    DEFAULT_BUDGET,
    DEFAULT_FALLBACK_SCORE,
    DEFAULT_TOP_K_RESULTS,
    MATCH_TIER_PRIORITY,
    REASON_TO_MATCH_TIER,
    build_candidate_summary,
    derive_candidate_match_tier,
    match_tier_rank,
    reason_to_match_tier,
)
from resolvekit.core.model import (
    Candidate,
    CandidateEvidence,
    MatchTier,
    ReasonCode,
    RetrievalSummary,
    ScoreSummary,
)

# ---------------------------------------------------------------------------
# Import-path smoke: every public symbol importable from tier_utils directly
# ---------------------------------------------------------------------------


class TestTierUtilsImports:
    def test_constants_importable(self):
        assert isinstance(MATCH_TIER_PRIORITY, dict)
        assert isinstance(REASON_TO_MATCH_TIER, dict)
        assert isinstance(DEFAULT_FALLBACK_SCORE, float)
        assert isinstance(DEFAULT_BUDGET, int)
        assert isinstance(DEFAULT_TOP_K_RESULTS, int)

    def test_also_importable_from_engine_package(self):
        """build_candidate_summary is re-exported via core.engine.__init__."""
        from resolvekit.core.engine import build_candidate_summary as bcs

        assert bcs is build_candidate_summary

    def test_also_importable_from_tier_utils_directly(self):
        from resolvekit.core.engine.tier_utils import match_tier_rank as mtr

        assert mtr is match_tier_rank


# ---------------------------------------------------------------------------
# match_tier_rank behavior
# ---------------------------------------------------------------------------


class TestMatchTierRank:
    def test_none_returns_minus_one(self):
        assert match_tier_rank(None) == -1

    def test_exact_code_is_highest(self):
        assert match_tier_rank(MatchTier.EXACT_CODE) > match_tier_rank(
            MatchTier.EXACT_NAME
        )

    def test_fallback_is_lowest_non_none(self):
        assert match_tier_rank(MatchTier.FALLBACK) == 0

    def test_ordering_is_total(self):
        tiers = [
            MatchTier.EXACT_CODE,
            MatchTier.EXACT_NAME,
            MatchTier.ACRONYM,
            MatchTier.FTS,
            MatchTier.FUZZY,
            MatchTier.FALLBACK,
        ]
        ranks = [match_tier_rank(t) for t in tiers]
        # All distinct
        assert len(set(ranks)) == len(ranks)


# ---------------------------------------------------------------------------
# reason_to_match_tier behavior
# ---------------------------------------------------------------------------


class TestReasonToMatchTier:
    def test_none_reason_returns_none(self):
        assert reason_to_match_tier(None) is None

    def test_exact_code_match_maps_to_exact_code(self):
        assert reason_to_match_tier(ReasonCode.EXACT_CODE_MATCH) == MatchTier.EXACT_CODE

    def test_exact_name_match_maps_to_exact_name(self):
        assert reason_to_match_tier(ReasonCode.EXACT_NAME_MATCH) == MatchTier.EXACT_NAME

    def test_acronym_match_maps_to_acronym(self):
        assert reason_to_match_tier(ReasonCode.ACRONYM_MATCH) == MatchTier.ACRONYM

    def test_acronym_match_ambiguous_maps_to_acronym(self):
        assert (
            reason_to_match_tier(ReasonCode.ACRONYM_MATCH_AMBIGUOUS)
            == MatchTier.ACRONYM
        )

    def test_unmapped_reason_returns_none(self):
        # ReasonCode values not in the map should return None
        assert reason_to_match_tier(ReasonCode.NO_CANDIDATES) is None


# ---------------------------------------------------------------------------
# derive_candidate_match_tier behavior
# ---------------------------------------------------------------------------


def _make_candidate(
    entity_id: str = "e1",
    *,
    sources: list[CandidateEvidence],
) -> Candidate:
    best = max(sources, key=lambda e: e.raw_score or 0.0)
    return Candidate(
        entity_id=entity_id,
        sources=sources,
        retrieval=RetrievalSummary(
            best_source=best.source_name,
            best_rank=best.rank,
            best_raw_score=best.raw_score,
            signals={},
        ),
        scores=ScoreSummary(raw_score=best.raw_score or 0.5, calibrated_score=0.5),
    )


def _ev(
    entity_id: str = "e1",
    *,
    source_name: str = "src",
    raw_score: float | None = None,
    rank: int | None = None,
    match_tier: MatchTier | None = None,
) -> CandidateEvidence:
    return CandidateEvidence(
        entity_id=entity_id,
        source_name=source_name,
        raw_score=raw_score,
        rank=rank,
        signals={},
        match_tier=match_tier,
    )


class TestDeriveCandidateMatchTier:
    def test_picks_strongest_tier_from_multiple_evidence(self):
        candidate = _make_candidate(
            sources=[
                _ev(match_tier=MatchTier.FUZZY, raw_score=0.7),
                _ev(match_tier=MatchTier.EXACT_NAME, raw_score=0.9, source_name="en"),
                _ev(match_tier=MatchTier.FTS, raw_score=0.6, source_name="fts"),
            ]
        )
        assert derive_candidate_match_tier(candidate) == MatchTier.EXACT_NAME

    def test_fallback_when_no_evidence(self):
        candidate = _make_candidate(sources=[_ev(raw_score=0.5)])
        # source_name="src" has no tier token and no stamped tier → FALLBACK
        assert derive_candidate_match_tier(candidate) == MatchTier.FALLBACK

    def test_uses_source_name_fallback_for_unstamped_evidence(self):
        candidate = _make_candidate(
            sources=[_ev(source_name="exact_code_src", raw_score=0.9)]
        )
        assert derive_candidate_match_tier(candidate) == MatchTier.EXACT_CODE


# ---------------------------------------------------------------------------
# build_candidate_summary behavior
# ---------------------------------------------------------------------------


class TestBuildCandidateSummary:
    def test_returns_correct_entity_id(self):
        candidate = _make_candidate(
            "my/entity",
            sources=[_ev("my/entity", match_tier=MatchTier.EXACT_CODE, raw_score=1.0)],
        )
        summary = build_candidate_summary(candidate)
        assert summary.entity_id == "my/entity"

    def test_top_evidence_capped_at_max_evidence(self):
        sources = [
            _ev(source_name=f"src{i}", raw_score=float(i) / 10) for i in range(6)
        ]
        candidate = _make_candidate(sources=sources)
        summary = build_candidate_summary(candidate, max_evidence=3)
        assert len(summary.top_evidence) == 3

    def test_top_evidence_sorted_descending_by_score(self):
        sources = [
            _ev(source_name="low", raw_score=0.3),
            _ev(source_name="high", raw_score=0.95),
            _ev(source_name="mid", raw_score=0.6),
        ]
        candidate = _make_candidate(sources=sources)
        summary = build_candidate_summary(candidate, max_evidence=2)
        assert summary.top_evidence[0].source_name == "high"
        assert summary.top_evidence[1].source_name == "mid"
