"""Geo scorer with heuristic fallback and logistic regression."""

from __future__ import annotations

import math
from typing import override

from resolvekit.core.engine.interfaces import ConfidenceBand
from resolvekit.core.model import FeatureVector
from resolvekit.packs.geo.features import GeoFeaturesV1
from resolvekit.shared.scoring_base import PackScorer

# Geo scoring thresholds (tuned via internal testing)
EXACT_CODE_SCORE = 0.95
EXACT_NAME_SCORE = 0.90
FUZZY_BASE = 0.5
FUZZY_EDIT_SIM_BONUS = 0.35
FUZZY_TOKEN_SIM_BONUS = 0.1
FUZZY_MAX_SCORE = 0.89
FUZZY_LENGTH_DIVISOR = 6.0
# Above this fuzzy_edit_sim, the match is trusted regardless of query length
# (short country names like "Italy" / "Egypt" would otherwise be crushed).
FUZZY_TRUST_SIM = 0.85
# Minimum length before any length penalty — queries at or above this are not penalized.
FUZZY_LENGTH_PENALTY_FLOOR = 4
# SymSpell distance-1 yields norm ~0.75; distance-2 yields ~0.6. When a pure-fuzzy
# resolution is only reachable via a distance>=2 SymSpell correction, the match is
# weaker (e.g. fictional "Latveria"->Latvia vs legit "Mexco"->Mexico). Damp the
# fuzzy bonus by sym_norm/this_anchor to widen the gap between dist-1 and dist-2
# in raw-score space, giving the calibrator a sharper signal.
FUZZY_SYMSPELL_QUALITY_THRESHOLD = 0.7
FUZZY_SYMSPELL_QUALITY_ANCHOR = 0.75
FTS_BASE = 0.4
FTS_BONUS = 0.4
FALLBACK_SCORE = 0.3
CONSTRAINT_FAIL_PENALTY = 0.05
HIERARCHY_TIEBREAK_FACTOR = 0.009  # must be < min inter-tier gap (0.01)
# Raised from 0.05 to let a dominant city/admin2 (prominence≈1.0) separate from
# an obscure same-named peer when city_min_gap is applied.  Max score adjustment
# is ±(PROMINENCE_TIEBREAK_FACTOR / 2) = ±0.06, which clears CITY_ADMIN_MIN_GAP
# (0.06) only when the prominence delta is large (≈1.0).  Equal-prominence pairs
# still produce zero net gap and stay AMBIGUOUS.
PROMINENCE_TIEBREAK_FACTOR = 0.12

# Acronym inputs (4-10 all-uppercase chars) route to geo so that group entities
# like NATO/ASEAN/OPEC can resolve via the geo pack.  The routing boost is
# intentional, but it must not allow geo admin/city or region candidates to win
# on the same inputs (e.g. "NASA" → geo admin4 "Nasa", "EMEA" → admin4 "Emea",
# "FIFA" fuzzy → geo.region IFAD are all misroutings).
#
# Group-class hierarchy ranks (org=0.80, continental_union=0.90, country=0.85,
# continent=1.0) are all >= 0.80.  Region (0.75) and below (admin1-5, city)
# are suppressed on bare uppercase-acronym inputs by clamping to FALLBACK_SCORE,
# keeping them below the 0.7 confidence threshold.
#
# The block applies to fuzzy AND exact-name tiers — exact-name hits on e.g.
# geo.admin4 "Nasa" or geo.city "Swift" are equally spurious.  Exact-code
# matches are always exempt (those are unambiguous ISO-code hits).
ACRONYM_GROUP_MIN_RANK = 0.80  # rank >= this is a group/union/country/continent
ACRONYM_REGION_RANK = 0.75  # rank in [0.75, 0.80) is a region/world_region
ACRONYM_QUERY_MIN_LEN = 4
ACRONYM_QUERY_MAX_LEN = 10


