"""Parity tests for the shared percentile primitive.

Pins the same values as test_metrics.py to verify the percentile implementation
is byte-identical across both locations.
"""

from __future__ import annotations

import pytest

from benchmarks.core._math import percentile


def test_percentile_empty() -> None:
    assert percentile([], 50) == 0.0


def test_percentile_p_le_0_returns_min() -> None:
    assert percentile([3.0, 1.0, 2.0], 0) == pytest.approx(1.0)
    assert percentile([3.0, 1.0, 2.0], -5) == pytest.approx(1.0)


def test_percentile_p_ge_100_returns_max() -> None:
    assert percentile([3.0, 1.0, 2.0], 100) == pytest.approx(3.0)
    assert percentile([3.0, 1.0, 2.0], 200) == pytest.approx(3.0)


def test_percentile_exact_rank() -> None:
    # 3 values, p=50: rank = (3-1)*0.5 = 1.0 → exact index, value = 20.0.
    assert percentile([10.0, 20.0, 30.0], 50) == pytest.approx(20.0)


def test_percentile_fractional_interpolation() -> None:
    # 4 values, p=50: rank = (4-1)*0.5 = 1.5 → interpolate between indices 1 and 2.
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == pytest.approx(2.5)
