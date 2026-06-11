"""Fitting routines for calibration models.

Uses scikit-learn for battle-tested implementations of Platt scaling
and isotonic regression. sklearn is an optional dependency:
    pip install resolvekit[calibration]

The fitted parameters are extracted into lightweight Pydantic models
(PlattCalibrator, IsotonicCalibrator) for runtime prediction — no
sklearn needed at predict time.
"""

from __future__ import annotations

import math
from typing import Literal

from resolvekit.calibration.dataset import LabeledExample
from resolvekit.calibration.models import (
    IsotonicCalibrator,
    PlattCalibrator,
    StratifiedCalibrator,
)
from resolvekit.calibration.scoring_model import LogisticScoringModel
from resolvekit.calibration.vectorize import (
    feature_names_for_domain,
    features_dict_to_vector,
)

_SKLEARN_INSTALL_MSG = (
    "scikit-learn is required for calibration fitting. "
    "Install with: pip install resolvekit[calibration]"
)


def _validate_inputs(
    scores: list[float], labels: list[int], min_examples: int = 2
) -> tuple[list[float], list[int]]:
    """Validate and filter calibration inputs."""
    if len(scores) < min_examples:
        raise ValueError(f"Need at least {min_examples} examples, got {len(scores)}")
    if len(scores) != len(labels):
        raise ValueError(
            f"scores and labels must have the same length: "
            f"{len(scores)} != {len(labels)}"
        )

    # Filter NaN/inf
    clean_scores = []
    clean_labels = []
    for s, lbl in zip(scores, labels, strict=False):
        if math.isfinite(s):
            clean_scores.append(s)
            clean_labels.append(lbl)

    if len(clean_scores) < min_examples:
        raise ValueError(
            f"After filtering NaN/inf, need at least {min_examples} examples, "
            f"got {len(clean_scores)}"
        )

    if len(set(clean_labels)) < 2:
        raise ValueError("Need both positive and negative examples for calibration")

    return clean_scores, clean_labels


def fit_platt(scores: list[float], labels: list[int], domain: str) -> PlattCalibrator:
    """Fit Platt scaling (sigmoid calibration) using sklearn.

    Uses LogisticRegression on (raw_score, label) pairs to fit the
    sigmoid P(correct) = 1 / (1 + exp(A*s + B)). The fitted
    coefficients are extracted into a PlattCalibrator for lightweight
    JSON-serializable prediction.

    Requires scikit-learn: pip install resolvekit[calibration]
    """
    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
    except ImportError:
        raise ImportError(_SKLEARN_INSTALL_MSG) from None

    scores, labels = _validate_inputs(scores, labels)

    X = np.array(scores).reshape(-1, 1)  # noqa: N806 (sklearn convention)
    y = np.array(labels)

    # High C = minimal regularization (let the sigmoid fit the data)
    lr = LogisticRegression(C=1e10, solver="lbfgs", max_iter=1000)
    lr.fit(X, y)

    # sklearn's LogisticRegression gives P(y=1) = 1 / (1 + exp(-(w*x + b)))
    # Our PlattCalibrator uses P(y=1) = 1 / (1 + exp(A*x + B))
    # So A = -w, B = -b
    w = float(lr.coef_[0][0])
    b = float(lr.intercept_[0])

    return PlattCalibrator(a=-w, b=-b, domain=domain, fit_n_samples=len(scores))


def fit_isotonic(
    scores: list[float], labels: list[int], domain: str
) -> IsotonicCalibrator:
    """Fit isotonic regression using sklearn.

    Uses sklearn's IsotonicRegression (PAVA algorithm) and extracts
    the fitted breakpoints into an IsotonicCalibrator for lightweight
    JSON-serializable prediction.

    Requires scikit-learn: pip install resolvekit[calibration]
    """
    try:
        from sklearn.isotonic import IsotonicRegression
    except ImportError:
        raise ImportError(_SKLEARN_INSTALL_MSG) from None

    scores, labels = _validate_inputs(scores, labels)

    ir = IsotonicRegression(out_of_bounds="clip", increasing=True)
    ir.fit(scores, labels)

    # Extract the fitted breakpoints
    xs = [float(x) for x in ir.X_thresholds_]
    ys = [float(y) for y in ir.y_thresholds_]

    return IsotonicCalibrator(xs=xs, ys=ys, domain=domain, fit_n_samples=len(scores))


