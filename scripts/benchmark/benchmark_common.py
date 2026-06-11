"""Shared utilities for benchmark scripts."""

from __future__ import annotations

import dataclasses
import json
import math
import random
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from statistics import mean as _mean
from typing import Any, ClassVar, Protocol, cast

from benchmarks.core._math import percentile
from resolvekit.builder.datapack_layout import module_pack_dir
from resolvekit.builder.models import BuildOptions, ReleaseRecord
from resolvekit.builder.registry import list_releases
from resolvekit.core.api import Resolver
from resolvekit.core.engine.router import RoutingMode


@dataclass(frozen=True)
class QueryCase:
    query: str
    expected_ids: tuple[str, ...]
    category: str | None
    difficulty: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkerConfig:
    datapacks: list[str | Path]
    routing_mode: RoutingMode
    packs: list[str] | None
    domains: list[str] | None


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkRunInputs:
    """Shared input surface for all benchmark scripts.

    Both ``benchmark_resolver`` and ``benchmark_autocomplete`` accept this
    base. ``AutocompleteRunInputs`` extends it with ``min_prefix_len``.
    """

    datapacks: list[str | Path]
    modules: list[str] | None
    build_root: Path = Path("data/build")
    csv: Path = Path("benchmarks/data/geo_countries_en.parquet")
    workers: int = 1
    limit: int | None = None
    warmup: int = 100
    shuffle: bool = False
    seed: int = 42
    routing_mode: RoutingMode = RoutingMode.AUTO
    packs: list[str] | None = None
    domains: list[str] | None = None
    output_json: Path | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkMetricsBase:
    """Shared metrics fields emitted by every benchmark script.

    Consumed via ``dataclasses.asdict(base) | {script_specific_fields}`` in
    each script's ``_build_metrics()``. Field names match the existing JSON
    wire-format keys so the output is byte-compatible.
    """

    workers: int
    warmup_queries: int
    benchmark_queries: int
    resolver_init_seconds: float
    elapsed_seconds: float
    latencies_ms: list[float]
    statuses: dict[str, int]
    exceptions: int


class BenchmarkMetrics(Protocol):
    """Protocol satisfied by every typed benchmark metrics dataclass.

    ``write_metrics_json`` accepts any dataclass that satisfies this protocol
    and serializes it via ``dataclasses.asdict()``.
    """

    __dataclass_fields__: ClassVar[dict[str, Any]]

    workers: int
    warmup_queries: int
    benchmark_queries: int
    resolver_init_seconds: float
    elapsed_seconds: float
    latencies_ms: list[float]
    statuses: dict[str, int]
    exceptions: int


@dataclass(frozen=True, slots=True, kw_only=True)
class StatusRow:
    """One row in the status table: a status label and its occurrence count."""

    status: str
    count: int


class BenchmarkConfigurationError(ValueError):
    """Raised when benchmark inputs are misconfigured.

    Subclasses ``ValueError`` so existing ``except ValueError:`` callers
    still catch it, but discriminates from ``FileNotFoundError`` which
    propagates separately when a path doesn't exist on disk.
    """


# Worker function signature: (resolver, benchmark_cases) -> R.
# Warmup is handled by the runner before calling the worker function.
type WorkerFn[R] = Callable[[Resolver, list[QueryCase]], R]


@dataclass(frozen=True, slots=True, kw_only=True)
class ProcessWorkerResult[R]:
    """Per-worker timing plus the script-specific result payload.

    All four timing fields are populated identically on the single-worker
    (in-process thread) and multi-worker (``ProcessPoolExecutor``) paths.
    """

    worker_result: R
    init_seconds: float
    warmup_seconds: float
    benchmark_seconds: float


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkerRunOutcome[R]:
    """Aggregate of a full benchmark run across all workers.

    ``init_seconds``, ``warmup_seconds``, and ``elapsed_seconds`` reflect
    the *slowest* worker (worst-case wall-clock parallelism — matches the
    existing convention in ``benchmark_resolver``).
    """

    results: list[ProcessWorkerResult[R]]
    elapsed_seconds: float
    init_seconds: float
    warmup_seconds: float


