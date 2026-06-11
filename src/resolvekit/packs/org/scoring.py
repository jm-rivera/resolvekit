"""Org scorer with heuristic fallback."""

from __future__ import annotations

from typing import override

from resolvekit.core.engine.interfaces import ConfidenceBand
from resolvekit.core.model import FeatureVector
from resolvekit.packs.org.features import OrgFeaturesV1
from resolvekit.shared.scoring_base import PackScorer

# Org scoring thresholds (tuned via internal testing)
EXACT_CODE_SCORE = 0.95
EXACT_NAME_SCORE = 0.92
ACRONYM_EXACT_SCORE = 0.88
ACRONYM_HIT_SCORE = 0.82
TOKEN_SIM_BASE = 0.5
TOKEN_SIM_BONUS = 0.35
FTS_BASE = 0.4
FTS_BONUS = 0.35
FALLBACK_SCORE = 0.3


class OrgScorer(PackScorer):
    """Scorer for org entities.

    Acronym matches get high scores but require stricter
    disambiguation due to collision risk.
    """

    @override
    def _apply_heuristic(self, features: FeatureVector) -> float:
        if not isinstance(features, OrgFeaturesV1):
            raise TypeError(
                f"OrgScorer requires OrgFeaturesV1, got {type(features).__name__}"
            )

        # Priority-ordered scoring rules: (condition, score)
        rules = [
            (features.exact_code_hit, EXACT_CODE_SCORE),
            (features.exact_name_hit, EXACT_NAME_SCORE),
            (features.acronym_exact, ACRONYM_EXACT_SCORE),
            (features.acronym_hit, ACRONYM_HIT_SCORE),
            (
                features.token_set_sim is not None,
                TOKEN_SIM_BASE + ((features.token_set_sim or 0) * TOKEN_SIM_BONUS),
            ),
            (
                features.fts_bm25_norm is not None,
                FTS_BASE + ((features.fts_bm25_norm or 0) * FTS_BONUS),
            ),
        ]

        return next((score for cond, score in rules if cond), FALLBACK_SCORE)

    @property
    @override
    def confidence_band(self) -> ConfidenceBand | None:
        # Org suppresses the band only for calibrator (model path not suppressed here).
        if self._calibrator is not None:
            return None  # Calibrated scores are probabilities; skip band normalization
        return ConfidenceBand(
            high_confidence_floor=0.85,
            medium_confidence_floor=0.65,
            low_confidence_floor=0.40,
        )
