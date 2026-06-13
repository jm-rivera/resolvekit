#!/usr/bin/env python3
"""Measure the peak-RAM cost of building the LARGE geo SymSpell index.

Audit finding #1/#2: ``GeoSymSpellSource`` never overrides ``warm()``, so the
background warm thread started by ``Resolver(warm=True)`` builds the LARGE
(admin2-5 / cities, ~764k terms) SymSpell index unconditionally — even when
every query is typed to country/admin1/region tiers and the LARGE
``generate()`` guard would return ``[]`` immediately. The LARGE index is
otherwise lazy-by-design ("often never built"); ``warm=True`` defeats that.

The cities/admin LARGE modules are ``distribution: "remote"`` (not cached on a
fresh box), so this script measures the exact object the finding is about — the
SymSpell index — by building it directly from the bundled ``_data`` dict files,
bypassing the remote-download gate. SMALL vs LARGE are built in isolated
subprocesses (``ru_maxrss`` is a monotonic high-water mark, so per-index deltas
are only trustworthy across process boundaries).

Each index is built from text on a FRESH compiled-cache dir (the cold path the
warm thread takes on first construction), reporting peak RSS and the
tracemalloc Python-heap peak.

Usage:
    uv run python -m scripts.benchmark.measure_warm_memory
"""

from __future__ import annotations

import gc
import json
import os
import resource
import subprocess
import sys
import tempfile
import time
import tracemalloc
from dataclasses import dataclass, field
from pathlib import Path

_DATA_ROOT = (
    Path(__file__).resolve().parents[2] / "src" / "resolvekit" / "_data" / "geo"
)

# SMALL tier: countries, admin1, regions, continents, continental unions.
_SMALL_MODULES = ["countries", "admin1", "regions", "continents", "continental_unions"]
# LARGE tier: admin2-5 / cities (the lazily-built, ~764k-term index).
_LARGE_MODULES = ["admin2", "admin3", "admin4", "admin5", "cities"]

_SCENARIO_ENV = "RESOLVEKIT_MEASURE_SCENARIO"


@dataclass(frozen=True, kw_only=True)
class Scenario:
    name: str
    modules: list[str]
    large_tier: bool


@dataclass(frozen=True, kw_only=True)
class Settings:
    """Edit here; this script is not shell-callable (no argparse)."""

    fresh_cache: bool = True
    scenarios: list[Scenario] = field(
        default_factory=lambda: [
            Scenario(name="small_index", modules=_SMALL_MODULES, large_tier=False),
            Scenario(name="large_index", modules=_LARGE_MODULES, large_tier=True),
        ]
    )


SETTINGS = Settings()


def _maxrss_bytes() -> int:
    """Peak resident set size of this process. ru_maxrss is bytes on macOS, KiB on Linux."""
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss if sys.platform == "darwin" else rss * 1024


def _mb(n: float) -> float:
    return n / (1024 * 1024)


def _dict_paths(modules: list[str]) -> list[str]:
    paths: list[str] = []
    for m in modules:
        p = _DATA_ROOT / m / "symspell.dict"
        if p.is_file():
            paths.append(str(p))
    return paths


def _count_terms(paths: list[str]) -> int:
    total = 0
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            total += sum(1 for _ in fh)
    return total


def _run_scenario_child(scenario: Scenario) -> dict[str, object]:
    """Build one SymSpell index in this (fresh) process and return metrics."""
    from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

    paths = _dict_paths(scenario.modules)
    term_count = _count_terms(paths)

    gc.collect()
    rss_before = _maxrss_bytes()
    tracemalloc.start()
    t0 = time.perf_counter()

    source = GeoSymSpellSource(
        name=f"geo_symspell{'_large' if scenario.large_tier else ''}",
        dictionary_path=paths[0] if paths else None,
        max_edit_distance=2,
        prefix_length=7,
        large_tier=scenario.large_tier,
        use_compiled_cache=scenario.large_tier,
    )
    for extra in paths[1:]:
        source.load_additional_dictionary(extra)
    source.warm()  # build the index synchronously (what the warm thread does)

    build_s = time.perf_counter() - t0
    gc.collect()
    py_current, py_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss_peak = _maxrss_bytes()

    return {
        "scenario": scenario.name,
        "terms": term_count,
        "from_pickle": _pickle_present(paths, scenario.large_tier),
        "build_s": round(build_s, 2),
        "rss_before_mb": round(_mb(rss_before), 1),
        "rss_peak_mb": round(_mb(rss_peak), 1),
        "rss_delta_mb": round(_mb(rss_peak - rss_before), 1),
        "py_heap_peak_mb": round(_mb(py_peak), 1),
        "py_heap_current_mb": round(_mb(py_current), 1),
    }


