"""CI assertion that the committed geo calibrator artifact is non-inverted."""

from __future__ import annotations

from pathlib import Path

import pytest

from resolvekit.calibration.models import load_calibrator

pytestmark = pytest.mark.calibration

_ARTIFACT = (
    Path(__file__).resolve().parents[2]
    / "src/resolvekit/_data/geo/countries/geo_calibrator.json"
)


def test_committed_geo_calibrator_is_monotonic() -> None:
    cal = load_calibrator(_ARTIFACT)
    assert cal.predict(0.9) > cal.predict(0.1), (
        "Committed geo calibrator is inverted: predict(0.9) <= predict(0.1). "
        "Retrain via `uv run python -m scripts.calibrate.calibrate_geo`."
    )
