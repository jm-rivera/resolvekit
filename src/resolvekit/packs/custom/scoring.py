"""Custom-domain scorer — heuristic-only, no model or calibrator."""

from __future__ import annotations

from typing import override

from resolvekit.core.engine.interfaces import ConfidenceBand
from resolvekit.core.model import FeatureVector
from resolvekit.packs.custom.features import CustomFeaturesV1
from resolvekit.shared.scoring_base import PackScorer

# Score constants: exact_code wins, then exact_name, then fuzzy/fts.
EXACT_CODE_SCORE = 0.95
EXACT_NAME_SCORE = 0.90
# Fuzzy: 0.5 + edit_sim*0.35 + token_sim*0.1, capped at 0.89
FUZZY_BASE = 0.5
FUZZY_EDIT_WEIGHT = 0.35
FUZZY_TOKEN_WEIGHT = 0.10
FUZZY_CAP = 0.89
# FTS: 0.4 + bm25_norm*0.4
FTS_BASE = 0.4
FTS_BONUS = 0.4
FALLBACK_SCORE = 0.3


class CustomScorer(PackScorer):
    """Heuristic scorer for custom-domain entities.

    Tier order: exact_code (0.95) > exact_name (0.90) > fuzzy (≤0.89) > fts > 0.3.
    No model or calibrator is used; calibration is an explicit non-goal for custom packs.
    """

    @override
    def _apply_heuristic(self, features: FeatureVector) -> float:
        if not isinstance(features, CustomFeaturesV1):
            raise TypeError(
                f"CustomScorer requires CustomFeaturesV1, got {type(features).__name__}"
            )

        if features.exact_code_hit:
            return EXACT_CODE_SCORE

        if features.exact_name_hit:
            return EXACT_NAME_SCORE

        # Fuzzy signals: cap at 0.89 so fuzzy never outranks exact hits.
        if features.fuzzy_edit_sim is not None:
            raw = (
                FUZZY_BASE
                + FUZZY_EDIT_WEIGHT * features.fuzzy_edit_sim
                + FUZZY_TOKEN_WEIGHT * (features.fuzzy_token_sim or 0.0)
            )
            return min(raw, FUZZY_CAP)

        if features.fts_bm25_norm is not None:
            return FTS_BASE + FTS_BONUS * features.fts_bm25_norm

        return FALLBACK_SCORE

    @property
    @override
    def confidence_band(self) -> ConfidenceBand | None:
        # Heuristic scores are already in a natural range; apply band normalization
        # so downstream callers get consistent high/medium/low confidence labels.
        return ConfidenceBand(
            high_confidence_floor=0.88,
            medium_confidence_floor=0.65,
            low_confidence_floor=0.40,
        )