def _process_worker_with_warmup[R](
    config: WorkerConfig,
    warmup_cases: list[QueryCase],
    benchmark_chunk: list[QueryCase],
    worker_fn: WorkerFn[R],
) -> ProcessWorkerResult[R]:
    """Top-level helper for ``ProcessPoolExecutor`` workers.

    Each process builds its own ``Resolver`` to avoid pickling issues.
    Warmup is run before ``worker_fn`` is called so the runner owns it
    uniformly.
    """
    t0 = time.perf_counter()
    resolver = build_resolver(
        config.datapacks,
        routing_mode=config.routing_mode,
        packs=config.packs,
    )
    t1 = time.perf_counter()
    for case in warmup_cases:
        resolver.resolve(case.query, domain=config.domains, to=None)
    t2 = time.perf_counter()
    result = worker_fn(resolver, benchmark_chunk)
    t3 = time.perf_counter()
    resolver.close()
    return ProcessWorkerResult(
        worker_result=result,
        init_seconds=t1 - t0,
        warmup_seconds=t2 - t1,
        benchmark_seconds=t3 - t2,
    )


def run_workers[R](
    *,
    config: WorkerConfig,
    benchmark_chunks: list[list[QueryCase]],
    warmup_cases: list[QueryCase],
    worker_fn: WorkerFn[R],
) -> WorkerRunOutcome[R]:
    """Run benchmark workers, handling warmup uniformly on both paths.

    Single-worker path uses a ``ThreadPoolExecutor`` (avoids process
    overhead). Multi-worker path uses ``ProcessPoolExecutor`` (bypasses
    the GIL). Both paths produce ``ProcessWorkerResult[R]`` with all four
    timing fields populated.

    Args:
        config: Shared worker configuration (datapacks, routing mode, etc.).
        benchmark_chunks: One chunk per worker; each is the slice of
            ``QueryCase`` objects that worker will benchmark.
        warmup_cases: Cases run before benchmarking (not counted in results).
        worker_fn: Callable ``(resolver, benchmark_cases) -> R`` that performs
            the actual benchmark and returns the per-script result payload.

    Returns:
        A ``WorkerRunOutcome[R]`` with one ``ProcessWorkerResult[R]`` per
        worker and aggregate timing.
    """
    n_workers = len(benchmark_chunks)

    if n_workers <= 1:
        # Single-worker: in-process, thread-backed (no spawn overhead).
        t0 = time.perf_counter()
        resolver = build_resolver(
            config.datapacks,
            routing_mode=config.routing_mode,
            packs=config.packs,
        )
        t1 = time.perf_counter()
        for case in warmup_cases:
            resolver.resolve(case.query, domain=config.domains, to=None)
        t2 = time.perf_counter()
        chunk = benchmark_chunks[0] if benchmark_chunks else []
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(worker_fn, resolver, chunk)
            worker_result = future.result()
        t3 = time.perf_counter()
        resolver.close()

        process_result = ProcessWorkerResult(
            worker_result=worker_result,
            init_seconds=t1 - t0,
            warmup_seconds=t2 - t1,
            benchmark_seconds=t3 - t2,
        )
        return WorkerRunOutcome(
            results=[process_result],
            elapsed_seconds=process_result.benchmark_seconds,
            init_seconds=process_result.init_seconds,
            warmup_seconds=process_result.warmup_seconds,
        )
    else:
        # Multi-worker: process pool (each process builds its own resolver).
        with ProcessPoolExecutor(max_workers=n_workers) as executor:
            futures = [
                executor.submit(
                    _process_worker_with_warmup,
                    config,
                    warmup_cases,
                    chunk,
                    worker_fn,
                )
                for chunk in benchmark_chunks
            ]
            process_results: list[ProcessWorkerResult[R]] = cast(
                list[ProcessWorkerResult[R]], [f.result() for f in futures]
            )

        return WorkerRunOutcome(
            results=process_results,
            elapsed_seconds=max(pr.benchmark_seconds for pr in process_results),
            init_seconds=max(pr.init_seconds for pr in process_results),
            warmup_seconds=max(pr.warmup_seconds for pr in process_results),
        )


