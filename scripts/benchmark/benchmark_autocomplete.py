#!/usr/bin/env python3
"""Benchmark autocomplete-style runtime behavior from a CSV query set."""

from __future__ import annotations

import functools
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean as _mean

from resolvekit.core.api import Resolver
from resolvekit.core.model import ResolutionResult
from scripts.benchmark.benchmark_common import (
    BenchmarkConfigurationError,
    BenchmarkMetricsBase,
    BenchmarkRunInputs,
    QueryCase,
    WorkerConfig,
    WorkerRunOutcome,
    chunk_evenly,
    format_status_table,
    load_query_cases,
    normalize_domains,
    percentile,
    relative_to_cwd,
    render_status_table,
    run_workers,
    validate_inputs,
    write_metrics_json,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class AutocompleteRunInputs(BenchmarkRunInputs):
    """Benchmark inputs for the autocomplete script.

    Extends :class:`~scripts.benchmark.benchmark_common.BenchmarkRunInputs` with the
    autocomplete-specific fields.

    Attributes:
        min_prefix_len: Minimum prefix length to evaluate.  Defaults to 2.
        mode: ``"resolve"`` (default, back-compat) calls ``resolver.resolve()``;
            ``"suggest"`` calls ``resolver.suggest()``.
        suggest_top_k: ``top_k`` passed to ``resolver.suggest()`` when
            ``mode == "suggest"``.
    """

    min_prefix_len: int = 2
    mode: str = "resolve"
    suggest_top_k: int = 10


@dataclass
class BucketResult:
    latencies_ms: list[float] = field(default_factory=list)
    status_counts: dict[str, int] = field(default_factory=dict)
    surfaced_count: int = 0
    returned_hit_count: int = 0
    top1_hit_count: int = 0


@dataclass
class WorkerResult:
    latencies_ms: list[float]
    status_counts: dict[str, int]
    prefix_count: int
    surfaced_count: int
    returned_hit_count: int
    top1_hit_count: int
    expected_prefix_count: int
    full_query_count: int
    full_query_surfaced_count: int
    full_query_returned_hit_count: int
    full_query_top1_hit_count: int
    query_count: int
    expected_query_count: int
    query_surfaced_count: int
    query_returned_hit_count: int
    query_top1_hit_count: int
    first_returned_hit_prefix_lens: list[int]
    first_top1_hit_prefix_lens: list[int]
    bucket_results: dict[str, BucketResult]
    error_count: int
    # suggest-mode MRR and success@k (full-query level, expected_ids cases only)
    mrr_sum: float = 0.0
    success_at_1_count: int = 0
    success_at_5_count: int = 0
    mrr_query_count: int = 0


@dataclass(frozen=True)
class PrefixFlags:
    surfaced: bool
    returned_hit: bool
    top1_hit: bool


@dataclass
class WorkerAccumulator:
    latencies_ms: list[float] = field(default_factory=list)
    status_counts: dict[str, int] = field(default_factory=dict)
    prefix_count: int = 0
    surfaced_count: int = 0
    returned_hit_count: int = 0
    top1_hit_count: int = 0
    expected_prefix_count: int = 0
    full_query_count: int = 0
    full_query_surfaced_count: int = 0
    full_query_returned_hit_count: int = 0
    full_query_top1_hit_count: int = 0
    query_surfaced_count: int = 0
    query_returned_hit_count: int = 0
    query_top1_hit_count: int = 0
    first_returned_hit_prefix_lens: list[int] = field(default_factory=list)
    first_top1_hit_prefix_lens: list[int] = field(default_factory=list)
    bucket_results: dict[str, BucketResult] = field(default_factory=dict)
    error_count: int = 0
    # suggest-mode MRR and success@k (full-query level, expected_ids cases only)
    mrr_sum: float = 0.0
    success_at_1_count: int = 0
    success_at_5_count: int = 0
    mrr_query_count: int = 0

    def record_exception(self, *, prefix: str, latency_ms: float) -> None:
        self.prefix_count += 1
        self.error_count += 1
        self.latencies_ms.append(latency_ms)
        self.status_counts["exception"] = self.status_counts.get("exception", 0) + 1

        bucket = self.bucket(prefix)
        bucket.latencies_ms.append(latency_ms)
        bucket.status_counts["exception"] = bucket.status_counts.get("exception", 0) + 1

    def record_result(
        self,
        *,
        case: QueryCase,
        prefix: str,
        result: ResolutionResult,
        latency_ms: float,
    ) -> PrefixFlags:
        self.prefix_count += 1
        self.latencies_ms.append(latency_ms)

        status_key = result.status.value
        self.status_counts[status_key] = self.status_counts.get(status_key, 0) + 1

        bucket = self.bucket(prefix)
        bucket.latencies_ms.append(latency_ms)
        bucket.status_counts[status_key] = bucket.status_counts.get(status_key, 0) + 1

        surfaced_ids = surfaced_entity_ids(result)
        top1_id = surfaced_ids[0] if surfaced_ids else None
        surfaced = bool(surfaced_ids)
        if surfaced:
            self.surfaced_count += 1
            bucket.surfaced_count += 1

        returned_hit = False
        top1_hit = False
        if case.expected_ids:
            self.expected_prefix_count += 1
            returned_hit = any(eid in surfaced_ids for eid in case.expected_ids)
            top1_hit = top1_id in case.expected_ids if top1_id is not None else False
            if returned_hit:
                self.returned_hit_count += 1
                bucket.returned_hit_count += 1
            if top1_hit:
                self.top1_hit_count += 1
                bucket.top1_hit_count += 1

        if prefix == case.query:
            self.full_query_count += 1
            if surfaced:
                self.full_query_surfaced_count += 1
            if returned_hit:
                self.full_query_returned_hit_count += 1
            if top1_hit:
                self.full_query_top1_hit_count += 1

        return PrefixFlags(
            surfaced=surfaced,
            returned_hit=returned_hit,
            top1_hit=top1_hit,
        )

    def finalize_query(
        self,
        *,
        case: QueryCase,
        saw_surface: bool,
        first_returned_hit: int | None,
        first_top1_hit: int | None,
    ) -> None:
        if saw_surface:
            self.query_surfaced_count += 1
        if case.expected_ids and first_returned_hit is not None:
            self.query_returned_hit_count += 1
            self.first_returned_hit_prefix_lens.append(first_returned_hit)
        if case.expected_ids and first_top1_hit is not None:
            self.query_top1_hit_count += 1
            self.first_top1_hit_prefix_lens.append(first_top1_hit)

    def bucket(self, prefix: str) -> BucketResult:
        return self.bucket_results.setdefault(
            prefix_len_bucket(len(prefix)), BucketResult()
        )

    def record_mrr(
        self, *, surfaced_ids: list[str], expected_ids: tuple[str, ...]
    ) -> None:
        """Record MRR and success@k for one full-query suggest result.

        Finds the first expected_id in ``surfaced_ids`` and accumulates the
        reciprocal rank.  success@1 and success@5 are updated accordingly.
        Called once per full-query (not per prefix).

        Args:
            surfaced_ids: Ordered list of entity IDs from ``resolver.suggest()``.
            expected_ids: Expected entity IDs for this query case.
        """
        if not expected_ids:
            return
        self.mrr_query_count += 1
        for rank_0, eid in enumerate(surfaced_ids):
            if eid in expected_ids:
                rr = 1.0 / (rank_0 + 1)
                self.mrr_sum += rr
                if rank_0 == 0:
                    self.success_at_1_count += 1
                if rank_0 < 5:
                    self.success_at_5_count += 1
                return
        # Expected id not found — contributes 0 to MRR.

    def to_result(self, *, query_count: int, expected_query_count: int) -> WorkerResult:
        return WorkerResult(
            latencies_ms=self.latencies_ms,
            status_counts=self.status_counts,
            prefix_count=self.prefix_count,
            surfaced_count=self.surfaced_count,
            returned_hit_count=self.returned_hit_count,
            top1_hit_count=self.top1_hit_count,
            expected_prefix_count=self.expected_prefix_count,
            full_query_count=self.full_query_count,
            full_query_surfaced_count=self.full_query_surfaced_count,
            full_query_returned_hit_count=self.full_query_returned_hit_count,
            full_query_top1_hit_count=self.full_query_top1_hit_count,
            query_count=query_count,
            expected_query_count=expected_query_count,
            query_surfaced_count=self.query_surfaced_count,
            query_returned_hit_count=self.query_returned_hit_count,
            query_top1_hit_count=self.query_top1_hit_count,
            first_returned_hit_prefix_lens=self.first_returned_hit_prefix_lens,
            first_top1_hit_prefix_lens=self.first_top1_hit_prefix_lens,
            bucket_results=self.bucket_results,
            error_count=self.error_count,
            mrr_sum=self.mrr_sum,
            success_at_1_count=self.success_at_1_count,
            success_at_5_count=self.success_at_5_count,
            mrr_query_count=self.mrr_query_count,
        )


def prefix_sequence(query: str, min_prefix_len: int) -> list[str]:
    if not query:
        return []

    min_len = max(1, min_prefix_len)
    if len(query) < min_len:
        return [query]

    prefixes = [query[:index] for index in range(min_len, len(query) + 1)]
    return prefixes or [query]


def surfaced_entity_ids(result: ResolutionResult) -> list[str]:
    entity_ids: list[str] = []
    seen: set[str] = set()
    if result.entity_id:
        entity_ids.append(result.entity_id)
        seen.add(result.entity_id)
    for candidate in result.candidates:
        if candidate.entity_id not in seen:
            entity_ids.append(candidate.entity_id)
            seen.add(candidate.entity_id)
    return entity_ids


def suggest_surfaced_entity_ids(suggestions: list) -> list[str]:
    """Extract ordered entity IDs from a ``resolver.suggest()`` result list.

    Args:
        suggestions: ``list[SuggestionResult]`` from ``resolver.suggest()``.

    Returns:
        Ordered list of ``entity_id`` strings (deduplicated, first-seen wins).
    """
    seen: set[str] = set()
    out: list[str] = []
    for s in suggestions:
        eid = s.entity_id
        if eid not in seen:
            seen.add(eid)
            out.append(eid)
    return out


def prefix_len_bucket(prefix_len: int) -> str:
    if prefix_len <= 1:
        return "1"
    if prefix_len <= 3:
        return "2-3"
    if prefix_len <= 5:
        return "4-5"
    if prefix_len <= 8:
        return "6-8"
    if prefix_len <= 12:
        return "9-12"
    return "13+"


def run_worker(
    resolver: Resolver,
    query_cases: list[QueryCase],
    *,
    domains: list[str] | None,
    min_prefix_len: int,
    mode: str = "resolve",
    suggest_top_k: int = 10,
) -> WorkerResult:
    """Run the autocomplete benchmark on a chunk of query cases.

    Module-level so it can be pickled for the ``ProcessPoolExecutor`` path
    (via :func:`functools.partial`).

    Args:
        resolver: Loaded resolver instance.
        query_cases: Query cases for this worker chunk.
        domains: Optional domain filter (``"resolve"`` mode only).
        min_prefix_len: Minimum prefix length to benchmark.
        mode: ``"resolve"`` (default) or ``"suggest"``.
        suggest_top_k: ``top_k`` passed to ``resolver.suggest()`` when
            ``mode == "suggest"``.  Ignored in ``"resolve"`` mode.
    """
    accumulator = WorkerAccumulator()

    for case in query_cases:
        prefixes = prefix_sequence(case.query, min_prefix_len)
        saw_surface = False
        first_returned_hit: int | None = None
        first_top1_hit: int | None = None
        full_query_suggest_ids: list[str] | None = None

        for prefix in prefixes:
            start = time.perf_counter()
            try:
                if mode == "suggest":
                    suggestions = resolver.suggest(prefix, top_k=suggest_top_k)
                    latency_ms = (time.perf_counter() - start) * 1000.0
                    surfaced_ids = suggest_surfaced_entity_ids(suggestions)
                    # Adapt to the existing record_result shape by synthesising a
                    # minimal ResolutionResult-like structure.  We bypass that and
                    # record directly into the accumulator fields.
                    accumulator.prefix_count += 1
                    accumulator.latencies_ms.append(latency_ms)
                    accumulator.status_counts["surfaced"] = (
                        accumulator.status_counts.get("surfaced", 0) + 1
                    )
                    bucket = accumulator.bucket(prefix)
                    bucket.latencies_ms.append(latency_ms)
                    bucket.status_counts["surfaced"] = (
                        bucket.status_counts.get("surfaced", 0) + 1
                    )
                    surfaced = bool(surfaced_ids)
                    if surfaced:
                        accumulator.surfaced_count += 1
                        bucket.surfaced_count += 1
                        saw_surface = True
                    returned_hit = False
                    top1_hit = False
                    if case.expected_ids:
                        accumulator.expected_prefix_count += 1
                        returned_hit = any(
                            eid in surfaced_ids for eid in case.expected_ids
                        )
                        top1_hit = bool(
                            surfaced_ids and surfaced_ids[0] in case.expected_ids
                        )
                        if returned_hit:
                            accumulator.returned_hit_count += 1
                            bucket.returned_hit_count += 1
                        if top1_hit:
                            accumulator.top1_hit_count += 1
                            bucket.top1_hit_count += 1
                    if prefix == case.query:
                        accumulator.full_query_count += 1
                        full_query_suggest_ids = surfaced_ids
                        if surfaced:
                            accumulator.full_query_surfaced_count += 1
                        if returned_hit:
                            accumulator.full_query_returned_hit_count += 1
                        if top1_hit:
                            accumulator.full_query_top1_hit_count += 1
                    if returned_hit and first_returned_hit is None:
                        first_returned_hit = len(prefix)
                    if top1_hit and first_top1_hit is None:
                        first_top1_hit = len(prefix)
                    continue
                else:
                    result = resolver.resolve(prefix, domain=domains, to=None)
            except Exception:
                latency_ms = (time.perf_counter() - start) * 1000.0
                accumulator.record_exception(prefix=prefix, latency_ms=latency_ms)
                continue

            latency_ms = (time.perf_counter() - start) * 1000.0
            flags = accumulator.record_result(
                case=case,
                prefix=prefix,
                result=result,
                latency_ms=latency_ms,
            )
            if flags.surfaced:
                saw_surface = True
            if flags.returned_hit and first_returned_hit is None:
                first_returned_hit = len(prefix)
            if flags.top1_hit and first_top1_hit is None:
                first_top1_hit = len(prefix)

        accumulator.finalize_query(
            case=case,
            saw_surface=saw_surface,
            first_returned_hit=first_returned_hit,
            first_top1_hit=first_top1_hit,
        )

        # MRR is computed at full-query level for suggest mode.
        if (
            mode == "suggest"
            and case.expected_ids
            and full_query_suggest_ids is not None
        ):
            accumulator.record_mrr(
                surfaced_ids=full_query_suggest_ids,
                expected_ids=case.expected_ids,
            )

    expected_query_count = sum(1 for case in query_cases if case.expected_ids)
    return accumulator.to_result(
        query_count=len(query_cases),
        expected_query_count=expected_query_count,
    )


@dataclass
class AggregatedResult:
    latencies_ms: list[float] = field(default_factory=list)
    status_counts: dict[str, int] = field(default_factory=dict)
    prefix_count: int = 0
    surfaced_count: int = 0
    returned_hit_count: int = 0
    top1_hit_count: int = 0
    expected_prefix_count: int = 0
    full_query_count: int = 0
    full_query_surfaced_count: int = 0
    full_query_returned_hit_count: int = 0
    full_query_top1_hit_count: int = 0
    query_count: int = 0
    expected_query_count: int = 0
    query_surfaced_count: int = 0
    query_returned_hit_count: int = 0
    query_top1_hit_count: int = 0
    first_returned_hit_prefix_lens: list[int] = field(default_factory=list)
    first_top1_hit_prefix_lens: list[int] = field(default_factory=list)
    error_count: int = 0
    bucket_results: dict[str, BucketResult] = field(default_factory=dict)
    # suggest-mode MRR and success@k
    mrr_sum: float = 0.0
    success_at_1_count: int = 0
    success_at_5_count: int = 0
    mrr_query_count: int = 0

    def merge(self, result: WorkerResult) -> None:
        self.latencies_ms.extend(result.latencies_ms)
        self.prefix_count += result.prefix_count
        self.surfaced_count += result.surfaced_count
        self.returned_hit_count += result.returned_hit_count
        self.top1_hit_count += result.top1_hit_count
        self.expected_prefix_count += result.expected_prefix_count
        self.full_query_count += result.full_query_count
        self.full_query_surfaced_count += result.full_query_surfaced_count
        self.full_query_returned_hit_count += result.full_query_returned_hit_count
        self.full_query_top1_hit_count += result.full_query_top1_hit_count
        self.query_count += result.query_count
        self.expected_query_count += result.expected_query_count
        self.query_surfaced_count += result.query_surfaced_count
        self.query_returned_hit_count += result.query_returned_hit_count
        self.query_top1_hit_count += result.query_top1_hit_count
        self.first_returned_hit_prefix_lens.extend(
            result.first_returned_hit_prefix_lens
        )
        self.first_top1_hit_prefix_lens.extend(result.first_top1_hit_prefix_lens)
        self.error_count += result.error_count
        self.mrr_sum += result.mrr_sum
        self.success_at_1_count += result.success_at_1_count
        self.success_at_5_count += result.success_at_5_count
        self.mrr_query_count += result.mrr_query_count
        for status, count in result.status_counts.items():
            self.status_counts[status] = self.status_counts.get(status, 0) + count
        for bucket_name, bucket_result in result.bucket_results.items():
            merged_bucket = self.bucket_results.setdefault(bucket_name, BucketResult())
            merged_bucket.latencies_ms.extend(bucket_result.latencies_ms)
            merged_bucket.surfaced_count += bucket_result.surfaced_count
            merged_bucket.returned_hit_count += bucket_result.returned_hit_count
            merged_bucket.top1_hit_count += bucket_result.top1_hit_count
            for status, count in bucket_result.status_counts.items():
                merged_bucket.status_counts[status] = (
                    merged_bucket.status_counts.get(status, 0) + count
                )


def _aggregate_worker_results(
    outcome: WorkerRunOutcome[WorkerResult],
) -> AggregatedResult:
    aggregated = AggregatedResult()
    for pr in outcome.results:
        aggregated.merge(pr.worker_result)
    return aggregated


@dataclass(frozen=True, slots=True, kw_only=True)
class AutocompleteLatencyBlock:
    """Per-prefix latency summary (5 keys: min, mean, p50, p95, max — no p99)."""

    min: float
    mean: float
    p50: float
    p95: float
    max: float


@dataclass(frozen=True, slots=True, kw_only=True)
class PrefixBucketMetrics:
    """Per-prefix-length-bucket metrics."""

    prefix_count: int
    latency_ms: AutocompleteLatencyBlock | None
    statuses: dict[str, int]
    surfaced_rate_pct: float | None
    returned_hit_rate_pct: float | None
    top1_hit_rate_pct: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class PrefixLenStats:
    """Stats for a first-hit prefix length distribution."""

    min: float
    mean: float
    p50: float
    p95: float
    max: float


@dataclass(frozen=True, slots=True, kw_only=True)
class AutocompleteBlock:
    """Autocomplete quality metrics block."""

    prefix_surface_rate_pct: float | None
    prefix_returned_hit_rate_pct: float | None
    prefix_top1_hit_rate_pct: float | None
    full_query_surface_rate_pct: float | None
    full_query_returned_hit_rate_pct: float | None
    full_query_top1_hit_rate_pct: float | None
    queries_with_any_surface_pct: float | None
    queries_reaching_returned_hit_pct: float | None
    queries_reaching_top1_hit_pct: float | None
    first_returned_hit_prefix_len: PrefixLenStats | None
    first_top1_hit_prefix_len: PrefixLenStats | None


@dataclass(frozen=True, slots=True, kw_only=True)
class SuggestMetricsBlock:
    """Suggest-mode quality metrics (MRR and success@k at full-query level)."""

    mrr: float | None
    success_at_1_pct: float | None
    success_at_5_pct: float | None
    query_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class AutocompleteBenchmarkMetrics(BenchmarkMetricsBase):
    """Typed metrics produced by the autocomplete benchmark.

    Extends :class:`~scripts.benchmark.benchmark_common.BenchmarkMetricsBase`
    with autocomplete-specific fields. Field names match the JSON wire-format
    keys so ``dataclasses.asdict()`` serializes without key translation.
    """

    csv_path: str
    datapacks: list[str]
    min_prefix_len: int
    benchmark_prefixes: int
    avg_prefixes_per_query: float
    throughput_prefix_qps: float
    throughput_query_sequences_per_sec: float
    latency_ms: AutocompleteLatencyBlock
    autocomplete: AutocompleteBlock
    prefix_buckets: dict[str, PrefixBucketMetrics]
    suggest: SuggestMetricsBlock | None = None


def format_rate(v: float | None) -> str:
    """Format a rate value as a percentage string, or 'n/a' when None."""
    if v is None:
        return "n/a"
    return f"{v:.2f}%"


def _stats_to_latency_block(
    values: list[float] | list[int],
) -> AutocompleteLatencyBlock:
    """Convert a list of numeric values to an ``AutocompleteLatencyBlock``."""
    if not values:
        return AutocompleteLatencyBlock(min=0.0, mean=0.0, p50=0.0, p95=0.0, max=0.0)
    numeric = [float(v) for v in values]
    return AutocompleteLatencyBlock(
        min=min(numeric),
        mean=_mean(numeric),
        p50=percentile(numeric, 50),
        p95=percentile(numeric, 95),
        max=max(numeric),
    )


def _stats_to_prefix_len_stats(values: list[int]) -> PrefixLenStats | None:
    """Convert a list of prefix length values to a ``PrefixLenStats``, or None."""
    if not values:
        return None
    numeric = [float(v) for v in values]
    return PrefixLenStats(
        min=min(numeric),
        mean=_mean(numeric),
        p50=percentile(numeric, 50),
        p95=percentile(numeric, 95),
        max=max(numeric),
    )


def _build_metrics(
    *,
    inputs: AutocompleteRunInputs,
    datapacks: list[str | Path],
    warmup_count: int,
    outcome: WorkerRunOutcome[WorkerResult],
    agg: AggregatedResult,
) -> AutocompleteBenchmarkMetrics:
    elapsed_seconds = outcome.elapsed_seconds
    prefix_qps = agg.prefix_count / elapsed_seconds if elapsed_seconds > 0 else 0.0
    query_qps = agg.query_count / elapsed_seconds if elapsed_seconds > 0 else 0.0

    prefix_buckets = {
        name: PrefixBucketMetrics(
            prefix_count=len(bucket.latencies_ms),
            latency_ms=(
                _stats_to_latency_block(bucket.latencies_ms)
                if bucket.latencies_ms
                else None
            ),
            statuses=bucket.status_counts,
            surfaced_rate_pct=(
                100.0 * bucket.surfaced_count / len(bucket.latencies_ms)
                if bucket.latencies_ms
                else None
            ),
            returned_hit_rate_pct=(
                100.0 * bucket.returned_hit_count / len(bucket.latencies_ms)
                if bucket.latencies_ms
                else None
            ),
            top1_hit_rate_pct=(
                100.0 * bucket.top1_hit_count / len(bucket.latencies_ms)
                if bucket.latencies_ms
                else None
            ),
        )
        for name, bucket in sorted(agg.bucket_results.items())
    }

    autocomplete_block = AutocompleteBlock(
        prefix_surface_rate_pct=(
            100.0 * agg.surfaced_count / agg.prefix_count if agg.prefix_count else None
        ),
        prefix_returned_hit_rate_pct=(
            100.0 * agg.returned_hit_count / agg.expected_prefix_count
            if agg.expected_prefix_count
            else None
        ),
        prefix_top1_hit_rate_pct=(
            100.0 * agg.top1_hit_count / agg.expected_prefix_count
            if agg.expected_prefix_count
            else None
        ),
        full_query_surface_rate_pct=(
            100.0 * agg.full_query_surfaced_count / agg.full_query_count
            if agg.full_query_count
            else None
        ),
        full_query_returned_hit_rate_pct=(
            100.0 * agg.full_query_returned_hit_count / agg.expected_query_count
            if agg.expected_query_count
            else None
        ),
        full_query_top1_hit_rate_pct=(
            100.0 * agg.full_query_top1_hit_count / agg.expected_query_count
            if agg.expected_query_count
            else None
        ),
        queries_with_any_surface_pct=(
            100.0 * agg.query_surfaced_count / agg.query_count
            if agg.query_count
            else None
        ),
        queries_reaching_returned_hit_pct=(
            100.0 * agg.query_returned_hit_count / agg.expected_query_count
            if agg.expected_query_count
            else None
        ),
        queries_reaching_top1_hit_pct=(
            100.0 * agg.query_top1_hit_count / agg.expected_query_count
            if agg.expected_query_count
            else None
        ),
        first_returned_hit_prefix_len=_stats_to_prefix_len_stats(
            agg.first_returned_hit_prefix_lens
        ),
        first_top1_hit_prefix_len=_stats_to_prefix_len_stats(
            agg.first_top1_hit_prefix_lens
        ),
    )

    suggest_block: SuggestMetricsBlock | None = None
    if agg.mrr_query_count > 0:
        suggest_block = SuggestMetricsBlock(
            mrr=agg.mrr_sum / agg.mrr_query_count,
            success_at_1_pct=100.0 * agg.success_at_1_count / agg.mrr_query_count,
            success_at_5_pct=100.0 * agg.success_at_5_count / agg.mrr_query_count,
            query_count=agg.mrr_query_count,
        )

    return AutocompleteBenchmarkMetrics(
        workers=inputs.workers,
        warmup_queries=warmup_count,
        benchmark_queries=agg.query_count,
        resolver_init_seconds=round(outcome.init_seconds, 6),
        elapsed_seconds=round(elapsed_seconds, 6),
        # latencies_ms is used for internal stats; excluded from JSON output.
        latencies_ms=agg.latencies_ms,
        statuses=agg.status_counts,
        exceptions=agg.error_count,
        csv_path=relative_to_cwd(path=inputs.csv),
        datapacks=[relative_to_cwd(path=p) for p in datapacks],
        min_prefix_len=inputs.min_prefix_len,
        benchmark_prefixes=agg.prefix_count,
        avg_prefixes_per_query=(
            agg.prefix_count / agg.query_count if agg.query_count else 0.0
        ),
        throughput_prefix_qps=prefix_qps,
        throughput_query_sequences_per_sec=query_qps,
        latency_ms=_stats_to_latency_block(agg.latencies_ms),
        autocomplete=autocomplete_block,
        prefix_buckets=prefix_buckets,
        suggest=suggest_block,
    )


def _print_metrics(metrics: AutocompleteBenchmarkMetrics) -> None:
    print("=== ResolveKit Autocomplete Benchmark ===")
    print(f"CSV: {metrics.csv_path}")
    print(f"Datapacks: {', '.join(metrics.datapacks)}")
    print(f"Workers: {metrics.workers}")
    print(f"Resolver init: {metrics.resolver_init_seconds:.3f}s")
    print(f"Warmup query sequences: {metrics.warmup_queries}")
    print(f"Benchmark query sequences: {metrics.benchmark_queries}")
    print(f"Benchmark prefixes: {metrics.benchmark_prefixes}")
    print(f"Min prefix length: {metrics.min_prefix_len}")
    print(f"Elapsed: {metrics.elapsed_seconds:.3f}s")
    print(
        "Throughput: "
        f"{metrics.throughput_prefix_qps:.2f} prefix-qps, "
        f"{metrics.throughput_query_sequences_per_sec:.2f} query-seq/s"
    )
    latency = metrics.latency_ms
    # Inline latency formatting: autocomplete's 5-key block (min/mean/p50/p95/max)
    # differs from the resolver's 6-key block (adds p99). Wire-format stability
    # precludes adopting the shared renderer here.
    print(
        "Latency (ms): "
        f"min={latency.min:.2f}, "
        f"mean={latency.mean:.2f}, "
        f"p50={latency.p50:.2f}, "
        f"p95={latency.p95:.2f}, "
        f"max={latency.max:.2f}"
    )
    status_rows = format_status_table(status_counts=metrics.statuses)
    print(render_status_table(rows=status_rows))

    autocomplete = metrics.autocomplete
    print(
        "Surface: "
        f"prefixes={format_rate(autocomplete.prefix_surface_rate_pct)} "
        f"queries={format_rate(autocomplete.queries_with_any_surface_pct)}"
    )
    print(
        "Expected entity surfaced: "
        f"prefixes={format_rate(autocomplete.prefix_returned_hit_rate_pct)} "
        f"queries={format_rate(autocomplete.queries_reaching_returned_hit_pct)}"
    )
    print(
        "Expected entity top1: "
        f"prefixes={format_rate(autocomplete.prefix_top1_hit_rate_pct)} "
        f"queries={format_rate(autocomplete.queries_reaching_top1_hit_pct)}"
    )
    print(
        "Full query: "
        f"returned={format_rate(autocomplete.full_query_returned_hit_rate_pct)} "
        f"top1={format_rate(autocomplete.full_query_top1_hit_rate_pct)}"
    )

    first_returned = autocomplete.first_returned_hit_prefix_len
    if first_returned is not None:
        print(
            "First expected-surface prefix len: "
            f"mean={first_returned.mean:.2f}, "
            f"p50={first_returned.p50:.2f}, "
            f"p95={first_returned.p95:.2f}"
        )

    first_top1 = autocomplete.first_top1_hit_prefix_len
    if first_top1 is not None:
        print(
            "First top1-hit prefix len: "
            f"mean={first_top1.mean:.2f}, "
            f"p50={first_top1.p50:.2f}, "
            f"p95={first_top1.p95:.2f}"
        )

    if metrics.suggest is not None:
        sug = metrics.suggest
        mrr_str = f"{sug.mrr:.4f}" if sug.mrr is not None else "n/a"
        s1_str = format_rate(sug.success_at_1_pct)
        s5_str = format_rate(sug.success_at_5_pct)
        print(
            f"Suggest metrics ({sug.query_count} queries): "
            f"MRR={mrr_str} success@1={s1_str} success@5={s5_str}"
        )


def main(*, inputs: AutocompleteRunInputs) -> None:
    """Run the autocomplete-style benchmark.

    Args:
        inputs: Benchmark configuration including autocomplete-specific
            ``min_prefix_len``. Datapacks are resolved from ``inputs.datapacks``
            and ``inputs.modules`` before running.
    """
    if inputs.min_prefix_len < 1:
        raise BenchmarkConfigurationError("min_prefix_len must be >= 1")

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

    # functools.partial is picklable when the wrapped function is module-level.
    worker_fn = functools.partial(
        run_worker,
        domains=domains,
        min_prefix_len=inputs.min_prefix_len,
        mode=inputs.mode,
        suggest_top_k=inputs.suggest_top_k,
    )
    outcome = run_workers(
        config=config,
        benchmark_chunks=benchmark_chunks,
        warmup_cases=warmup_cases,
        worker_fn=worker_fn,
    )

    agg = _aggregate_worker_results(outcome)
    metrics = _build_metrics(
        inputs=inputs,
        datapacks=datapacks,
        warmup_count=warmup_count,
        outcome=outcome,
        agg=agg,
    )
    _print_metrics(metrics)
    write_metrics_json(inputs.output_json, metrics)


if __name__ == "__main__":
    main(
        inputs=AutocompleteRunInputs(
            csv=Path("scripts/benchmark/fixtures/autocomplete_country_typos.csv"),
            # Bundled packs only: this trio satisfies its own module
            # dependencies. admin1+ are remote and not materialized locally
            # (and drag in admin2/3/cities), so they are not in the default set.
            datapacks=[
                Path("src/resolvekit/_data/geo/countries"),
                Path("src/resolvekit/_data/geo/continental_unions"),
                Path("src/resolvekit/_data/geo/regions"),
            ],
            modules=None,
            mode="suggest",
            suggest_top_k=10,
            min_prefix_len=1,
            warmup=0,
        )
    )