def _pickle_present(paths: list[str], large_tier: bool) -> bool:
    """Whether a compiled pickle already exists for this build (load-path vs text-build)."""
    if not large_tier:
        return False
    from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

    probe = GeoSymSpellSource(
        name="geo_symspell_large",
        dictionary_path=paths[0] if paths else None,
        large_tier=True,
        use_compiled_cache=True,
    )
    for extra in paths[1:]:
        probe.load_additional_dictionary(extra)
    cache_path = probe._compiled_cache_path(paths)
    return cache_path is not None and cache_path.is_file()


def _spawn_scenario(
    scenario: Scenario, *, cache_dir: str | None = None
) -> dict[str, object]:
    env = dict(os.environ)
    env[_SCENARIO_ENV] = scenario.name
    if cache_dir is not None:
        env["RESOLVEKIT_CACHE_DIR"] = cache_dir
    elif SETTINGS.fresh_cache:
        env["RESOLVEKIT_CACHE_DIR"] = tempfile.mkdtemp(
            prefix=f"rk-mem-{scenario.name}-"
        )
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.benchmark.measure_warm_memory"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"scenario {scenario.name!r} child failed (exit {proc.returncode}):\n{proc.stderr}"
        )
    return json.loads(proc.stdout.strip().splitlines()[-1])


_COLS = [
    ("label", 22),
    ("terms", 9),
    ("build_s", 9),
    ("rss_peak_mb", 12),
    ("rss_delta_mb", 13),
    ("py_heap_peak_mb", 16),
    ("py_heap_current_mb", 19),
]


def _print_table(rows: list[dict[str, object]]) -> None:
    header = "  ".join(name.ljust(w) for name, w in _COLS)
    print(header)
    print("-" * len(header))
    for row in rows:
        print("  ".join(str(row.get(name, "")).ljust(w) for name, w in _COLS))


def _num(row: dict[str, object], key: str) -> float:
    value = row[key]
    assert isinstance(value, (int, float))
    return float(value)


def main() -> None:
    small_s = next(s for s in SETTINGS.scenarios if s.name == "small_index")
    large_s = next(s for s in SETTINGS.scenarios if s.name == "large_index")

    rows: list[dict[str, object]] = []

    small = _spawn_scenario(small_s)
    small["label"] = "small (text build)"
    rows.append(small)

    # Build LARGE twice in a shared cache dir: first run text-builds and writes
    # the compiled pickle; second run loads from that pickle (the steady-state
    # production path after the first construction).
    shared = tempfile.mkdtemp(prefix="rk-mem-large-shared-")
    large_text = _spawn_scenario(large_s, cache_dir=shared)
    large_text["label"] = "large (text build)"
    rows.append(large_text)
    large_pickle = _spawn_scenario(large_s, cache_dir=shared)
    large_pickle["label"] = "large (pickle load)"
    rows.append(large_pickle)

    print()
    _print_table(rows)
    print()
    rss_text = _num(large_text, "rss_delta_mb") - _num(small, "rss_delta_mb")
    rss_pickle = _num(large_pickle, "rss_delta_mb") - _num(small, "rss_delta_mb")
    sustained = _num(large_pickle, "py_heap_current_mb") - _num(
        small, "py_heap_current_mb"
    )
    print(
        "LARGE-tier eager warm cost vs SMALL baseline:\n"
        f"  cold text build  : +{rss_text:.0f} MB peak RSS  "
        f"(first ever construction, ~{_num(large_text, 'build_s'):.0f}s)\n"
        f"  pickle load      : +{rss_pickle:.0f} MB peak RSS  "
        f"(every construction after the first)\n"
        f"  sustained heap   : +{sustained:.0f} MB resident after warm completes\n\n"
        "A workload that loads a city/admin datapack but only queries countries "
        "pays this\nunder warm=True (default) yet never uses it — the LARGE "
        "generate() guard returns []\nfor small-tier entity_types. Overriding "
        "GeoSymSpellSource.warm() to stay lazy avoids it."
    )
    print()


if __name__ == "__main__":
    _scenario_name = os.environ.get(_SCENARIO_ENV)
    if _scenario_name:
        _scenario = next(s for s in SETTINGS.scenarios if s.name == _scenario_name)
        print(json.dumps(_run_scenario_child(_scenario)))
    else:
        main()
