#!/usr/bin/env python3
"""Profile resolvekit hot paths on a representative geo query mix.

In-process, single-threaded diagnostic using cProfile or wall-clock
measurements. Reuses benchmark helpers but does not join the worker framework.

Usage:
    uv run python -m scripts.benchmark.profile_resolver
"""

from __future__ import annotations

import contextlib
import cProfile
import dataclasses
import pstats
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from resolvekit.core.api import Resolver
from resolvekit.core.engine.router import RoutingMode
from scripts.benchmark.benchmark_common import (
    build_resolver,
    load_query_cases,
    resolve_datapacks,
)


class _CategoryRow(TypedDict):
    category: str
    n: int
    mean_ms: float
    qps: float


class _TimeRunResult(TypedDict):
    elapsed_seconds: float
    qps: float
    n: int
    statuses: dict[str, int]
    by_category: list[_CategoryRow]


DEFAULT_DATASETS = [
    Path("benchmarks/data/geo_countries_en.parquet"),
    Path("benchmarks/data/no_match.parquet"),
]


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileSettings:
    """Settings for a profiling run."""

    queries: int = 5000
    warmup: int = 200
    cprofile: bool = False
    top: int = 30
    only_cat: str | None = None
    datasets: list[Path] | None = None
    modules: tuple[str, ...] = dataclasses.field(
        default_factory=lambda: ("geo.countries",)
    )


def _do_warmup(
    resolver: Resolver, queries: list[tuple[str, str]], n: int = 200
) -> None:
    for q, _ in queries[:n]:
        with contextlib.suppress(Exception):
            resolver.resolve(q, to=None)


def time_run(resolver: Resolver, queries: list[tuple[str, str]]) -> _TimeRunResult:
    by_cat: Counter[str] = Counter()
    by_cat_ms: dict[str, float] = {}
    statuses: Counter[str] = Counter()
    start = time.perf_counter()
    for q, cat in queries:
        t0 = time.perf_counter()
        try:
            res = resolver.resolve(q, to=None)
            statuses[res.status.value] += 1
        except Exception as e:
            statuses[f"error:{type(e).__name__}"] += 1
        dt = time.perf_counter() - t0
        by_cat[cat] += 1
        by_cat_ms[cat] = by_cat_ms.get(cat, 0.0) + dt * 1000.0
    elapsed = time.perf_counter() - start
    qps = len(queries) / elapsed if elapsed else 0.0
    return {
        "elapsed_seconds": elapsed,
        "qps": qps,
        "n": len(queries),
        "statuses": dict(statuses),
        "by_category": [
            {
                "category": c,
                "n": n,
                "mean_ms": by_cat_ms[c] / n,
                "qps": n / (by_cat_ms[c] / 1000.0) if by_cat_ms.get(c) else 0.0,
            }
            for c, n in by_cat.most_common()
        ],
    }


def cprofile_run(
    resolver: Resolver, queries: list[tuple[str, str]], top: int = 30
) -> None:
    pr = cProfile.Profile()
    pr.enable()
    for q, _ in queries:
        with contextlib.suppress(Exception):
            resolver.resolve(q, to=None)
    pr.disable()
    st = pstats.Stats(pr)
    st.sort_stats("cumulative").print_stats(top)
    st.sort_stats("tottime").print_stats(top)


def run(*, settings: ProfileSettings) -> None:
    """Profile the resolver on a representative geo query mix.

    Args:
        settings: Profiling run settings (queries, warmup, cprofile, etc.).
    """
    paths = settings.datasets if settings.datasets else DEFAULT_DATASETS

    print("Loading resolver…")
    t0 = time.perf_counter()
    datapacks = resolve_datapacks(
        datapacks=[],
        modules=list(settings.modules),
        build_root=Path("data/build"),
    )
    resolver = build_resolver(datapacks, routing_mode=RoutingMode.AUTO, packs=None)
    init_s = time.perf_counter() - t0
    print(f"Init: {init_s:.3f}s")

    print(f"Loading queries from {[str(p) for p in paths]}")
    query_rows: list[tuple[str, str]] = []
    for path in paths:
        cases = load_query_cases(
            dataset_path=path,
            shuffle=False,
            seed=42,
            limit=None,
        )
        query_rows.extend((c.query, c.category or path.stem) for c in cases)

    if settings.only_cat:
        query_rows = [(q, c) for q, c in query_rows if c == settings.only_cat]
        print(
            f"Filtered to category={settings.only_cat}: {len(query_rows)} queries available"
        )
    query_rows = query_rows[: settings.queries] if settings.queries > 0 else query_rows
    print(f"Total queries: {len(query_rows)}")

    print(f"Warmup ({settings.warmup})…")
    _do_warmup(resolver, query_rows, settings.warmup)

    if settings.cprofile:
        print("\n=== cProfile ===")
        cprofile_run(resolver, query_rows, top=settings.top)
    else:
        print("\n=== Wall-clock per category ===")
        results = time_run(resolver, query_rows)
        print(
            f"Total: {results['n']} queries in {results['elapsed_seconds']:.3f}s"
            f" = {results['qps']:.1f} qps"
        )
        print(f"Statuses: {results['statuses']}")
        for row in results["by_category"]:
            print(
                f"  {row['category']:20s} n={row['n']:6d}"
                f" mean={row['mean_ms']:.3f}ms qps={row['qps']:.0f}"
            )

    resolver.close()


if __name__ == "__main__":
    run(settings=ProfileSettings())