def normalize_domains(domains_input: list[str] | None) -> list[str] | None:
    """Deduplicate a domain list and return ``None`` for an empty result.

    Args:
        domains_input: Raw domain list from inputs, or ``None``.

    Returns:
        Deduplicated list, or ``None`` if empty.
    """
    deduped = list(dict.fromkeys(domains_input or []))
    return deduped or None


def validate_inputs(*, inputs: BenchmarkRunInputs) -> list[str | Path]:
    """Validate benchmark inputs, resolve datapacks, and return the resolved list.

    Combines :func:`resolve_datapacks` and configuration validation into a
    single entry point so callers don't need to call both separately.

    Args:
        inputs: The benchmark run inputs to validate.

    Returns:
        Resolved list of datapack paths (explicit paths first, then
        module-resolved paths).

    Raises:
        BenchmarkConfigurationError: For configuration errors (workers < 1,
            incompatible routing-mode + domains combination, etc.).
        FileNotFoundError: When a resolved datapack path doesn't exist on disk,
            or a module has no release records.
        ValueError: If neither ``inputs.datapacks`` nor ``inputs.modules``
            contains any entries.
    """
    if inputs.workers < 1:
        raise BenchmarkConfigurationError("workers must be >= 1")

    domains = normalize_domains(inputs.domains)
    if domains and inputs.routing_mode == RoutingMode.AUTO:
        raise BenchmarkConfigurationError(
            "domains requires routing_mode explicit or hybrid, not auto"
        )

    resolved_datapacks = resolve_datapacks(
        datapacks=inputs.datapacks,
        modules=inputs.modules,
        build_root=inputs.build_root,
    )

    for path in resolved_datapacks:
        resolved = Path(path) if isinstance(path, str) else path
        if not resolved.exists():
            raise FileNotFoundError(f"Datapack path does not exist: {resolved}")

    return resolved_datapacks


def load_query_cases(
    *,
    dataset_path: Path,
    shuffle: bool,
    seed: int,
    limit: int | None,
) -> list[QueryCase]:
    """Load query cases from a Parquet dataset.

    Args:
        dataset_path: Path to the Parquet file.
        shuffle: Whether to shuffle before applying *limit*.
        seed: RNG seed used when *shuffle* is ``True``.
        limit: Maximum number of cases to return; ``None`` means no limit.

    Returns:
        List of ``QueryCase`` objects.

    Raises:
        FileNotFoundError: If *dataset_path* does not exist.
        ValueError: If the dataset is missing the required ``query`` column or
            if no non-empty queries are found after filtering.
    """
    cases = load_queries(dataset_path.expanduser().resolve())
    if shuffle:
        rng = random.Random(seed)
        rng.shuffle(cases)
    if limit is not None:
        cases = cases[:limit]
    if not cases:
        raise ValueError("No queries selected after applying filters.")
    return cases


def resolve_datapacks(
    *,
    datapacks: list[str | Path],
    modules: list[str] | None,
    build_root: Path,
) -> list[str | Path]:
    """Resolve a mix of explicit datapack paths and module IDs to a path list.

    For each module ID, resolution is attempted in two steps:

    1. **On-disk lookup** — derive the datapack directory from the v1 flat
       layout (``<datapacks_root>/<domain>/<subpath>/``) and check for
       ``entities.sqlite``.  This works even when the release ledger has no
       row, as is the case after a plain ``build()`` (which does not write the
       ledger).
    2. **Ledger fallback** — if the on-disk path does not exist or lacks
       ``entities.sqlite``, fall back to the release registry
       (``list_releases``).

    Args:
        datapacks: Explicitly provided datapack directory paths.
        modules: Module IDs to look up (on-disk first, ledger second).
        build_root: Build root used to locate the registry for the ledger
            fallback.  Also used to derive the default ``datapacks_root``
            (``<build_root>/../src/resolvekit/_data`` relative to repo root).

    Returns:
        Deduplicated list of resolved datapack paths (explicit paths first,
        then module-resolved paths).

    Raises:
        ValueError: If neither *datapacks* nor *modules* contains any entries.
        FileNotFoundError: If a module cannot be found either on disk or in
            the registry.
    """
    resolved: list[str | Path] = [
        Path(value).expanduser().resolve() for value in datapacks or []
    ]
    module_ids = list(dict.fromkeys(modules or []))
    if not resolved and not module_ids:
        raise ValueError("Pass at least one datapack path or module ID.")

    if module_ids:
        options = BuildOptions(build_root=build_root.expanduser().resolve())
        for module_id in module_ids:
            pack_path = _resolve_module_on_disk(module_id, options=options)
            if pack_path is not None:
                resolved.append(pack_path)
            else:
                record = _latest_existing_release_for_module(module_id, options=options)
                resolved.append(record.output_path.resolve())

    return list(dict.fromkeys(resolved))


