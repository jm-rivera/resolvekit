"""Benchmark runner orchestration.

`run_benchmark` fans every requested tool over every requested dataset,
measures cold-start + hot-path latency, computes accuracy/latency/memory
metrics via ``benchmarks.core.metrics``, and returns a ``BenchmarkReport``.

Online adapters (``offline == False``) are restricted by default to the
datasets in ``_ONLINE_DEFAULT_DATASETS`` so the default CI run stays
cache-only. That set covers every geo dataset, so a committed Data Commons
cache lets the default run report DC per entity type alongside the offline
tools. Callers who pass ``datasets=[...]`` explicitly opt out of this guard
and are responsible for either priming the cache or tolerating live calls.

Every tool runs on every dataset its declared entity types intersect —
including the curated ``eval_*`` sets — so the per-entity-type tables show a
like-for-like comparison (a country-only tool is simply scoped to the country
rows). The ``eval`` flag now only drives the CI regression gate and the
typed-hint note, not a tool restriction.
"""

from __future__ import annotations

import contextlib
import logging
import os
import platform
import random
import time
from datetime import UTC, datetime
from pathlib import Path

from benchmarks.build.provenance import dataset_sha256
from benchmarks.core.kernel import Observation, Query, Response
from benchmarks.core.loader import DATASET_NAMES, load_dataset
from benchmarks.core.metricresults import ToolMetrics
from benchmarks.core.metrics import (
    accuracy_metrics,
    ambiguity_recall,
    calibration_metrics,
    data_size_mb_from_manifest,
    latency_metrics,
    throughput_qps,
    wheel_size_mb,
)
from benchmarks.core.profile import ToolProfile, measure_profile
from benchmarks.core.report import (
    BenchmarkReport,
    DatasetMeta,
    HardwareInfo,
    ToolResult,
)
from benchmarks.core.toolspec import tool_registry
from benchmarks.tools.protocol import ResolverAdapter

_log = logging.getLogger("benchmarks.core.engine")

# Datasets on which online adapters (e.g. data_commons_resolve) run by default.
# Covers every geo dataset so Data Commons is measured per entity type
# (country / admin1 / admin2 / city) alongside the offline tools, given a
# committed online cache. Adapters are still scoped to the entity types they
# declare, so DC only runs on the rows it supports within each dataset.
_ONLINE_DEFAULT_DATASETS: frozenset[str] = frozenset(
    {
        "ambiguous",
        "no_match",
        "geo_countries_en",
        "geo_countries_multilingual",
        "geo_admin",
        "geo_cities",
        "eval_geo",
    }
)

# Datasets that use multi-span mention-level scoring; excluded from the default
# single-response benchmarks/core run to prevent a bogus 0%-accuracy row.
# An explicit datasets=[...] call still loads them for dedicated consumers.
_MULTISPAN_EVAL_DATASETS: frozenset[str] = frozenset({"eval_parse"})

# Path to resolvekit's manifest — used by the no-cold-start fallback to compute
# data_size_mb without going through measure_profile.
_RESOLVEKIT_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent
    / "src"
    / "resolvekit"
    / "_data"
    / "manifest.json"
)