def fit_stratified(
    scores: list[float],
    labels: list[int],
    query_lens: list[int],
    domain: str,
    *,
    short_query_threshold: int = 6,
    sub_method: Literal["platt", "isotonic"] = "platt",
) -> StratifiedCalibrator:
    """Fit separate calibrators for short and long queries.

    Splits examples by query length and fits independent sub-calibrators
    for each group. Falls back to fitting on the full dataset when a
    group has too few examples or lacks class diversity.

    Args:
        scores: Raw heuristic scores.
        labels: Binary labels (1=correct, 0=incorrect).
        query_lens: Length of each query string.
        domain: Domain identifier (e.g., "geo").
        short_query_threshold: Queries with len <= this use short_calibrator.
        sub_method: "platt" or "isotonic" for sub-calibrators.

    Returns:
        A StratifiedCalibrator with two fitted sub-calibrators.

    Requires scikit-learn: pip install resolvekit[calibration]
    """
    short_scores: list[float] = []
    short_labels: list[int] = []
    long_scores: list[float] = []
    long_labels: list[int] = []

    for s, label, ql in zip(scores, labels, query_lens, strict=False):
        if ql <= short_query_threshold:
            short_scores.append(s)
            short_labels.append(label)
        else:
            long_scores.append(s)
            long_labels.append(label)

    fit_fn = fit_platt if sub_method == "platt" else fit_isotonic

    # Fit each group; fall back to full dataset if group is too small
    if len(set(short_labels)) >= 2 and len(short_scores) >= 10:
        short_cal = fit_fn(short_scores, short_labels, domain=domain)
    else:
        short_cal = fit_fn(scores, labels, domain=domain)

    if len(set(long_labels)) >= 2 and len(long_scores) >= 10:
        long_cal = fit_fn(long_scores, long_labels, domain=domain)
    else:
        long_cal = fit_fn(scores, labels, domain=domain)

    return StratifiedCalibrator(
        short_query_threshold=short_query_threshold,
        short_calibrator=short_cal,
        long_calibrator=long_cal,
        domain=domain,
        fit_n_samples=len(scores),
    )


def fit_scoring_model(
    examples: list[LabeledExample],
    domain: str,
    *,
    regularization: float = 1.0,
) -> LogisticScoringModel:
    """Fit a logistic scoring model from labeled examples with features.

    Args:
        examples: List of LabeledExample instances with ``features_dict``
            and ``label`` populated.
        domain: Domain identifier (e.g. "geo").
        regularization: Inverse regularization strength (C in sklearn).
            Higher values = less regularization.

    Returns:
        A fitted LogisticScoringModel ready for JSON serialization.

    Requires scikit-learn: pip install resolvekit[calibration]
    """
    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
    except ImportError:
        raise ImportError(_SKLEARN_INSTALL_MSG) from None

    # Filter to examples that have both feature dict and label
    valid = [e for e in examples if e.features_dict is not None and e.label is not None]

    if len(valid) < 2:
        raise ValueError(
            f"Need at least 2 examples with features_dict and label, got {len(valid)}"
        )
    if len({e.label for e in valid}) < 2:
        raise ValueError(
            "Need both positive and negative examples to fit a scoring model"
        )

    feature_names = feature_names_for_domain(domain)
    X = np.array(  # noqa: N806 (sklearn convention)
        [features_dict_to_vector(feature_names, e.features_dict) for e in valid],
        dtype=float,
    )
    y = np.array([e.label for e in valid], dtype=int)

    lr = LogisticRegression(
        C=regularization,
        class_weight="balanced",
        solver="lbfgs",
        max_iter=1000,
    )
    lr.fit(X, y)

    weights = [float(w) for w in lr.coef_[0]]
    bias = float(lr.intercept_[0])

    return LogisticScoringModel(
        feature_names=feature_names,
        weights=weights,
        bias=bias,
        domain=domain,
        fit_n_samples=len(valid),
    )
