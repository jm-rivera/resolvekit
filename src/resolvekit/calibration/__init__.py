"""Calibration pipeline for ResolveKit scorers.

Provides:
- PlattCalibrator and IsotonicCalibrator models
- Fitting routines (fit_platt, fit_isotonic)
- Evaluation metrics (brier_score, expected_calibration_error, evaluate_calibration)
- load_calibrator / save_calibrator helpers
- Dataset models and labeling utilities
- LogisticScoringModel and related helpers
- train_model / ModelTrainResult for end-to-end ML model training

Training-only symbols (``train_calibrator``, ``train_model``,
``run_adapters``, ``ModelTrainResult``, ``TrainResult``) are imported
lazily on first attribute access so that merely loading a calibrator
JSON at runtime does not pull in pandas / gecko / scikit-learn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from resolvekit.calibration.dataset import (
    CalibrationDataset,
    LabeledExample,
    label_examples,
    load_examples_jsonl,
    save_examples_jsonl,
)
from resolvekit.calibration.evaluation import (
    CalibrationBin,
    CalibrationMetrics,
    brier_score,
    calibration_curve_data,
    evaluate_calibration,
    expected_calibration_error,
)
from resolvekit.calibration.models import (
    Calibrator,
    IsotonicCalibrator,
    PlattCalibrator,
    StratifiedCalibrator,
    load_calibrator,
    save_calibrator,
)
from resolvekit.calibration.scoring_model import (
    LogisticScoringModel,
    load_scoring_model,
    save_scoring_model,
)

if TYPE_CHECKING:  # pragma: no cover - typing-only
    from resolvekit.calibration.train import (
        ModelTrainResult,
        TrainResult,
        run_adapters,
        train_calibrator,
        train_model,
    )


# Map of lazily-loaded training symbols → their submodule. Importing the
# ``train`` submodule drags in pandas / gecko / sklearn which are not
# runtime dependencies of the resolver; defer it until a caller actually
# requests a training symbol.
_LAZY_TRAIN_SYMBOLS = frozenset(
    {
        "ModelTrainResult",
        "TrainResult",
        "run_adapters",
        "train_calibrator",
        "train_model",
    }
)


def __getattr__(name: str) -> Any:
    if name in _LAZY_TRAIN_SYMBOLS:
        from resolvekit.calibration import train as _train

        value = getattr(_train, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CalibrationBin",
    "CalibrationDataset",
    "CalibrationMetrics",
    "Calibrator",
    "IsotonicCalibrator",
    "LabeledExample",
    "LogisticScoringModel",
    "ModelTrainResult",
    "PlattCalibrator",
    "StratifiedCalibrator",
    "TrainResult",
    "brier_score",
    "calibration_curve_data",
    "evaluate_calibration",
    "expected_calibration_error",
    "label_examples",
    "load_calibrator",
    "load_examples_jsonl",
    "load_scoring_model",
    "run_adapters",
    "save_calibrator",
    "save_examples_jsonl",
    "save_scoring_model",
    "train_calibrator",
    "train_model",
]
