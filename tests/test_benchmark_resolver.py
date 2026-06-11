from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock

from resolvekit.core.model import ResolutionStatus
from scripts.benchmark.benchmark_common import QueryCase
from scripts.benchmark.benchmark_resolver import (
    LatencyBlock,
    QualityBlock,
    ResolverBenchmarkMetrics,
    run_worker,
)


def test_resolver_metrics_serializes_to_expected_keys() -> None:
    """Wire format keys must stay stable; this test pins the JSON shape."""
    metrics = ResolverBenchmarkMetrics(
        workers=1,
        warmup_queries=10,
        benchmark_queries=100,
        resolver_init_seconds=0.123456,
        elapsed_seconds=1.234567,
        latencies_ms=[1.0, 2.0, 3.0],
        statuses={"resolved": 95, "no_match": 5},
        exceptions=0,
        dataset_path="benchmarks/data/geo_countries_en.parquet",
        datapacks=["src/resolvekit/_data/geo/countries"],
        throughput_qps=81.0,
        latency_ms=LatencyBlock(min=1.0, mean=2.0, p50=2.0, p95=3.0, p99=3.0, max=3.0),
        quality=QualityBlock(
            resolved_count=95,
            expected_count=100,
            exact_match_count=80,
            exact_match_rate_all_expected_pct=80.0,
            exact_match_rate_resolved_pct=84.21,
        ),
    )

    serialized = dataclasses.asdict(metrics)
    serialized.pop("latencies_ms", None)

    # Top-level keys from the JSON wire format.
    expected_top_level = {
        "workers",
        "warmup_queries",
        "benchmark_queries",
        "resolver_init_seconds",
        "elapsed_seconds",
        "statuses",
        "exceptions",
        "dataset_path",
        "datapacks",
        "throughput_qps",
        "latency_ms",
        "quality",
    }
    assert set(serialized.keys()) == expected_top_level

    assert set(serialized["latency_ms"].keys()) == {
        "min",
        "mean",
        "p50",
        "p95",
        "p99",
        "max",
    }
    assert set(serialized["quality"].keys()) == {
        "resolved_count",
        "expected_count",
        "exact_match_count",
        "exact_match_rate_all_expected_pct",
        "exact_match_rate_resolved_pct",
    }


def test_run_worker_counts_hit_when_resolver_returns_any_expected_id() -> None:
    """A multi-id QueryCase counts as a hit when the resolver returns any expected id."""
    case = QueryCase(
        query="Tokyo",
        expected_ids=("geo.admin1/JPN-13", "geo.city/Q1490"),
        category=None,
        difficulty=None,
    )

    resolver = MagicMock()
    result_mock = MagicMock()
    result_mock.status = ResolutionStatus.RESOLVED
    result_mock.entity_id = "geo.city/Q1490"  # second id in expected_ids
    resolver.resolve.return_value = result_mock

    worker_result = run_worker(resolver, [case], domains=None)

    assert worker_result.expected_count == 1
    assert worker_result.exact_match_count == 1