def run_benchmark(
    *,
    tools: list[str] | None = None,
    datasets: list[str] | None = None,
    warmup: int = 100,
    seed: int = 42,
    refresh_online_cache: bool = False,
    measure_cold_start: bool = True,
    data_dir: Path | None = None,
) -> BenchmarkReport:
    """Run every (tool, dataset) combo and return an aggregated report."""
    registry = tool_registry()
    selected_tools = _select_tools(tools, registry=registry)
    dataset_info = _load_datasets(datasets, data_dir=data_dir)

    profile_cache: dict[str, ToolProfile] = {}
    results: list[ToolResult] = []
    explicit_datasets = datasets is not None
    for tool_name in selected_tools:
        adapter_cls = registry[tool_name]
        for dataset_name, info in dataset_info.items():
            if (
                not explicit_datasets
                and not adapter_cls.spec.offline
                and dataset_name not in _ONLINE_DEFAULT_DATASETS
            ):
                continue
            rows = info["rows"]
            results.append(
                _run_combo(
                    tool_name=tool_name,
                    adapter_cls=adapter_cls,
                    dataset_name=dataset_name,
                    rows=rows,
                    warmup=warmup,
                    seed=seed,
                    refresh_online_cache=refresh_online_cache,
                    measure_cold_start=measure_cold_start,
                    profile_cache=profile_cache,
                )
            )

    dataset_meta = {
        name: DatasetMeta(
            sha256=info["sha256"],
            row_count=info["row_count"],
            path=info["path"],
        )
        for name, info in dataset_info.items()
    }

    return BenchmarkReport(
        benchmark_version="1",
        generated_at=datetime.now(UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        hardware=_collect_hardware(),
        datasets=dataset_meta,
        warmup=warmup,
        seed=seed,
        tools=tuple(sorted(results, key=lambda r: (r.dataset, r.name))),
    )


def _select_tools(
    tools: list[str] | None, *, registry: dict[str, type[ResolverAdapter]]
) -> list[str]:
    if tools is None:
        return list(registry)
    unknown = [name for name in tools if name not in registry]
    if unknown:
        raise ValueError(f"Unknown tool(s): {unknown}. Known: {sorted(registry)}")
    return list(tools)


def _load_datasets(
    datasets: list[str] | None,
    *,
    data_dir: Path | None,
) -> dict[str, dict]:
    if datasets is not None:
        candidate_names = list(datasets)
    else:
        # Exclude multi-span eval datasets: they require the dedicated
        # benchmarks/parse runner and would emit a bogus 0%-accuracy row here.
        candidate_names = [
            n for n in DATASET_NAMES if n not in _MULTISPAN_EVAL_DATASETS
        ]
    unknown = [name for name in candidate_names if name not in DATASET_NAMES]
    if unknown:
        raise ValueError(f"Unknown dataset(s): {unknown}. Known: {list(DATASET_NAMES)}")
    directory = (
        data_dir if data_dir is not None else Path(__file__).parent.parent / "data"
    )
    loaded: dict[str, dict] = {}
    for name in candidate_names:
        path = directory / f"{name}.parquet"
        rows = load_dataset(name, data_dir=data_dir)
        if not rows and datasets is None:
            _log.info("skipping empty stretch dataset %s", name)
            continue
        loaded[name] = {
            "rows": rows,
            "row_count": len(rows),
            "sha256": _sha256_file(path),
            "path": f"benchmarks/data/{name}.parquet",
        }
    return loaded


def _run_combo(
    *,
    tool_name: str,
    adapter_cls: type[ResolverAdapter],
    dataset_name: str,
    rows: list[Query],
    warmup: int,
    seed: int,
    refresh_online_cache: bool,
    measure_cold_start: bool,
    profile_cache: dict[str, ToolProfile],
) -> ToolResult:
    _log.info("running %s on %s (%d rows)", tool_name, dataset_name, len(rows))
    spec = adapter_cls.spec

    try:
        adapter = _construct_adapter(
            adapter_cls=adapter_cls,
            refresh_online_cache=refresh_online_cache,
        )
    except ImportError as exc:
        reason = f"not installed: {spec.distribution} ({exc.name or str(exc)})"
        _log.info("skip %s on %s: %s", tool_name, dataset_name, reason)
        return ToolResult(
            name=tool_name,
            version=None,
            offline=spec.offline,
            dataset=dataset_name,
            metrics=None,
            skipped_reason=reason,
            coverage=None,
        )

    dataset_types = {row.entity_type for row in rows}
    supported = spec.entity_types
    if not (dataset_types & supported):
        reason = (
            f"scope: supports {sorted(supported)}, dataset has {sorted(dataset_types)}"
        )
        _log.info("skip %s on %s: %s", tool_name, dataset_name, reason)
        return ToolResult(
            name=tool_name,
            version=adapter.version(),
            offline=spec.offline,
            dataset=dataset_name,
            metrics=None,
            skipped_reason=reason,
            coverage=None,
        )

    # Collect per-tool profile (cold-start + peak RSS + version) once per tool.
    # When measure_cold_start=False, skip the subprocess entirely; wheel_size_mb
    # and data_size_mb are still computed cheaply in-process.
    if measure_cold_start and rows:
        if tool_name not in profile_cache:
            _log.debug("profiling %s (subprocess)", tool_name)
            profile_cache[tool_name] = measure_profile(
                adapter_cls=adapter_cls,
                first_query=rows[0].text,
                distribution=spec.distribution,
            )
        profile = profile_cache[tool_name]
    else:
        profile = None

    try:
        adapter.warmup()
    except Exception as exc:
        # An online adapter (e.g. data_commons_resolve) can fail warmup when its
        # endpoint is unreachable or rejects the request — notably a 403 from the
        # DC instance in CI, where the runner has no access to it. Skip the tool
        # with a clear reason instead of aborting the whole run; the eval gate
        # measures resolvekit's offline accuracy and does not depend on it.
        reason = f"warmup failed: {exc!r}"
        _log.warning("skip %s on %s: %s", tool_name, dataset_name, reason)
        return ToolResult(
            name=tool_name,
            version=adapter.version(),
            offline=spec.offline,
            dataset=dataset_name,
            metrics=None,
            skipped_reason=reason,
            coverage=None,
        )
    shuffled = list(rows)
    random.Random(seed).shuffle(shuffled)

    # Filter to the rows this adapter's declared entity_types cover; throughput
    # and latency percentiles are measured over scoped rows only, so absolute QPS
    # shifts for mixed-type adapters reflect their true domain coverage, not a
    # penalty for rows they never claimed to answer.
    scoped = [r for r in shuffled if r.entity_type in spec.entity_types]
    coverage = len(scoped) / len(rows) if rows else 0.0

    effective_warmup = warmup if warmup < len(scoped) else len(scoped) // 5
    for row in scoped[:effective_warmup]:
        with contextlib.suppress(Exception):
            adapter.resolve(row)

    measured = scoped[effective_warmup:]
    observations: list[Observation] = []
    latencies: list[float] = []
    wall_start = time.perf_counter()
    for row in measured:
        start = time.perf_counter()
        try:
            response = adapter.resolve(row)
        except Exception as exc:
            response = Response(status="error", error=repr(exc))
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        observations.append(
            Observation(query=row, response=response, latency_ms=elapsed_ms)
        )
        latencies.append(elapsed_ms)
    wall_elapsed = time.perf_counter() - wall_start

    acc = accuracy_metrics(observations=observations)
    lat = latency_metrics(latencies_ms=latencies)
    tool_metrics = ToolMetrics(
        accuracy=acc,
        ambiguity_recall=ambiguity_recall(observations=observations),
        latency_ms=lat,
        throughput_qps=throughput_qps(
            latencies_ms=latencies, wall_elapsed_seconds=wall_elapsed
        ),
        effective_warmup=effective_warmup,
        cold_start_ms=profile.cold_start_ms if profile else None,
        peak_rss_mb=profile.peak_rss_mb if profile else None,
        # wheel_size_mb / data_size_mb: from profile when available (subprocess
        # measured it), otherwise compute in-process so --no-cold-start still shows
        # footprint numbers.
        wheel_size_mb=(
            profile.wheel_size_mb
            if profile is not None
            else wheel_size_mb(dist_name=spec.distribution)
        ),
        data_size_mb=(
            profile.data_size_mb
            if profile is not None
            else (
                data_size_mb_from_manifest(
                    manifest_path=_RESOLVEKIT_MANIFEST_PATH,
                )
                if spec.distribution == "resolvekit"
                else None
            )
        ),
        calibration=(
            calibration_metrics(observations=observations)
            if spec.supports_calibration
            else None
        ),
    )

    _log.info(
        "done %s on %s: acc=%.3f p50=%.2fms",
        tool_name,
        dataset_name,
        acc.overall,
        lat.p50,
    )

    return ToolResult(
        name=tool_name,
        version=profile.version if profile else adapter.version(),
        offline=spec.offline,
        dataset=dataset_name,
        metrics=tool_metrics,
        coverage=coverage,
    )


def _construct_adapter(
    *,
    adapter_cls: type[ResolverAdapter],
    refresh_online_cache: bool,
) -> ResolverAdapter:
    if not adapter_cls.spec.offline and refresh_online_cache:
        return adapter_cls(refresh=True)  # type: ignore[call-arg]
    return adapter_cls()


# Alias: tests monkeypatch this to control dataset provenance.
_sha256_file = dataset_sha256


def _collect_hardware() -> HardwareInfo:
    cpu = platform.processor() or ""
    cpuinfo = Path("/proc/cpuinfo")
    if not cpu and cpuinfo.exists():
        with contextlib.suppress(OSError):
            for line in cpuinfo.read_text().splitlines():
                if line.lower().startswith("model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
    try:
        import psutil

        memory_mb: int | None = int(psutil.virtual_memory().total / (1024 * 1024))
    except ImportError:
        memory_mb = None
    return HardwareInfo(
        cpu=cpu or "unknown",
        cores=os.cpu_count(),
        memory_mb=memory_mb,
        platform=platform.platform(),
        python=platform.python_version(),
    )
