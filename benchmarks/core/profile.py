"""Subprocess tool profiler.

``measure_profile`` runs a fresh interpreter per tool so each tool's peak
RSS is measured independently (an in-process run would let a tool inherit
an earlier tool's already-loaded heap, inflating its footprint).

``wheel_size_mb`` is computed in-process (deterministic filesystem stat) and
folded into ``ToolProfile`` alongside the subprocess measurements.  For
resolvekit, ``data_size_mb`` is also computed from the package manifest so
the benchmark report can show the full on-demand data footprint separately.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from benchmarks.core.metrics import data_size_mb_from_manifest, wheel_size_mb

if TYPE_CHECKING:
    from benchmarks.tools.protocol import ResolverAdapter

# One subprocess per tool: import → construct → warmup → one resolve().
# Prints a single JSON line: {"cold_start_ms": float, "peak_rss_mb": float | null,
#                             "version": str | null}
_PROFILE_SCRIPT = """
import json
import sys
import time

# Peak RSS capture — platform-aware normalization
def _peak_rss_mb():
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return rss / (1024 ** 2)   # bytes → MiB
        return rss / 1024              # KiB → MiB (linux)
    except Exception:
        return None

from benchmarks.tools import {class_name}
from benchmarks.core.kernel import Query

start = time.perf_counter()
adapter = {class_name}()
adapter.warmup()
adapter.resolve(Query(query_id="", text={query!r}, expected_ids=(), language="en",
                      entity_type="country", category="", difficulty="",
                      capabilities=(), source="", notes=None))
elapsed_ms = (time.perf_counter() - start) * 1000.0

peak_rss_mb = _peak_rss_mb()
try:
    version = adapter.version()
except Exception:
    version = None

print(json.dumps({{"cold_start_ms": elapsed_ms, "peak_rss_mb": peak_rss_mb,
                   "version": version}}))
"""


@dataclass(frozen=True)
class ToolProfile:
    """Per-tool measurements collected from a dedicated subprocess."""

    version: str | None
    wheel_size_mb: float | None
    data_size_mb: float | None
    cold_start_ms: float | None
    peak_rss_mb: float | None


# Path to resolvekit's manifest, relative to this file.  Used to compute the
# separate on-demand data footprint; other tools have no remote data packs.
_RESOLVEKIT_MANIFEST = (
    Path(__file__).parent.parent.parent
    / "src"
    / "resolvekit"
    / "_data"
    / "manifest.json"
)


def _resolvekit_data_size_mb() -> float | None:
    """Return the sum of size_mb for all remote modules in resolvekit's manifest."""
    return data_size_mb_from_manifest(manifest_path=_RESOLVEKIT_MANIFEST)


def measure_profile(
    *,
    adapter_cls: type[ResolverAdapter],
    first_query: str,
    distribution: str,
) -> ToolProfile:
    """Measure cold-start latency and peak RSS in a fresh subprocess.

    ``wheel_size_mb`` is computed in-process (cheap, deterministic) and folded
    into the returned profile.  For resolvekit, ``data_size_mb`` is also
    computed from the package manifest to report the on-demand data footprint
    separately.  On timeout or subprocess failure all subprocess fields are
    ``None``.
    """
    w_mb = wheel_size_mb(dist_name=distribution)
    d_mb = _resolvekit_data_size_mb() if distribution == "resolvekit" else None

    # All subprocess fields are None when the profiling run fails; only
    # wheel_size_mb / data_size_mb (measured in-process) survive.
    def _failed() -> ToolProfile:
        return ToolProfile(
            version=None,
            wheel_size_mb=w_mb,
            data_size_mb=d_mb,
            cold_start_ms=None,
            peak_rss_mb=None,
        )

    script = _PROFILE_SCRIPT.format(
        class_name=adapter_cls.__name__,
        query=first_query,
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return _failed()

    if completed.returncode != 0:
        return _failed()

    last_line = (completed.stdout or "").strip().splitlines()[-1:]
    if not last_line:
        return _failed()

    try:
        data = json.loads(last_line[0])
    except (ValueError, KeyError):
        return _failed()

    cold_start_ms = data.get("cold_start_ms")
    peak_rss_mb = data.get("peak_rss_mb")
    version = data.get("version")

    return ToolProfile(
        version=version if isinstance(version, str) else None,
        wheel_size_mb=w_mb,
        data_size_mb=d_mb,
        cold_start_ms=float(cold_start_ms) if cold_start_ms is not None else None,
        peak_rss_mb=float(peak_rss_mb) if peak_rss_mb is not None else None,
    )
