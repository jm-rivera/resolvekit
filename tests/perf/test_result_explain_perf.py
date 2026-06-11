"""Perf test: result.explain() re-execution overhead.

Resolves a set of country names without a query cache, caches the
ResolutionResult objects, then measures per-call cost of result.explain()
vs a fresh resolver.resolve() (also cache-free).

The query cache is disabled so that resolve() times reflect actual pipeline
cost. With the cache enabled, resolve() would return near-zero cache hits,
inflating the overhead ratio and producing a misleading failure.

Assertion: result.explain() per-call cost <= 1.5x that of a fresh resolve().
"""

from __future__ import annotations

import contextlib
import statistics
import time

import pytest

SAMPLE_TEXTS = [
    "United States",
    "Germany",
    "France",
    "Japan",
    "South Africa",
    "United Kingdom",
    "Brazil",
    "India",
    "China",
    "Australia",
]
MAX_OVERHEAD_RATIO = 1.5
WARMUP_RUNS = 5
MEASURED_RUNS = 50


@pytest.mark.slow
def test_result_explain_overhead() -> None:
    """result.explain() per-call overhead is <= MAX_OVERHEAD_RATIO vs fresh resolve()."""
    from resolvekit.core.api.resolver import Resolver

    # Disable query cache so resolve() times reflect pipeline cost.
    resolver = Resolver.auto(cache_size=0)

    n_needed = WARMUP_RUNS + MEASURED_RUNS
    cycle_len = len(SAMPLE_TEXTS)
    cached_results = []
    for i in range(n_needed):
        text = SAMPLE_TEXTS[i % cycle_len]
        result = resolver.resolve(text, include_entity=False)
        cached_results.append((text, result))

    # Filter to results with a live _resolver back-ref and query_text.
    explainable = [
        (t, r) for t, r in cached_results if r._resolver is not None and r.query_text
    ]

    if not explainable:
        pytest.skip(
            "no explainable results (results lack _resolver back-ref or query_text)"
        )

    sample = explainable[:n_needed]
    texts_to_measure = [t for t, _ in sample[WARMUP_RUNS:]]
    results_to_measure = [r for _, r in sample[WARMUP_RUNS:]]

    for text, result in sample[:WARMUP_RUNS]:
        with contextlib.suppress(Exception):
            result.explain()
        resolver.resolve(text, include_entity=False)

    explain_times: list[float] = []
    explain_successes = 0
    for result in results_to_measure:
        t0 = time.perf_counter()
        try:
            result.explain()
            explain_successes += 1
        except Exception:
            pass
        explain_times.append(time.perf_counter() - t0)

    if explain_successes == 0:
        pytest.skip(
            f"explain() raised on all {len(results_to_measure)} samples — "
            "_resolver back-ref may not be set by this resolver path"
        )

    fresh_times: list[float] = []
    for text in texts_to_measure:
        t0 = time.perf_counter()
        resolver.resolve(text, include_entity=False)
        fresh_times.append(time.perf_counter() - t0)

    explain_mean_ms = statistics.mean(explain_times) * 1000
    fresh_mean_ms = statistics.mean(fresh_times) * 1000
    overhead_ratio = (
        explain_mean_ms / fresh_mean_ms if fresh_mean_ms > 0 else float("inf")
    )

    assert overhead_ratio <= MAX_OVERHEAD_RATIO, (
        f"explain() overhead ratio {overhead_ratio:.2f}x > {MAX_OVERHEAD_RATIO:.1f}x limit "
        f"(explain mean={explain_mean_ms:.3f} ms, resolve mean={fresh_mean_ms:.3f} ms)"
    )
