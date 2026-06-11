"""Typed metric result dataclasses.

Field declaration order matches the dict insertion order in
``benchmarks.core.metrics`` so that ``dataclasses.asdict`` reproduces
byte-identical JSON for all existing keys.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass


@dataclass(frozen=True)
class AccuracyResult:
    """Return type of ``accuracy_metrics``."""

    # Field order mirrors accuracy_metrics() dict insertion order.
    overall: float
    by_capability: dict[str, float]
    by_language: dict[str, float]
    by_difficulty: dict[str, float]
    by_entity_type: dict[str, float]
    wrong_match_rate: float
    abstention_precision: float
    abstention_recall: float
    error_rate: float
    row_count: int
    # Wilson 95% CI on overall accuracy; None when row_count == 0.
    accuracy_ci_low: float | None = None
    accuracy_ci_high: float | None = None
    # Row count per entity_type stratum (total rows, not just correct).
    # Empty dict in older JSON payloads that pre-date this field.
    by_entity_type_n: dict[str, int] = dataclasses.field(default_factory=dict)
    # Wrong-match rate per entity_type (wrong matches / total rows in type).
    # Empty dict in older JSON payloads that pre-date this field.
    by_entity_type_wrong_match: dict[str, float] = dataclasses.field(
        default_factory=dict
    )


@dataclass(frozen=True)
class LatencyResult:
    """Return type of ``latency_metrics``."""

    # Field order mirrors latency_metrics() dict insertion order.
    p50: float
    p95: float | None
    p99: float | None
    mean: float
    min: float
    max: float
    # Number of observations used; p95/p99 are None when sample_count < 20.
    sample_count: int = 0


@dataclass(frozen=True)
class ReliabilityBin:
    """One calibration bin in the reliability diagram."""

    # Field order mirrors the bin dict in calibration_metrics().
    lower: float
    upper: float
    count: int
    mean_confidence: float
    observed_accuracy: float


@dataclass(frozen=True)
class CalibrationResult:
    """Return type of ``calibration_metrics``."""

    # Field order mirrors calibration_metrics() dict insertion order.
    n_with_confidence: int
    ece: float | None
    brier: float | None
    reliability_bins: tuple[ReliabilityBin, ...]


@dataclass(frozen=True)
class ToolMetrics:
    """Per-(tool, dataset) aggregated metrics assembled by ``_run_combo``."""

    accuracy: AccuracyResult
    ambiguity_recall: float
    latency_ms: LatencyResult
    throughput_qps: float
    effective_warmup: int
    cold_start_ms: float | None
    peak_rss_mb: float | None
    wheel_size_mb: float | None
    data_size_mb: float | None
    calibration: CalibrationResult | None
