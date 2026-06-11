"""Calibration evaluation metrics."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from resolvekit.calibration.dataset import LabeledExample


class CalibrationBin(BaseModel):
    """Statistics for a single calibration bin."""

    model_config = ConfigDict(frozen=True)

    bin_lower: float
    bin_upper: float
    mean_predicted: float
    mean_observed: float
    count: int


class CalibrationMetrics(BaseModel):
    """Summary calibration metrics."""

    model_config = ConfigDict(frozen=True)

    brier_score: float
    log_loss: float
    ece: float
    adaptive_ece: float
    n_samples: int
    bins: list[CalibrationBin] = Field(default_factory=list)


def brier_score(predicted: list[float], actual: list[int]) -> float:
    """Compute Brier score: mean squared error between predicted probs and labels."""
    if not predicted:
        return 0.0
    return sum((p - a) ** 2 for p, a in zip(predicted, actual, strict=False)) / len(
        predicted
    )


def log_loss(predicted: list[float], actual: list[int], eps: float = 1e-15) -> float:
    """Compute log loss (negative log-likelihood).

    More sensitive to confident-but-wrong predictions than Brier score.
    """
    if not predicted:
        return 0.0
    clipped = [max(eps, min(1.0 - eps, p)) for p in predicted]
    return -sum(
        a * math.log(p) + (1 - a) * math.log(1 - p)
        for p, a in zip(clipped, actual, strict=False)
    ) / len(actual)


def adaptive_expected_calibration_error(
    predicted: list[float], actual: list[int], n_bins: int = 10
) -> float:
    """Compute ECE with equal-mass (equal-count) bins.

    Equal-width bins leave low-density regions nearly empty with imbalanced
    data. Equal-mass bins ensure each bin has enough examples for a
    meaningful calibration error estimate.
    """
    if not predicted:
        return 0.0
    sorted_pairs = sorted(zip(predicted, actual, strict=False))
    n = len(sorted_pairs)
    bin_size = max(1, n // n_bins)
    ece = 0.0
    for i in range(0, n, bin_size):
        chunk = sorted_pairs[i : i + bin_size]
        ps, ys = zip(*chunk, strict=False)
        ece += len(chunk) * abs(sum(ps) / len(ps) - sum(ys) / len(ys))
    return ece / n


def expected_calibration_error(
    predicted: list[float], actual: list[int], n_bins: int = 10
) -> float:
    """Compute Expected Calibration Error (ECE) using equal-width bins."""
    bins = calibration_curve_data(predicted, actual, n_bins=n_bins)
    n = len(predicted)
    if n == 0:
        return 0.0
    return sum(
        b.count * abs(b.mean_predicted - b.mean_observed) / n
        for b in bins
        if b.count > 0
    )


def calibration_curve_data(
    predicted: list[float], actual: list[int], n_bins: int = 10
) -> list[CalibrationBin]:
    """Build calibration curve data grouped into equal-width bins."""
    if not predicted:
        return []

    bin_width = 1.0 / n_bins
    bins: list[CalibrationBin] = []

    for i in range(n_bins):
        lower = i * bin_width
        upper = (i + 1) * bin_width

        in_bin = [
            (p, a)
            for p, a in zip(predicted, actual, strict=False)
            if lower <= p < upper or (i == n_bins - 1 and p == 1.0)
        ]

        if not in_bin:
            bins.append(
                CalibrationBin(
                    bin_lower=lower,
                    bin_upper=upper,
                    mean_predicted=0.0,
                    mean_observed=0.0,
                    count=0,
                )
            )
        else:
            ps, ys = zip(*in_bin, strict=False)
            bins.append(
                CalibrationBin(
                    bin_lower=lower,
                    bin_upper=upper,
                    mean_predicted=sum(ps) / len(ps),
                    mean_observed=sum(ys) / len(ys),
                    count=len(in_bin),
                )
            )

    return bins


def evaluate_calibration(
    predicted: list[float], actual: list[int], n_bins: int = 10
) -> CalibrationMetrics:
    """Compute full calibration metrics including Brier score, ECE, and bin data."""
    bins = calibration_curve_data(predicted, actual, n_bins=n_bins)
    return CalibrationMetrics(
        brier_score=brier_score(predicted, actual),
        log_loss=log_loss(predicted, actual),
        ece=expected_calibration_error(predicted, actual, n_bins=n_bins),
        adaptive_ece=adaptive_expected_calibration_error(
            predicted, actual, n_bins=n_bins
        ),
        n_samples=len(predicted),
        bins=bins,
    )


def find_f1_threshold(predicted: list[float], actual: list[int | None]) -> float:
    """Return the threshold in (0, 1) that maximises F1 over a 1..99 sweep.

    Defaults to 0.5 when no threshold improves on F1=0.
    """
    best_f1 = 0.0
    best_threshold = 0.5
    for t in [i / 100 for i in range(1, 100)]:
        tp = fp = fn = 0
        for p, lbl in zip(predicted, actual, strict=False):
            if p >= t:
                if lbl == 1:
                    tp += 1
                else:
                    fp += 1
            elif lbl == 1:
                fn += 1
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0
        )
        if f1 > best_f1:
            best_f1 = f1
            best_threshold = t
    return best_threshold


def find_exact_code_min_score(
    predicted: list[float],
    eval_examples: list[LabeledExample],
    *,
    percentile: float = 0.05,
) -> float | None:
    """Return the Nth-percentile model score among correct exact-code-hit examples.

    Returns None when no such examples exist in the eval set.
    """
    exact_code_scores = [
        p
        for p, e in zip(predicted, eval_examples, strict=False)
        if e.label == 1 and e.features_dict and e.features_dict.get("exact_code_hit")
    ]
    if not exact_code_scores:
        return None
    exact_code_scores.sort()
    idx = max(0, int(len(exact_code_scores) * percentile))
    return exact_code_scores[idx]
