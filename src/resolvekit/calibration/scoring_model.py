"""Logistic scoring model: dot product + sigmoid, serialisable to JSON.

The model is trained with sklearn at training time, but at runtime it
uses pure-Python arithmetic so sklearn is not required.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from resolvekit.calibration.vectorize import features_dict_to_vector

if TYPE_CHECKING:
    from resolvekit.core.model import FeatureVector


class LogisticScoringModel(BaseModel):
    """Trained logistic regression scoring model.

    Stores feature names, weights, and bias extracted from a fitted
    sklearn LogisticRegression. At predict time it applies the dot
    product + sigmoid in pure Python — no sklearn dependency.

    Sigmoid convention: ``1 / (1 + exp(-logit))`` — identical to
    sklearn's default, not the negated Platt convention.
    """

    model_config = ConfigDict(frozen=True)

    method: Literal["logistic"] = "logistic"
    feature_names: list[str]
    weights: list[float]
    bias: float
    domain: str
    fit_n_samples: int
    schema_version: str = "geo.features.v1"
    confidence_threshold: float | None = None
    min_gap: float | None = None
    exact_code_min_score: float | None = None

    @property
    def model_version(self) -> str:
        """Version string for trace metadata."""
        return f"logistic:{self.schema_version}:n={self.fit_n_samples}"

    def predict(self, features: FeatureVector) -> float:
        """Return calibrated probability for the given feature vector.

        Args:
            features: Any object satisfying the FeatureVector protocol
                (must have a ``to_dict()`` method).

        Returns:
            Probability in [0, 1].
        """
        return self.predict_dict(features.to_dict())

    def predict_dict(self, features: dict[str, float]) -> float:
        """Return calibrated probability for a raw feature dict keyed by name.

        Args:
            features: Feature values keyed by feature name (e.g. a stored
                ``features_dict``). Missing names are vectorized as 0.

        Returns:
            Probability in [0, 1].
        """
        vec = features_dict_to_vector(self.feature_names, features)
        logit = sum(w * x for w, x in zip(self.weights, vec, strict=False)) + self.bias
        logit = max(-30.0, min(30.0, logit))
        return 1.0 / (1.0 + math.exp(-logit))


def save_scoring_model(model: LogisticScoringModel, path: str | Path) -> None:
    """Save a LogisticScoringModel to a JSON file."""
    Path(path).write_text(model.model_dump_json(indent=2), encoding="utf-8")


def load_scoring_model(path: str | Path) -> LogisticScoringModel:
    """Load a LogisticScoringModel from a JSON file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return LogisticScoringModel.model_validate(data)
