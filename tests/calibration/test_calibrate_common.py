"""Tests for pick_best_and_save in calibrate_common — monotonicity guard."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import pytest

from resolvekit.calibration.evaluation import CalibrationMetrics
from resolvekit.calibration.models import Calibrator, PlattCalibrator
from scripts.calibrate.calibrate_common import (
    CalibrationMetricKey,
    pick_best_and_save,
)

pytestmark = pytest.mark.calibration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Method(StrEnum):
    INVERTED = "inverted"
    MONOTONE = "monotone"
    INVERTED_B = "inverted_b"


def _metrics(adaptive_ece: float) -> CalibrationMetrics:
    """Minimal CalibrationMetrics for use in pick_best_and_save results."""
    return CalibrationMetrics(
        brier_score=0.2,
        log_loss=0.3,
        ece=0.1,
        adaptive_ece=adaptive_ece,
        n_samples=20,
    )


# PlattCalibrator(a=+5, b=-2) is inverted: predict(0.9) < predict(0.1)
# sigmoid(5*0.9 - 2) ≈ 0.076  <  sigmoid(5*0.1 - 2) ≈ 0.818
_INVERTED_CAL = PlattCalibrator(a=5, b=-2, domain="geo", fit_n_samples=10)

# PlattCalibrator(a=-5, b=2) is monotone: predict(0.9) > predict(0.1)
# sigmoid(-5*0.9 + 2) ≈ 0.924  >  sigmoid(-5*0.1 + 2) ≈ 0.182
_MONOTONE_CAL = PlattCalibrator(a=-5, b=2, domain="geo", fit_n_samples=10)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_inverted_calibrator_direction() -> None:
    """Sanity-check the test calibrators have the expected monotonicity."""
    assert _INVERTED_CAL.predict(0.9) <= _INVERTED_CAL.predict(0.1), (
        "Test fixture _INVERTED_CAL should be inverted"
    )
    assert _MONOTONE_CAL.predict(0.9) > _MONOTONE_CAL.predict(0.1), (
        "Test fixture _MONOTONE_CAL should be monotone"
    )


def test_pick_best_rejects_all_inverted(tmp_path: Path) -> None:
    """All-inverted results dict raises ValueError; nothing written to output_path."""
    output_path = tmp_path / "best.json"
    results: dict[_Method, tuple[Calibrator, CalibrationMetrics]] = {
        _Method.INVERTED: (_INVERTED_CAL, _metrics(0.05)),
        _Method.INVERTED_B: (
            PlattCalibrator(a=3, b=-1, domain="geo", fit_n_samples=10),
            _metrics(0.08),
        ),
    }

    with pytest.raises(ValueError, match="inverted"):
        pick_best_and_save(
            results=results,
            output_path=output_path,
            metric=CalibrationMetricKey.ADAPTIVE_ECE,
        )

    assert not output_path.exists(), (
        "No file should be written when all variants are inverted"
    )


def test_pick_best_filters_inverted_keeps_monotone(tmp_path: Path) -> None:
    """Monotone variant is selected even when the inverted one has lower ECE."""
    output_path = tmp_path / "best.json"

    # The inverted variant has better (lower) ECE — without the guard it would win.
    results: dict[_Method, tuple[Calibrator, CalibrationMetrics]] = {
        _Method.INVERTED: (_INVERTED_CAL, _metrics(adaptive_ece=0.01)),
        _Method.MONOTONE: (_MONOTONE_CAL, _metrics(adaptive_ece=0.10)),
    }

    best_key, best_cal = pick_best_and_save(
        results=results,
        output_path=output_path,
        metric=CalibrationMetricKey.ADAPTIVE_ECE,
    )

    assert best_key == _Method.MONOTONE, (
        f"Expected monotone variant to be selected, got {best_key}"
    )
    assert best_cal is _MONOTONE_CAL
    assert output_path.exists(), "Best calibrator should be written to output_path"