def load_queries(dataset_path: Path) -> list[QueryCase]:
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    if dataset_path.suffix.lower() == ".csv":
        return _load_queries_csv(dataset_path)

    import polars as pl  # type: ignore[import-not-found]

    frame = pl.read_parquet(dataset_path)
    columns = set(frame.columns)
    if "query" not in columns:
        raise ValueError("Dataset missing required column: 'query'")

    has_expected_ids = "expected_ids" in columns

    queries: list[QueryCase] = []
    for row in frame.iter_rows(named=True):
        query = (row.get("query") or "").strip()
        if not query:
            continue
        if has_expected_ids:
            raw_ids = row.get("expected_ids") or ()
            expected_ids = tuple(s for s in (str(v).strip() for v in raw_ids) if s)
        else:
            expected_ids = ()
        queries.append(
            QueryCase(
                query=query,
                expected_ids=expected_ids,
                category=_clean_optional(row.get("category")),
                difficulty=_clean_optional(row.get("difficulty")),
            )
        )
    if not queries:
        raise ValueError("No non-empty queries found in dataset.")
    return queries


def _load_queries_csv(dataset_path: Path) -> list[QueryCase]:
    """Load query cases from a ``query,expected_ids`` CSV.

    Mirrors the Parquet loader's contract: requires a ``query`` column;
    ``expected_ids`` is optional and may carry multiple ids separated by ``|``
    or whitespace. Used by the autocomplete eval-gate fixtures, which ship as
    CSV rather than Parquet.
    """
    import csv

    queries: list[QueryCase] = []
    with dataset_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or "query" not in reader.fieldnames:
            raise ValueError("Dataset missing required column: 'query'")
        for row in reader:
            query = (row.get("query") or "").strip()
            if not query:
                continue
            raw_ids = (row.get("expected_ids") or "").strip()
            expected_ids = tuple(s for s in raw_ids.replace("|", " ").split() if s)
            queries.append(
                QueryCase(
                    query=query,
                    expected_ids=expected_ids,
                    category=_clean_optional(row.get("category")),
                    difficulty=_clean_optional(row.get("difficulty")),
                )
            )
    if not queries:
        raise ValueError("No non-empty queries found in dataset.")
    return queries


def _clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped if stripped else None


def build_resolver(
    datapacks: list[str | Path],
    *,
    routing_mode: RoutingMode,
    packs: list[str] | None,
) -> Resolver:
    return Resolver.from_datapacks(
        datapack_paths=datapacks,
        domains=packs,
        routing_mode=routing_mode,
    )


