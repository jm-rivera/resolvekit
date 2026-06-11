"""Perf test: BulkResult dataclass construction cost at N ∈ {100, 10K, 1M}.

BulkResult is a @dataclass(slots=True, frozen=True), NOT pydantic, so
construction should be O(1) wrt collection size — the tuple assignment does
not iterate or validate per-item.

Assertion: Construction time difference between N=10K and N=1M is < 2x
(i.e., construction is effectively O(1) wrt collection size).
"""

from __future__ import annotations

import time

import pytest

from resolvekit.core.model.bulk_result import BulkResult
from resolvekit.core.model.result import ReasonCode, ResolutionResult, ResolutionStatus

SIZES = [100, 10_000, 1_000_000]
WARMUP_RUNS = 3
MEASURED_RUNS = 5
MAX_RATIO = 2.0  # 10K → 1M construction must be < 2x slower


def _make_source(n: int) -> tuple[ResolutionResult, ...]:
    """Build a tuple of *n* minimal ResolutionResult instances."""
    sentinel = ResolutionResult(
        status=ResolutionStatus.NO_MATCH,
        reasons=[ReasonCode.NO_CANDIDATES],
    )
    return (sentinel,) * n


def _measure_construction(source: tuple[ResolutionResult, ...]) -> float:
    """Return median wall-clock seconds for BulkResult construction.

    ``values_list`` is pre-computed outside the timed section so we measure
    only the dataclass ``__init__`` assignment, not the O(N) ``list()`` copy.
    """
    values_list = list(source)
    times: list[float] = []

    for _ in range(WARMUP_RUNS):
        BulkResult(values=values_list, source=source, kind="list")

    for _ in range(MEASURED_RUNS):
        t0 = time.perf_counter()
        BulkResult(values=values_list, source=source, kind="list")
        times.append(time.perf_counter() - t0)

    times.sort()
    mid = len(times) // 2
    return times[mid]


@pytest.mark.slow
def test_bulk_result_construction_is_o1() -> None:
    """BulkResult construction time 10K→1M ratio < MAX_RATIO (effectively O(1))."""
    results: dict[int, float] = {}
    for n in SIZES:
        source = _make_source(n)
        results[n] = _measure_construction(source)

    t10k = results[10_000]
    t1m = results[1_000_000]
    ratio = t1m / t10k if t10k > 0 else float("inf")

    assert ratio < MAX_RATIO, (
        f"BulkResult construction 10K→1M ratio {ratio:.2f}x >= {MAX_RATIO:.0f}x — "
        f"construction appears to scale with N (N=10K: {t10k * 1000:.3f} ms, "
        f"N=1M: {t1m * 1000:.3f} ms)"
    )
