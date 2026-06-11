"""Tests for calibration model classes."""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import pytest

from resolvekit.calibration.models import (
    IsotonicCalibrator,
    PlattCalibrator,
    StratifiedCalibrator,
    load_calibrator,
    save_calibrator,
)


class TestPlattCalibrator:
    def test_platt_predict_known_values(self):
        cal = PlattCalibrator(a=-2.0, b=1.0, domain="geo", fit_n_samples=100)
        # logit = -2 * 0.5 + 1 = 0 -> 1/(1+e^0) = 0.5
        result = cal.predict(0.5)
        assert abs(result - 0.5) < 1e-9

        # logit = -2 * 0.0 + 1 = 1 -> 1/(1+e^1)
        result2 = cal.predict(0.0)
        expected = 1.0 / (1.0 + math.exp(1.0))
        assert abs(result2 - expected) < 1e-9

    def test_platt_predict_overflow(self):
        cal = PlattCalibrator(a=-100.0, b=0.0, domain="geo", fit_n_samples=50)
        # Very large positive logit -> near 1.0 (clamped at 30)
        result = cal.predict(1.0)
        assert 0.0 <= result <= 1.0
        assert not math.isnan(result)
        assert not math.isinf(result)

    def test_platt_model_frozen(self):
        cal = PlattCalibrator(a=-2.0, b=1.0, domain="geo", fit_n_samples=100)
        with pytest.raises(Exception):
            cal.a = 5.0  # type: ignore[misc]

    def test_platt_json_roundtrip(self):
        original = PlattCalibrator(a=-1.5, b=0.3, domain="geo", fit_n_samples=200)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "calibrator.json"
            save_calibrator(original, path)
            loaded = load_calibrator(path)

        assert isinstance(loaded, PlattCalibrator)
        assert loaded.a == original.a
        assert loaded.b == original.b
        assert loaded.domain == original.domain
        assert loaded.fit_n_samples == original.fit_n_samples


class TestIsotonicCalibrator:
    def test_isotonic_predict_interpolation(self):
        cal = IsotonicCalibrator(
            xs=[0.0, 0.5, 1.0],
            ys=[0.1, 0.5, 0.9],
            domain="org",
            fit_n_samples=100,
        )
        # Midpoint between xs[0]=0.0 and xs[1]=0.5 should interpolate
        result = cal.predict(0.25)
        assert abs(result - 0.3) < 1e-9

    def test_isotonic_predict_boundary_clamp(self):
        cal = IsotonicCalibrator(
            xs=[0.2, 0.8],
            ys=[0.1, 0.9],
            domain="geo",
            fit_n_samples=50,
        )
        # Below range clamps to ys[0]
        assert cal.predict(0.0) == 0.1
        # Above range clamps to ys[-1]
        assert cal.predict(1.0) == 0.9

    def test_isotonic_predict_empty(self):
        cal = IsotonicCalibrator(xs=[], ys=[], domain="geo", fit_n_samples=0)
        assert cal.predict(0.7) == 0.7

    def test_isotonic_predict_single_point(self):
        cal = IsotonicCalibrator(xs=[0.5], ys=[0.6], domain="geo", fit_n_samples=1)
        assert cal.predict(0.3) == 0.6
        assert cal.predict(0.5) == 0.6
        assert cal.predict(0.9) == 0.6

    def test_isotonic_json_roundtrip(self):
        original = IsotonicCalibrator(
            xs=[0.0, 0.5, 1.0],
            ys=[0.1, 0.5, 0.9],
            domain="org",
            fit_n_samples=80,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "calibrator.json"
            save_calibrator(original, path)
            loaded = load_calibrator(path)

        assert isinstance(loaded, IsotonicCalibrator)
        assert loaded.xs == original.xs
        assert loaded.ys == original.ys
        assert loaded.domain == original.domain
        assert loaded.fit_n_samples == original.fit_n_samples


class TestStratifiedCalibrator:
    def test_dispatches_by_length(self):
        short_cal = PlattCalibrator(a=-2.0, b=1.0, domain="geo", fit_n_samples=50)
        long_cal = PlattCalibrator(a=-5.0, b=2.0, domain="geo", fit_n_samples=50)
        strat = StratifiedCalibrator(
            short_query_threshold=6,
            short_calibrator=short_cal,
            long_calibrator=long_cal,
            domain="geo",
            fit_n_samples=100,
        )

        short_result = strat.predict(0.7, query_len=3)
        long_result = strat.predict(0.7, query_len=15)
        assert short_result != long_result
        assert abs(short_result - short_cal.predict(0.7)) < 1e-9
        assert abs(long_result - long_cal.predict(0.7)) < 1e-9

    def test_boundary_inclusive(self):
        short_cal = PlattCalibrator(a=-2.0, b=1.0, domain="geo", fit_n_samples=50)
        long_cal = PlattCalibrator(a=-5.0, b=2.0, domain="geo", fit_n_samples=50)
        strat = StratifiedCalibrator(
            short_query_threshold=6,
            short_calibrator=short_cal,
            long_calibrator=long_cal,
            domain="geo",
            fit_n_samples=100,
        )

        # query_len=6 should use short (<=6)
        at_boundary = strat.predict(0.7, query_len=6)
        assert abs(at_boundary - short_cal.predict(0.7)) < 1e-9

        # query_len=7 should use long
        above_boundary = strat.predict(0.7, query_len=7)
        assert abs(above_boundary - long_cal.predict(0.7)) < 1e-9

    def test_none_query_len_uses_long(self):
        short_cal = PlattCalibrator(a=-2.0, b=1.0, domain="geo", fit_n_samples=50)
        long_cal = PlattCalibrator(a=-5.0, b=2.0, domain="geo", fit_n_samples=50)
        strat = StratifiedCalibrator(
            short_query_threshold=6,
            short_calibrator=short_cal,
            long_calibrator=long_cal,
            domain="geo",
            fit_n_samples=100,
        )

        result = strat.predict(0.7, query_len=None)
        assert abs(result - long_cal.predict(0.7)) < 1e-9

    def test_json_roundtrip(self):
        original = StratifiedCalibrator(
            short_query_threshold=6,
            short_calibrator=PlattCalibrator(
                a=-2.0, b=1.0, domain="geo", fit_n_samples=50
            ),
            long_calibrator=IsotonicCalibrator(
                xs=[0.0, 1.0], ys=[0.1, 0.9], domain="geo", fit_n_samples=50
            ),
            domain="geo",
            fit_n_samples=100,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "strat.json"
            save_calibrator(original, path)
            loaded = load_calibrator(path)

        assert isinstance(loaded, StratifiedCalibrator)
        assert loaded.short_query_threshold == 6
        assert isinstance(loaded.short_calibrator, PlattCalibrator)
        assert isinstance(loaded.long_calibrator, IsotonicCalibrator)

    def test_platt_ignores_query_len(self):
        cal = PlattCalibrator(a=-2.0, b=1.0, domain="geo", fit_n_samples=100)
        assert cal.predict(0.7) == cal.predict(0.7, query_len=3)


class TestLoadCalibrator:
    def test_load_calibrator_unknown_method(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bad.json"
            path.write_text(json.dumps({"method": "unknown_method", "domain": "geo"}))
            with pytest.raises((ValueError, Exception)):
                load_calibrator(path)
