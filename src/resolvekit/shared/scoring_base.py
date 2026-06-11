"""Shared scorer base: heuristic-or-model dispatch, calibration, and thresholds.

All pack scorers inherit from `PackScorer`. Subclasses implement
`_apply_heuristic` (domain scoring logic) and `confidence_band`
(pack-specific band floors); the base owns everything else.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from resolvekit.core.engine import Scorer
from resolvekit.core.engine.interfaces import (
    ConfidenceBand,
    DecisionThresholds,
    ScoringModel,
)
from resolvekit.core.model import Candidate, FeatureVector, Query, RetrievalSummary

if TYPE_CHECKING:
    from resolvekit.calibration.models import Calibrator

# Shared threshold constants — identical in both geo and org packs.
_HEURISTIC_THRESHOLDS = DecisionThresholds()
_MODEL_THRESHOLDS = DecisionThresholds(
    confidence_threshold=0.70,
    min_gap=0.08,
    exact_code_min_score=0.75,
)


class PackScorer(Scorer):
    """Scorer base: heuristic-or-model dispatch + calibration + thresholds.

    Subclasses implement `_apply_heuristic` and `confidence_band`; the base
    owns the model/calibrator wiring shared by all packs.
    """

    def __init__(
        self,
        model: ScoringModel | None = None,
        calibrator: Calibrator | None = None,
    ) -> None:
        self._model = model
        self._calibrator = calibrator

    def score(self, features: FeatureVector, retrieval: RetrievalSummary) -> float:
        if self._model:
            return self._apply_model(features)
        return self._apply_heuristic(features)

    def calibrate(self, raw_score: float, query: Query, candidate: Candidate) -> float:
        if self._calibrator is not None:
            query_len = len(query.raw_text) if query is not None else None
            return self._calibrator.predict(raw_score, query_len=query_len)
        return raw_score

    @property
    def scorer_type(self) -> str:
        return "model" if self._model else "heuristic"

    @property
    def decision_thresholds(self) -> DecisionThresholds:
        if self._model is not None:
            ct = getattr(self._model, "confidence_threshold", None)
            mg = getattr(self._model, "min_gap", None)
            ec = getattr(self._model, "exact_code_min_score", None)
            return DecisionThresholds(
                confidence_threshold=ct
                if ct is not None
                else _MODEL_THRESHOLDS.confidence_threshold,
                min_gap=mg if mg is not None else _MODEL_THRESHOLDS.min_gap,
                exact_code_min_score=ec
                if ec is not None
                else _MODEL_THRESHOLDS.exact_code_min_score,
            )
        if self._calibrator is not None:
            return _MODEL_THRESHOLDS
        return _HEURISTIC_THRESHOLDS

    def _apply_model(self, features: FeatureVector) -> float:
        if self._model is None:
            raise RuntimeError("model scoring requested without a model")
        return self._model.predict(features)

    @abstractmethod
    def _apply_heuristic(self, features: FeatureVector) -> float:
        """Subclasses must implement."""
        ...

    @property
    @abstractmethod
    def confidence_band(self) -> ConfidenceBand | None:
        """Pack-specific confidence band floors for cross-pack normalization."""
        ...
