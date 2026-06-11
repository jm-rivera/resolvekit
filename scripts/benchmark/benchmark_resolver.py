#!/usr/bin/env python3
"""Benchmark resolver throughput and latency using a Parquet query set."""

from __future__ import annotations

import dataclasses
import functools
import time
from dataclasses import dataclass
from pathlib import Path

from resolvekit.core.api import Resolver
from resolvekit.core.model import ResolutionStatus
from scripts.benchmark.benchmark_common import (
    BenchmarkMetricsBase,
    BenchmarkRunInputs,
    QueryCase,
    WorkerConfig,
    WorkerRunOutcome,
    chunk_evenly,
    format_latency_block,
    format_pct,
    format_status_table,
    load_query_cases,
    normalize_domains,
    relative_to_cwd,
    render_latency_block,
    render_status_table,
    run_workers,
    validate_inputs,
    write_metrics_json,
)


@dataclass
class WorkerResult:
    latencies_ms: list[float]
    status_counts: dict[str, int]
    resolved_count: int
    expected_count: int
    exact_match_count: int
    error_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class LatencyBlock:
    """Latency summary for the resolver benchmark wire format."""

    min: float
    mean: float
    p50: float
    p95: float
    p99: float
    max: float


@dataclass(frozen=True, slots=True, kw_only=True)
class QualityBlock:
    """Quality summary for the resolver benchmark wire format."""

    resolved_count: int
    expected_count: int
    exact_match_count: int
    exact_match_rate_all_expected_pct: float | None
    exact_match_rate_resolved_pct: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolverBenchmarkMetrics(BenchmarkMetricsBase):
    """Typed metrics produced by the resolver benchmark.

    Extends :class:`~scripts.benchmark.benchmark_common.BenchmarkMetricsBase`
    with resolver-specific fields. Field names match the JSON wire-format keys
    so ``dataclasses.asdict()`` serializes without key translation.
    """

    dataset_path: str
    datapacks: list[str]
    throughput_qps: float
    latency_ms: LatencyBlock
    quality: QualityBlock


def run_worker(
    resolver: Resolver,
    query_cases: list[QueryCase],
    *,
    domains: list[str] | None,
) -> WorkerResult:
    """Benchmark a list of query cases and return aggregated per-worker metrics.

    This is a module-level function so it can be pickled for the
    ``ProcessPoolExecutor`` path (via :func:`functools.partial`).
    """
    latencies_ms: list[float] = []
    status_counts: dict[str, int] = {}
    resolved_count = 0
    expected_count = 0
    exact_match_count = 0
    error_count = 0

    for case in query_cases:
        start = time.perf_counter()
        try:
            result = resolver.resolve(case.query, domain=domains, to=None)
        except Exception:
            error_count += 1
            status_counts["exception"] = status_counts.get("exception", 0) + 1
            continue
        finally:
            latencies_ms.append((time.perf_counter() - start) * 1000.0)

        status_key = result.status.value
        status_counts[status_key] = status_counts.get(status_key, 0) + 1

        if result.status == ResolutionStatus.RESOLVED:
            resolved_count += 1
        if case.expected_ids:
            expected_count += 1
            if result.entity_id in case.expected_ids:
                exact_match_count += 1

    return WorkerResult(
        latencies_ms=latencies_ms,
        status_counts=status_counts,
        resolved_count=resolved_count,
        expected_count=expected_count,
        exact_match_count=exact_match_count,
        error_count=error_count,
    )


def _aggregate_worker_results(
    outcome: WorkerRunOutcome[WorkerResult],
) -> WorkerResult:
    worker_results = [pr.worker_result for pr in outcome.results]
    all_latencies = [
        value for result in worker_results for value in result.latencies_ms
    ]

    status_counts: dict[str, int] = {}
    resolved_count = 0
    expected_count = 0
    exact_match_count = 0
    exception_count = 0

    for result in worker_results:
        for status, count in result.status_counts.items():
            status_counts[status] = status_counts.get(status, 0) + count
        resolved_count += result.resolved_count
        expected_count += result.expected_count
        exact_match_count += result.exact_match_count
        exception_count += result.error_count

    return WorkerResult(
        latencies_ms=all_latencies,
        status_counts=status_counts,
        resolved_count=resolved_count,
        expected_count=expected_count,
        exact_match_count=exact_match_count,
        error_count=exception_count,
    )


