"""Calibration model definitions for Platt scaling and isotonic regression."""

from __future__ import annotations

import bisect
import json
import math
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class PlattCalibrator(BaseModel):
    """Platt scaling calibrator: maps raw scores to probabilities via sigmoid."""

    model_config = ConfigDict(frozen=True)

    method: Literal["platt"] = "platt"
    a: float
    b: float
    domain: str
    fit_n_samples: int

    def predict(self, raw_score: float, *, query_len: int | None = None) -> float:
        """Apply Platt scaling: sigmoid(a * raw_score + b)."""
        logit = self.a * raw_score + self.b
        logit = max(-30.0, min(30.0, logit))
        return 1.0 / (1.0 + math.exp(logit))


class IsotonicCalibrator(BaseModel):
    """Isotonic regression calibrator using piecewise linear interpolation."""

    model_config = ConfigDict(frozen=True)

    method: Literal["isotonic"] = "isotonic"
    xs: list[float] = Field(default_factory=list)
    ys: list[float] = Field(default_factory=list)
    domain: str
    fit_n_samples: int

    def predict(self, raw_score: float, *, query_len: int | None = None) -> float:
        """Piecewise linear interpolation with boundary clamping."""
        if not self.xs:
            return raw_score
        if len(self.xs) == 1:
            return self.ys[0]

        if raw_score <= self.xs[0]:
            return self.ys[0]
        if raw_score >= self.xs[-1]:
            return self.ys[-1]

        # Binary search for the interval
        idx = bisect.bisect_right(self.xs, raw_score) - 1
        x0, x1 = self.xs[idx], self.xs[idx + 1]
        y0, y1 = self.ys[idx], self.ys[idx + 1]

        t = (raw_score - x0) / (x1 - x0)
        return y0 + t * (y1 - y0)


class StratifiedCalibrator(BaseModel):
    """Calibrator that dispatches to sub-calibrators based on query length.

    Addresses non-monotonic score-accuracy relationships by training separate
    calibrators for short vs long queries, where within each group the
    relationship is more monotonic.
    """

    model_config = ConfigDict(frozen=True)

    method: Literal["stratified"] = "stratified"
    short_query_threshold: int = 6
    short_calibrator: PlattCalibrator | IsotonicCalibrator
    long_calibrator: PlattCalibrator | IsotonicCalibrator
    domain: str
    fit_n_samples: int

    def predict(self, raw_score: float, *, query_len: int | None = None) -> float:
        """Predict calibrated score, dispatching by query length.

        Falls back to long_calibrator when query_len is unknown (None),
        since long queries are the majority case.
        """
        if query_len is not None and query_len <= self.short_query_threshold:
            return self.short_calibrator.predict(raw_score)
        return self.long_calibrator.predict(raw_score)


# Union type for all calibrator variants
Calibrator = Annotated[
    PlattCalibrator | IsotonicCalibrator | StratifiedCalibrator,
    Field(discriminator="method"),
]


_calibrator_adapter = TypeAdapter(Calibrator)


def load_calibrator(path: str | Path) -> Calibrator:
    """Load a calibrator from a JSON file, dispatching on the 'method' field."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return _calibrator_adapter.validate_python(data)


def save_calibrator(calibrator: Calibrator, path: str | Path) -> None:
    """Save a calibrator to a JSON file."""
    Path(path).write_text(calibrator.model_dump_json(indent=2), encoding="utf-8")
