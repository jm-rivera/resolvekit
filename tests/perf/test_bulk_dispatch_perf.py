"""Perf test: bulk() wall-clock across input shapes (pandas, polars, list, numpy).

Measures throughput and latency for a 100K-row dataset of country names and
asserts a sanity-floor on pandas throughput and overhead vs the list path.

Note: after warmup the resolver's LRU query cache will hold results for the
6 unique country names, so subsequent measured runs reflect the cache-warm
path. This is intentional — the benchmark gates the full dispatch overhead
(dedup, broadcast, shape reconstruction) not cold-start resolution.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable

import pytest

COUNTRY_NAMES = [
    "United States",
    "Germany",
    "France",
    "Japan",
    "South Africa",
    "United Kingdom",
]
N_ROWS = 100_000
WARMUP_RUNS = 3
# 20 runs gives a meaningful p95 (19th of 20 sorted values).
MEASURED_RUNS = 20
# pandas wraps a Python list into a Series; some overhead is expected.
# 5x vs the raw list path is a generous upper bound — pandas overhead
# on a 100K-row dispatch should be negligible compared to resolution work.
MAX_PANDAS_OVERHEAD = 5.0
MIN_THROUGHPUT = 500  # rows/sec sanity floor


def _make_list(pool: list[str], n: int) -> list[str]:
    cycle_len = len(pool)
    return [pool[i % cycle_len] for i in range(n)]


def _measure(fn: Callable[[], None], runs: int) -> list[float]:
    """Run *fn* *runs* times and return wall-clock seconds per run."""
    times: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return times


@pytest.mark.slow
def test_bulk_dispatch_pandas_overhead_and_throughput() -> None:
    """pandas/list overhead ratio <= MAX_PANDAS_OVERHEAD and pandas throughput >= MIN_THROUGHPUT."""
    import resolvekit as rk

    resolver = rk.default()

    raw_list = _make_list(COUNTRY_NAMES, N_ROWS)

    # Build input shapes — only import what's available.
    shapes: dict[str, object] = {"list": raw_list}

    try:
        import pandas as pd

        shapes["pandas"] = pd.Series(raw_list)
    except ImportError:
        pass

    try:
        import polars as pl

        shapes["polars"] = pl.Series(raw_list)
    except ImportError:
        pass

    try:
        import numpy as np

        shapes["numpy"] = np.array(raw_list, dtype=object)
    except ImportError:
        pass

    from resolvekit.core.api.bulk import _bulk_dispatch

    results: dict[str, tuple[float, float, float]] = {}

    for shape_name, values in shapes.items():

        def _call(v: object = values) -> None:
            _bulk_dispatch(
                resolver=resolver,
                values=v,
                to="iso3",
                output="series",
                domain=None,
                context=None,
                from_system=None,
                not_found="null",
                on_error="null",
                on_ambiguous="null",
            )

        for _ in range(WARMUP_RUNS):
            _call()

        run_times = _measure(_call, MEASURED_RUNS)  # type: ignore[arg-type]
        run_times_ms = [t * 1000 for t in run_times]

        p50_ms = statistics.median(run_times_ms)
        tput = N_ROWS / statistics.median(run_times)
        results[shape_name] = (p50_ms, tput, statistics.median(run_times))

    pandas_p50_ms, pandas_tput, _ = results.get("pandas", (None, None, None))  # type: ignore[assignment]
    list_p50_ms, _, _ = results.get("list", (None, None, None))  # type: ignore[assignment]

    if pandas_p50_ms is None:
        pytest.skip("pandas not available")

    assert pandas_tput >= MIN_THROUGHPUT, (
        f"pandas throughput {pandas_tput:,.0f} rows/sec < {MIN_THROUGHPUT:,} rows/sec floor"
    )

    if list_p50_ms is not None:
        ratio = pandas_p50_ms / list_p50_ms
        assert ratio <= MAX_PANDAS_OVERHEAD, (
            f"pandas/list overhead ratio {ratio:.2f}x exceeds {MAX_PANDAS_OVERHEAD:.0f}x limit "
            f"(pandas p50={pandas_p50_ms:.1f} ms, list p50={list_p50_ms:.1f} ms)"
        )