def format_pct(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "n/a"
    return f"{(100.0 * numerator / denominator):.2f}%"


def chunk_evenly(items: list[QueryCase], chunks: int) -> list[list[QueryCase]]:
    """Split *items* into *chunks* slices, padding with empty lists if needed.

    The returned list always has exactly *chunks* elements so callers can zip
    directly with a worker list.
    """
    if chunks <= 1:
        return [items]
    size = math.ceil(len(items) / chunks)
    result = [items[index : index + size] for index in range(0, len(items), size)]
    # Pad to exactly `chunks` entries when items < chunks.
    while len(result) < chunks:
        result.append([])
    return result


def format_latency_block(*, latencies_ms: list[float]) -> dict[str, float]:
    """Compute the latency summary block.

    Args:
        latencies_ms: Per-query latency measurements in milliseconds.

    Returns:
        Dict with keys ``min``, ``mean``, ``p50``, ``p95``, ``p99``, ``max``.
        All values are 0.0 when *latencies_ms* is empty.
    """
    if not latencies_ms:
        return {"min": 0.0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
    return {
        "min": min(latencies_ms),
        "mean": _mean(latencies_ms),
        "p50": percentile(latencies_ms, 50),
        "p95": percentile(latencies_ms, 95),
        "p99": percentile(latencies_ms, 99),
        "max": max(latencies_ms),
    }


def render_latency_block(*, block: dict[str, float]) -> str:
    """Format a latency block dict as a human-readable string.

    Args:
        block: A dict as returned by :func:`format_latency_block`.

    Returns:
        Single-line string suitable for printing.
    """
    return (
        f"Latency (ms): "
        f"min={block['min']:.2f}, "
        f"mean={block['mean']:.2f}, "
        f"p50={block['p50']:.2f}, "
        f"p95={block['p95']:.2f}, "
        f"p99={block['p99']:.2f}, "
        f"max={block['max']:.2f}"
    )


def format_status_table(*, status_counts: dict[str, int]) -> list[StatusRow]:
    """Convert a status-count dict to a sorted list of ``StatusRow`` records.

    Args:
        status_counts: Mapping of status label to occurrence count.

    Returns:
        List of :class:`StatusRow` records sorted alphabetically by status.
    """
    return [StatusRow(status=k, count=v) for k, v in sorted(status_counts.items())]


def render_status_table(*, rows: list[StatusRow]) -> str:
    """Format a list of status rows as a human-readable block.

    Args:
        rows: Rows as returned by :func:`format_status_table`.

    Returns:
        Multi-line string with one ``"  <status>: <count>"`` line per row.
    """
    lines = ["Statuses:"]
    lines.extend(f"  {row.status}: {row.count}" for row in rows)
    return "\n".join(lines)


def _resolve_module_on_disk(
    module_id: str,
    *,
    options: BuildOptions,
) -> Path | None:
    """Return the on-disk datapack path for *module_id*, or ``None`` if absent.

    Uses the v1 flat layout (``datapacks_root/<domain>/<subpath>/``) and
    checks for ``entities.sqlite`` as the presence sentinel.  Returns a
    resolved absolute path or ``None`` when the pack is not present on disk.
    """
    try:
        pack_dir = module_pack_dir(
            module_id=module_id, datapacks_root=options.datapacks_root
        )
    except ValueError:
        return None
    if (pack_dir / "entities.sqlite").exists():
        return pack_dir.resolve()
    return None


def _latest_existing_release_for_module(
    module_id: str,
    *,
    options: BuildOptions,
) -> ReleaseRecord:
    releases = list_releases(options=options, module_id=module_id)
    if not releases:
        raise FileNotFoundError(
            f"No releases found for module '{module_id}' in {options.registry_path}"
        )

    for release in releases:
        if release.output_path.exists():
            return release

    raise FileNotFoundError(
        f"No existing datapack output found for module '{module_id}'. "
        f"Checked {len(releases)} release record(s) in {options.registry_path}."
    )


def relative_to_cwd(*, path: Path | str) -> str:
    """Return *path* as a string relative to the current working directory.

    Falls back to the absolute path if *path* is outside the cwd subtree,
    so committed JSON artifacts never contain machine-specific absolute paths.
    """
    p = Path(path).resolve()
    try:
        return str(p.relative_to(Path.cwd()))
    except ValueError:
        return str(p)


def write_metrics_json(output_json: Path | None, metrics: BenchmarkMetrics) -> None:
    if output_json is None:
        return
    output_path = output_json.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Exclude latencies_ms from JSON output (it feeds internal stats only).
    # Replace with [] before asdict() to avoid deep-copying large latency lists.
    serialized = dataclasses.asdict(dataclasses.replace(metrics, latencies_ms=[]))
    serialized.pop("latencies_ms", None)
    output_path.write_text(json.dumps(serialized, indent=2), encoding="utf-8")
    print(f"Wrote JSON metrics: {output_path}")
