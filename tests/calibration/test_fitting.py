"""Tests for calibration fitting routines."""

from __future__ import annotations

import pytest

from resolvekit.calibration.fitting import fit_isotonic, fit_platt, fit_stratified
from resolvekit.calibration.models import (
    IsotonicCalibrator,
    PlattCalibrator,
    StratifiedCalibrator,
)

pytestmark = pytest.mark.calibration

try:
    import sklearn  # noqa: F401

    _has_sklearn = True
except ImportError:
    _has_sklearn = False


@pytest.mark.skipif(not _has_sklearn, reason="scikit-learn required for Platt fitting")
class TestFitPlatt:
    def test_fit_platt_separable(self):
        # High scores -> label 1, low scores -> label 0
        scores = [0.8, 0.9, 0.85, 0.95, 0.1, 0.2, 0.15, 0.05]
        labels = [1, 1, 1, 1, 0, 0, 0, 0]
        cal = fit_platt(scores, labels, domain="geo")

        assert isinstance(cal, PlattCalibrator)
        # A should be negative (higher raw score -> higher probability)
        assert cal.a < 0
        # Prediction should be monotone: high score -> higher prob
        assert cal.predict(0.9) > cal.predict(0.1)

    def test_fit_platt_small_dataset(self):
        # 20 examples should work without crashing
        scores = [float(i) / 20 for i in range(20)]
        labels = [1 if i >= 10 else 0 for i in range(20)]
        cal = fit_platt(scores, labels, domain="org")
        assert isinstance(cal, PlattCalibrator)
        assert cal.fit_n_samples == 20

    def test_fit_platt_requires_both_classes(self):
        scores = [0.5, 0.6, 0.7]
        labels = [1, 1, 1]
        with pytest.raises(ValueError, match="both positive and negative"):
            fit_platt(scores, labels, domain="geo")

    def test_fit_platt_requires_min_examples(self):
        with pytest.raises(ValueError, match="at least 2"):
            fit_platt([0.5], [1], domain="geo")

    def test_fit_roundtrip_platt(self):
        # Fit on separable data, check Brier score is reasonable
        scores = [0.9, 0.85, 0.8, 0.75, 0.2, 0.15, 0.1, 0.05] * 5
        labels = [1, 1, 1, 1, 0, 0, 0, 0] * 5
        cal = fit_platt(scores, labels, domain="geo")

        predicted = [cal.predict(s) for s in scores]
        brier = sum(
            (p - lbl) ** 2 for p, lbl in zip(predicted, labels, strict=False)
        ) / len(labels)
        assert brier < 0.25


@pytest.mark.skipif(
    not _has_sklearn, reason="scikit-learn required for isotonic fitting"
)
class TestFitIsotonic:
    def test_fit_isotonic_monotone(self):
        scores = [float(i) / 20 for i in range(20)]
        labels = [1 if i >= 10 else 0 for i in range(20)]
        cal = fit_isotonic(scores, labels, domain="geo")

        assert isinstance(cal, IsotonicCalibrator)
        # ys should be non-decreasing
        for y1, y2 in zip(cal.ys, cal.ys[1:], strict=False):
            assert y2 >= y1 - 1e-12

    def test_fit_isotonic_sorted(self):
        scores = [0.9, 0.1, 0.5, 0.3, 0.7]
        labels = [1, 0, 1, 0, 1]
        cal = fit_isotonic(scores, labels, domain="org")

        # xs should be sorted ascending
        for x1, x2 in zip(cal.xs, cal.xs[1:], strict=False):
            assert x2 >= x1 - 1e-12

    def test_fit_isotonic_small_dataset(self):
        scores = [float(i) / 20 for i in range(20)]
        labels = [1 if i >= 10 else 0 for i in range(20)]
        cal = fit_isotonic(scores, labels, domain="geo")
        assert isinstance(cal, IsotonicCalibrator)
        assert cal.fit_n_samples == 20

    def test_fit_isotonic_requires_both_classes(self):
        with pytest.raises(ValueError, match="both positive and negative"):
            fit_isotonic([0.5, 0.6], [0, 0], domain="geo")

    def test_fit_isotonic_requires_min_examples(self):
        with pytest.raises(ValueError, match="at least 2"):
            fit_isotonic([0.5], [1], domain="geo")


@pytest.mark.skipif(
    not _has_sklearn, reason="scikit-learn required for stratified fitting"
)
class TestFitStratified:
    def test_fit_stratified_basic(self):
        scores = [0.8, 0.9, 0.85, 0.95, 0.1, 0.2, 0.15, 0.05] * 5
        labels = [1, 1, 1, 1, 0, 0, 0, 0] * 5
        query_lens = [3, 3, 3, 3, 3, 3, 3, 3] * 2 + [12, 12, 12, 12, 12, 12, 12, 12] * 3

        cal = fit_stratified(scores, labels, query_lens, domain="geo")

        assert isinstance(cal, StratifiedCalibrator)
        assert cal.domain == "geo"
        assert cal.fit_n_samples == 40
        assert isinstance(cal.short_calibrator, PlattCalibrator)
        assert isinstance(cal.long_calibrator, PlattCalibrator)

    def test_fit_stratified_fallback_small_group(self):
        # Only 2 short examples (too few) — should fall back to full dataset
        scores = [0.8, 0.2] + [0.9, 0.85, 0.1, 0.2, 0.15, 0.05] * 5
        labels = [1, 0] + [1, 1, 0, 0, 0, 0] * 5
        query_lens = [3, 3] + [12] * 30

        cal = fit_stratified(scores, labels, query_lens, domain="geo")

        assert isinstance(cal, StratifiedCalibrator)
        # short_calibrator should still be valid (fell back to full dataset)
        assert isinstance(cal.short_calibrator, PlattCalibrator)

    def test_fit_stratified_isotonic_sub_method(self):
        scores = [0.8, 0.9, 0.85, 0.95, 0.1, 0.2, 0.15, 0.05] * 5
        labels = [1, 1, 1, 1, 0, 0, 0, 0] * 5
        query_lens = [3, 3, 3, 3, 3, 3, 3, 3] * 2 + [12, 12, 12, 12, 12, 12, 12, 12] * 3

        cal = fit_stratified(
            scores, labels, query_lens, domain="geo", sub_method="isotonic"
        )

        assert isinstance(cal, StratifiedCalibrator)
        assert isinstance(cal.short_calibrator, IsotonicCalibrator)
        assert isinstance(cal.long_calibrator, IsotonicCalibrator)