class GeoScorer(PackScorer):
    """Scorer for geo entities.

    Supports:
    - Heuristic scoring (default)
    - Logistic regression (when model provided)
    """

    @override
    def _apply_heuristic(self, features: FeatureVector) -> float:
        """Apply rule-based heuristic scoring."""
        if not isinstance(features, GeoFeaturesV1):
            raise TypeError(
                f"GeoScorer requires GeoFeaturesV1, got {type(features).__name__}"
            )
        # Tier 1: Exact matches
        if features.exact_code_hit:
            score = EXACT_CODE_SCORE
        elif features.exact_name_hit:
            score = EXACT_NAME_SCORE
            # Block non-group geo entities on bare uppercase-acronym inputs even
            # when matched by name (e.g. "NASA" → exact_name geo.admin4 "Nasa",
            # "SWIFT" → exact_name geo.city "Swift").  Exact-code is exempt.
            if self._is_acronym_admin_mismatch(features):
                score = FALLBACK_SCORE
        # Tier 2: Fuzzy matches (with query-length penalty)
        elif features.fuzzy_edit_sim is not None:
            length_factor = self._fuzzy_length_factor(
                features.query_len, features.fuzzy_edit_sim
            )
            sym_quality = self._symspell_quality_factor(features.symspell_edit_norm)
            base = FUZZY_BASE + (
                features.fuzzy_edit_sim
                * FUZZY_EDIT_SIM_BONUS
                * length_factor
                * sym_quality
            )
            if features.fuzzy_token_sim:
                base += features.fuzzy_token_sim * FUZZY_TOKEN_SIM_BONUS * sym_quality
            base = min(base, FUZZY_MAX_SCORE)
            score = self._apply_constraint_penalties(features, base)
            # Block non-group geo entities on bare uppercase-acronym inputs.
            # The routing +0.15 boost exists so group entities (NATO, ASEAN,
            # OPEC…) can compete against org.  Fuzzy matches to admin/city/region
            # on the same inputs (e.g. "FIFA" → fuzzy geo.region IFAD) are
            # misroutings: clamp them to FALLBACK_SCORE so they can never
            # clear the 0.7 confidence threshold.
            if self._is_acronym_admin_mismatch(features):
                score = FALLBACK_SCORE
        # Tier 3: FTS
        elif features.fts_bm25_norm is not None:
            score = FTS_BASE + (features.fts_bm25_norm * FTS_BONUS)
            score = self._apply_constraint_penalties(features, score)
        else:
            # Fallback
            score = FALLBACK_SCORE

        # Hierarchy tie-breaking: prefer more prominent entity types
        if features.hierarchy_rank is not None:
            score += features.hierarchy_rank * HIERARCHY_TIEBREAK_FACTOR

        if features.candidate_prominence is not None:
            score += (features.candidate_prominence - 0.5) * PROMINENCE_TIEBREAK_FACTOR

        return score

    def _is_acronym_admin_mismatch(self, features: GeoFeaturesV1) -> bool:
        """True when an all-uppercase acronym query matched a non-group geo entity.

        Group entities (continent=1.0, continental_union=0.9, country=0.85,
        organization=0.80) always pass.  City (0.70) and admin1-5 (0.65-0.25)
        are always suppressed (e.g. "NASA" -> exact_name geo.admin4 "Nasa",
        "SWIFT" -> geo.city "Swift").  Region/world_region (0.75) is allowed on
        an exact name/code hit (a world-region acronym like MENA is a real
        target) but suppressed on a fuzzy match ("FIFA" -> fuzzy geo.region IFAD).
        """
        if not features.query_is_upper:
            return False
        if not (ACRONYM_QUERY_MIN_LEN <= features.query_len <= ACRONYM_QUERY_MAX_LEN):
            return False
        rank = features.hierarchy_rank
        if rank is None or rank >= ACRONYM_GROUP_MIN_RANK:
            return False
        if rank < ACRONYM_REGION_RANK:
            return True  # city/admin tier: always spurious on an acronym
        # region tier: legitimate only when matched exactly, not fuzzily.
        return not (features.exact_name_hit or features.exact_code_hit)

    def _fuzzy_length_factor(self, query_len: int, fuzzy_edit_sim: float) -> float:
        # Trust strong fuzzy matches regardless of length: country names like
        # "Italy" or "Egypt" are short but legitimate, so do not penalize them.
        if fuzzy_edit_sim >= FUZZY_TRUST_SIM:
            return 1.0
        length = max(query_len, 1)
        if length >= FUZZY_LENGTH_PENALTY_FLOOR:
            # Square-root ramp is gentler than linear; reaches 1.0 at len = divisor.
            return min(1.0, math.sqrt(length / FUZZY_LENGTH_DIVISOR))
        return length / FUZZY_LENGTH_DIVISOR

    def _symspell_quality_factor(self, symspell_edit_norm: float | None) -> float:
        if symspell_edit_norm is None:
            return 1.0
        if symspell_edit_norm >= FUZZY_SYMSPELL_QUALITY_THRESHOLD:
            return 1.0
        return min(1.0, symspell_edit_norm / FUZZY_SYMSPELL_QUALITY_ANCHOR)

    def _apply_constraint_penalties(
        self, features: GeoFeaturesV1, score: float
    ) -> float:
        """Apply small penalties when constraints explicitly fail."""
        if features.containment_pass is False:
            score -= CONSTRAINT_FAIL_PENALTY
        if features.type_pass is False:
            score -= CONSTRAINT_FAIL_PENALTY
        return max(score, FALLBACK_SCORE)

    @property
    @override
    def confidence_band(self) -> ConfidenceBand | None:
        # Suppress the band when a model or calibrator is present — both already
        # produce probabilities, so band normalization would be redundant.
        if self._model is not None or self._calibrator is not None:
            return None
        return ConfidenceBand(
            high_confidence_floor=0.88,
            medium_confidence_floor=0.65,
            low_confidence_floor=0.40,
        )
