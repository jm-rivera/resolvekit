"""Tests for calibration evaluation metrics."""

from __future__ import annotations

from resolvekit.calibration.evaluation import (
    CalibrationMetrics,
    adaptive_expected_calibration_error,
    brier_score,
    calibration_curve_data,
    evaluate_calibration,
    expected_calibration_error,
    log_loss,
)


class TestBrierScore:
    def test_brier_perfect(self):
        predicted = [1.0, 1.0, 0.0, 0.0]
        actual = [1, 1, 0, 0]
        assert brier_score(predicted, actual) == 0.0

    def test_brier_worst(self):
        predicted = [0.0, 0.0, 1.0, 1.0]
        actual = [1, 1, 0, 0]
        assert brier_score(predicted, actual) == 1.0

    def test_brier_empty(self):
        assert brier_score([], []) == 0.0


class TestExpectedCalibrationError:
    def test_ece_perfect(self):
        # Perfect calibration: predicted prob matches observed frequency
        predicted = [0.0, 0.0, 1.0, 1.0]
        actual = [0, 0, 1, 1]
        ece = expected_calibration_error(predicted, actual, n_bins=2)
        assert ece < 0.01

    def test_ece_empty(self):
        assert expected_calibration_error([], []) == 0.0


class TestCalibrationCurveData:
    def test_calibration_curve_bins(self):
        predicted = [0.1, 0.2, 0.6, 0.8]
        actual = [0, 0, 1, 1]
        bins = calibration_curve_data(predicted, actual, n_bins=10)

        assert len(bins) == 10
        # Check structure
        for b in bins:
            assert b.bin_lower < b.bin_upper
            assert b.count >= 0

        # Bins with data
        bins_with_data = [b for b in bins if b.count > 0]
        assert len(bins_with_data) >= 2

    def test_calibration_curve_empty(self):
        result = calibration_curve_data([], [])
        assert result == []


class TestLogLoss:
    def test_log_loss_perfect(self):
        predicted = [1.0, 1.0, 0.0, 0.0]
        actual = [1, 1, 0, 0]
        assert log_loss(predicted, actual) < 0.001

    def test_log_loss_worst(self):
        predicted = [0.0, 0.0, 1.0, 1.0]
        actual = [1, 1, 0, 0]
        # Should be very high (clipped, not infinite)
        assert log_loss(predicted, actual) > 30.0

    def test_log_loss_empty(self):
        assert log_loss([], []) == 0.0

    def test_log_loss_midpoint(self):
        # All predictions at 0.5 → log loss = -log(0.5) ≈ 0.693
        predicted = [0.5, 0.5, 0.5, 0.5]
        actual = [0, 1, 0, 1]
        assert abs(log_loss(predicted, actual) - 0.6931) < 0.001


class TestAdaptiveECE:
    def test_adaptive_ece_perfect(self):
        predicted = [0.0, 0.0, 1.0, 1.0]
        actual = [0, 0, 1, 1]
        assert adaptive_expected_calibration_error(predicted, actual, n_bins=2) < 0.01

    def test_adaptive_ece_empty(self):
        assert adaptive_expected_calibration_error([], []) == 0.0

    def test_adaptive_ece_uses_equal_mass(self):
        # 8 examples, 4 bins → 2 per bin
        predicted = [0.1, 0.2, 0.3, 0.4, 0.7, 0.8, 0.9, 0.95]
        actual = [0, 0, 0, 0, 1, 1, 1, 1]
        result = adaptive_expected_calibration_error(predicted, actual, n_bins=4)
        assert 0.0 <= result <= 1.0


class TestEvaluateCalibration:
    def test_evaluate_integration(self):
        predicted = [0.1, 0.4, 0.6, 0.9]
        actual = [0, 0, 1, 1]
        metrics = evaluate_calibration(predicted, actual, n_bins=4)

        assert isinstance(metrics, CalibrationMetrics)
        assert metrics.n_samples == 4
        assert 0.0 <= metrics.brier_score <= 1.0
        assert 0.0 <= metrics.ece <= 1.0
        assert metrics.log_loss >= 0.0
        assert 0.0 <= metrics.adaptive_ece <= 1.0
        assert len(metrics.bins) == 4
