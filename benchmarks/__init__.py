"""Public benchmark API for resolvekit.

Usage::

    from benchmarks import run_benchmark, load_dataset
    report = run_benchmark(
        tools=["resolvekit", "pycountry"],
        datasets=["geo_countries_en"],
    )
"""

from __future__ import annotations

from benchmarks.core.engine import run_benchmark
from benchmarks.core.kernel import Query, Response, Status
from benchmarks.core.loader import DATASET_NAMES, load_dataset
from benchmarks.core.report import BenchmarkReport, ToolResult
from benchmarks.core.toolspec import ToolSpec
from benchmarks.tools.protocol import ResolverAdapter

__all__ = [
    "DATASET_NAMES",
    "BenchmarkReport",
    "Query",
    "ResolverAdapter",
    "Response",
    "Status",
    "ToolResult",
    "ToolSpec",
    "load_dataset",
    "run_benchmark",
]
