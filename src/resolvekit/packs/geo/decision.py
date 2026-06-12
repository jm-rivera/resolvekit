"""Geo decision policy."""

from typing import override

from resolvekit.core.engine.decision import ThresholdDecisionPolicy
from resolvekit.core.explain import TraceSink
from resolvekit.core.model import (
    Candidate,
    MatchTier,
    Query,
    ReasonCode,
    ResolutionContext,
    ResolutionResult,
)


def _hierarchy_rank(candidate: Candidate) -> float | None:
    """Geo hierarchy rank of a candidate, or None when unavailable."""
    features = candidate.features
    return getattr(features, "hierarchy_rank", None) if features is not None else None


# Decision policy defaults
DEFAULT_CONFIDENCE_THRESHOLD = 0.7
# min_gap of 0.07 from Platt calibration fit on full geo-tier mix.
# Calibrated-probability gaps scale with slope ratio ≈ 0.62 from the fit (a=-8.50).
# Empirical validation: South Sudan (country/SSD, fts-match rival of Sudan/SDN) sits
# at calibrated gap ≈0.074 — within this threshold — which produces the expected
# Sudan→country/SDN resolution.
DEFAULT_MIN_GAP = 0.07
DEFAULT_MAX_CANDIDATES = 5

# Strong early accept threshold for exact code matches
EXACT_CODE_MIN_SCORE = 0.9

# Hierarchy rank thresholds (mirrors scoring.py constants)
_CITY_RANK = 0.70
_ADMIN2_RANK = 0.60

# Lower min_gap for city/admin2 ties: with live prominence data, a dominant city
# (prom=1.0) produces a calibrated gap of ≈0.034 vs an obscure same-named peer (prom=0.0).
# Setting this to 0.03 allows such dominant cities to resolve while equal-prominence
# pairs (gap≈0) and near-equal cities (gap≈0.004) stay AMBIGUOUS.
CITY_ADMIN_MIN_GAP = 0.03


class GeoDecisionPolicy(ThresholdDecisionPolicy):
    """Decision policy for geographic entity resolution.

    Early accept rules (candidates pre-filtered for hard constraint violations):
    - Exact code match with score >= 0.9
    - High-confidence fuzzy match with score >= threshold and clear winner gap

    Standard resolution:
    - Accept if confidence >= threshold and gap to runner-up >= min_gap
    - AMBIGUOUS if gap to runner-up < min_gap (e.g., "Springfield")
    - NO_MATCH if confidence < threshold

    City/admin2 ties use ``city_admin_min_gap`` (lower than ``min_gap``) so that
    a genuinely dominant city (high prominence) can resolve over an obscure
    same-named peer while equal-prominence pairs still stay AMBIGUOUS.
    """

    def __init__(
        self,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        min_gap: float = DEFAULT_MIN_GAP,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
        exact_code_min_score: float = EXACT_CODE_MIN_SCORE,
        city_admin_min_gap: float = CITY_ADMIN_MIN_GAP,
    ) -> None:
        super().__init__(
            confidence_threshold=confidence_threshold,
            min_gap=min_gap,
            gap_inclusive=True,
            max_candidates=max_candidates,
        )
        self._exact_code_min_score = exact_code_min_score
        self._city_admin_min_gap = city_admin_min_gap
        self._tiebreak_winner_id: str | None = None

    @override
    def decide(
        self,
        query: Query,
        context: ResolutionContext,
        candidates: list[Candidate],
        trace: TraceSink,
    ) -> ResolutionResult:
        """Resolve with a per-tier gap: city/admin2 ties use a lower min_gap.

        When the top candidates are all city or admin2 entities, substitutes
        ``city_admin_min_gap`` for the default ``min_gap`` so that a genuinely
        dominant city (high prominence) can clear the gap while equal-prominence
        pairs still stay AMBIGUOUS.  All other cases use the parent logic unchanged.
        """
        if candidates and self._all_city_admin(candidates):
            original_min_gap = self._min_gap
            self._min_gap = self._city_admin_min_gap
            try:
                return super().decide(query, context, candidates, trace)
            finally:
                self._min_gap = original_min_gap
        return super().decide(query, context, candidates, trace)

    def _all_city_admin(self, candidates: list[Candidate]) -> bool:
        """Return True when every candidate is a city or admin2-and-below entity."""
        for c in candidates:
            rank = _hierarchy_rank(c)
            if rank is None or rank > _CITY_RANK:
                return False
        return True

    @override
    def _early_accept(
        self, top: Candidate, all_candidates: list[Candidate]
    ) -> ReasonCode | None:
        """Early accept for exact-code matches with high confidence.

        Detects the EXACT_CODE tier via stamped evidence, falling back to a
        source_name check only for un-stamped evidence (match_tier is None).
        """
        top_score = top.scores.calibrated_score
        has_exact_code = any(
            ev.match_tier == MatchTier.EXACT_CODE
            or (ev.match_tier is None and ev.source_name.endswith("exact_code"))
            for ev in top.sources
        )
        if has_exact_code and top_score >= self._exact_code_min_score:
            return ReasonCode.EXACT_CODE_MATCH
        return None

    @override
    def _tiebreak(
        self,
        candidates: list[Candidate],
        context: ResolutionContext,
        gap: float,
    ) -> Candidate | None:
        """Break a near-tie when the top candidate strictly outranks its rivals.

        When the top candidate sits within ``gap`` of one or more runners-up but
        outranks every one of them in the geo hierarchy (continent > country >
        region > admin…), it is the unambiguous answer — e.g. the continent
        "Antarctica" (rank 1.0) over the same-named UN region (rank 0.75). A tie
        between equal-rank entities (two cities named "Springfield") is left
        AMBIGUOUS.
        """
        self._tiebreak_winner_id = None
        top = candidates[0]
        top_rank = _hierarchy_rank(top)
        if top_rank is None:
            return None

        top_score = top.scores.calibrated_score
        close = [
            c for c in candidates[1:] if top_score - c.scores.calibrated_score < gap
        ]
        if not close:
            return None
        for rival in close:
            rival_rank = _hierarchy_rank(rival)
            if rival_rank is None or rival_rank >= top_rank:
                return None

        self._tiebreak_winner_id = top.entity_id
        return top

    @override
    def _resolved_reason(self, top: Candidate) -> ReasonCode:
        """Emit HIERARCHY_PREFERENCE_TIEBREAK when the rank tiebreak won."""
        if self._tiebreak_winner_id == top.entity_id:
            self._tiebreak_winner_id = None  # clear after use
            return ReasonCode.HIERARCHY_PREFERENCE_TIEBREAK
        return super()._resolved_reason(top)