def _build_metrics(
    *,
    inputs: BenchmarkRunInputs,
    datapacks: list[str | Path],
    warmup_count: int,
    outcome: WorkerRunOutcome[WorkerResult],
    aggregated: WorkerResult,
) -> ResolverBenchmarkMetrics:
    total_queries = len(aggregated.latencies_ms)
    elapsed_seconds = outcome.elapsed_seconds
    throughput_qps = total_queries / elapsed_seconds if elapsed_seconds > 0 else 0.0

    latency_dict = format_latency_block(latencies_ms=aggregated.latencies_ms)
    latency_block = LatencyBlock(
        min=latency_dict["min"],
        mean=latency_dict["mean"],
        p50=latency_dict["p50"],
        p95=latency_dict["p95"],
        p99=latency_dict["p99"],
        max=latency_dict["max"],
    )
    quality_block = QualityBlock(
        resolved_count=aggregated.resolved_count,
        expected_count=aggregated.expected_count,
        exact_match_count=aggregated.exact_match_count,
        exact_match_rate_all_expected_pct=(
            100.0 * aggregated.exact_match_count / aggregated.expected_count
            if aggregated.expected_count
            else None
        ),
        exact_match_rate_resolved_pct=(
            100.0 * aggregated.exact_match_count / aggregated.resolved_count
            if aggregated.resolved_count
            else None
        ),
    )

    return ResolverBenchmarkMetrics(
        workers=inputs.workers,
        warmup_queries=warmup_count,
        benchmark_queries=total_queries,
        resolver_init_seconds=round(outcome.init_seconds, 6),
        elapsed_seconds=round(elapsed_seconds, 6),
        # latencies_ms excluded from JSON output (write_metrics_json strips it).
        latencies_ms=aggregated.latencies_ms,
        statuses=aggregated.status_counts,
        exceptions=aggregated.error_count,
        # Paths relative to cwd ensure JSON artifacts are portable, not machine-specific.
        dataset_path=relative_to_cwd(path=inputs.csv),
        datapacks=[relative_to_cwd(path=p) for p in datapacks],
        throughput_qps=throughput_qps,
        latency_ms=latency_block,
        quality=quality_block,
    )


def _print_metrics(metrics: ResolverBenchmarkMetrics) -> None:
    print("=== ResolveKit Throughput Benchmark ===")
    print(f"Dataset: {metrics.dataset_path}")
    print(f"Datapacks: {', '.join(metrics.datapacks)}")
    print(f"Workers: {metrics.workers}")
    print(f"Resolver init: {metrics.resolver_init_seconds:.3f}s")
    print(f"Warmup queries: {metrics.warmup_queries}")
    print(f"Benchmark queries: {metrics.benchmark_queries}")
    print(f"Elapsed: {metrics.elapsed_seconds:.3f}s")
    print(f"Throughput: {metrics.throughput_qps:.2f} qps")
    print(render_latency_block(block=dataclasses.asdict(metrics.latency_ms)))
    status_rows = format_status_table(status_counts=metrics.statuses)
    print(render_status_table(rows=status_rows))
    quality = metrics.quality
    print(
        "Quality: "
        f"exact_match={quality.exact_match_count}/{quality.expected_count} "
        f"({format_pct(quality.exact_match_count, quality.expected_count)}), "
        f"exact_on_resolved={quality.exact_match_count}/{quality.resolved_count} "
        f"({format_pct(quality.exact_match_count, quality.resolved_count)})"
    )


def main(*, inputs: BenchmarkRunInputs) -> None:
    """Run the resolver throughput benchmark.

    Args:
        inputs: Benchmark configuration. Datapacks are resolved from
            ``inputs.datapacks`` and ``inputs.modules`` before running.
    """
    datapacks = validate_inputs(inputs=inputs)

    domains = normalize_domains(inputs.domains)
    query_cases = load_query_cases(
        dataset_path=inputs.csv,
        shuffle=inputs.shuffle,
        seed=inputs.seed,
        limit=inputs.limit,
    )

    warmup_count = min(max(inputs.warmup, 0), len(query_cases))
    warmup_cases = query_cases[:warmup_count]
    benchmark_queries = query_cases[warmup_count:]
    if not benchmark_queries:
        raise ValueError("No benchmark queries left after warmup.")

    config = WorkerConfig(
        datapacks=datapacks,
        routing_mode=inputs.routing_mode,
        packs=inputs.packs,
        domains=domains,
    )
    benchmark_chunks = chunk_evenly(benchmark_queries, inputs.workers)

    worker_fn = functools.partial(run_worker, domains=domains)
    outcome = run_workers(
        config=config,
        benchmark_chunks=benchmark_chunks,
        warmup_cases=warmup_cases,
        worker_fn=worker_fn,
    )

    aggregated = _aggregate_worker_results(outcome)
    metrics = _build_metrics(
        inputs=inputs,
        datapacks=datapacks,
        warmup_count=warmup_count,
        outcome=outcome,
        aggregated=aggregated,
    )
    _print_metrics(metrics)
    write_metrics_json(inputs.output_json, metrics)


if __name__ == "__main__":
    main(
        inputs=BenchmarkRunInputs(
            datapacks=[
                Path("src/resolvekit/_data/geo/countries"),
                Path("src/resolvekit/_data/geo/continental_unions"),
                Path("src/resolvekit/_data/geo/regions"),
            ],
            modules=None,
        )
    )
