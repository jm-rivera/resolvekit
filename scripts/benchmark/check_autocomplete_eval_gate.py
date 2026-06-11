"""Suggest-mode autocomplete eval gate.

Runs ``resolver.suggest()`` on the committed fixture
``scripts/benchmark/fixtures/autocomplete_country_typos.csv`` and asserts
country success@1, success@5, and MRR against committed thresholds.

Accuracy (success@1, success@5, MRR) is always blocking and deterministic.
Latency is **measured and printed for observability but NOT gated here** —
wall-clock timing on shared CI runners is too variable to hard-assert (cold
first-call swings 250 ms-1.2 s under load; warm p95 8-25 ms), and this repo
keeps real perf benchmarking in ``benchmark.yml``.  The ``max_*_ms`` ceilings
default to ``None`` (advisory); set a float to opt into a hard latency gate
locally, but do not wire one into ``test.yml``.

Configuration: edit ``GateConfig`` directly in ``__main__`` (no argparse).
Run: uv run python -m scripts.benchmark.check_autocomplete_eval_gate
"""

from __future__ import annotations

import csv
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
_FIXTURE_PATH = (
    _REPO_ROOT / "scripts" / "benchmark" / "fixtures" / "autocomplete_country_typos.csv"
)


@dataclass(frozen=True, kw_only=True)
class GateConfig:
    """Thresholds for the suggest-mode autocomplete eval gate.

    Args:
        fixture_csv: Path to the ``query,expected_ids`` fixture CSV.
        top_k: ``top_k`` passed to ``resolver.suggest()``.
        min_success_at_1: Minimum fraction (0-1) of queries with the expected
            entity at rank 1.  Conservative floor; triggers a hard fail.
        min_success_at_5: Minimum fraction (0-1) of queries with the expected
            entity in the top 5.  Primary quality gate.
        min_mrr: Minimum MRR over the fixture.
        max_warm_p95_ms: Warm p95 latency ceiling in ms; ``None`` (default)
            measures and prints but does NOT gate — too flaky on CI runners.
        max_cold_ms: Cold first-call latency ceiling in ms; ``None`` (default)
            measures and prints but does NOT gate.
        warm_reps: Number of warm calls per query used to measure p95.
    """

    fixture_csv: Path = _FIXTURE_PATH
    top_k: int = 10
    min_success_at_1: float = 0.67
    min_success_at_5: float = 0.83
    min_mrr: float = 0.75
    # Latency advisory-only by default (see module docstring). Local opt-in: set a float.
    max_warm_p95_ms: float | None = None
    max_cold_ms: float | None = None
    warm_reps: int = 5


def _fail(msg: str) -> int:
    print(msg, file=sys.stderr)
    return 1


def _load_fixture(path: Path) -> list[tuple[str, str]]:
    """Return list of (query, expected_entity_id) pairs from the CSV."""
    rows: list[tuple[str, str]] = []
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            q = row.get("query", "").strip()
            eid = row.get("expected_ids", "").strip()
            if q and eid:
                rows.append((q, eid))
    return rows


def check_gate(*, config: GateConfig) -> int:
    """Run the suggest-mode eval gate.

    Returns 0 on pass, 1 on any failure.
    """
    if not config.fixture_csv.exists():
        return _fail(f"suggest eval gate: fixture not found at {config.fixture_csv}")

    fixture = _load_fixture(config.fixture_csv)
    if not fixture:
        return _fail("suggest eval gate: fixture is empty")

    # Import here so import errors are surfaced at gate runtime, not at module
    # load time (mirrors check_parse_eval_gate style).
    from resolvekit import Resolver

    # -- Cold-start measurement -----------------------------------------------
    # Resolver.auto() init is separate from the suggest SLO.  Cold measurement
    # (≤ max_cold_ms) covers the first suggest() call only, which triggers
    # lazy name-list materialization on top of a live resolver.
    resolver = Resolver.auto()
    first_query = fixture[0][0]
    cold_start = time.perf_counter()
    _ = resolver.suggest(first_query, top_k=config.top_k, fuzzy="auto")
    cold_ms = (time.perf_counter() - cold_start) * 1000.0

    # -- Warm-run latency measurement (before eval loop) ----------------------
    warm_latencies: list[float] = []
    for q, _ in fixture:
        for _ in range(config.warm_reps):
            t0 = time.perf_counter()
            resolver.suggest(q, top_k=config.top_k, fuzzy="auto")
            warm_latencies.append((time.perf_counter() - t0) * 1000.0)
    warm_latencies.sort()
    warm_p95 = warm_latencies[int(len(warm_latencies) * 0.95)]

    # -- Quality eval (re-run so latency noise doesn't affect rank) -----------
    n = len(fixture)
    success_at_1 = 0
    success_at_5 = 0
    mrr_sum = 0.0

    for q, expected_id in fixture:
        results = resolver.suggest(q, top_k=config.top_k, fuzzy="auto")
        ids = [r.entity_id for r in results]
        rank: int | None = None
        for i, eid in enumerate(ids):
            if eid == expected_id:
                rank = i + 1
                break
        if rank == 1:
            success_at_1 += 1
        if rank is not None and rank <= 5:
            success_at_5 += 1
        mrr_sum += 1.0 / rank if rank is not None else 0.0

    frac_at_1 = success_at_1 / n
    frac_at_5 = success_at_5 / n
    mrr = mrr_sum / n

    # -- Report ---------------------------------------------------------------
    print(f"suggest eval gate: {n} fixture queries")
    print(f"  success@1 = {success_at_1}/{n} ({frac_at_1:.2%})")
    print(f"  success@5 = {success_at_5}/{n} ({frac_at_5:.2%})")
    print(f"  MRR       = {mrr:.4f}")
    print(f"  cold ms   = {cold_ms:.1f}")
    print(f"  warm p95  = {warm_p95:.1f} ms ({len(warm_latencies)} samples)")

    # -- Gates (precision first, then latency) --------------------------------
    exit_code = 0

    if frac_at_1 < config.min_success_at_1:
        exit_code = _fail(
            f"suggest eval gate FAILED: success@1 {frac_at_1:.2%} "
            f"< {config.min_success_at_1:.2%}"
        )
    if frac_at_5 < config.min_success_at_5:
        exit_code = _fail(
            f"suggest eval gate FAILED: success@5 {frac_at_5:.2%} "
            f"< {config.min_success_at_5:.2%}"
        )
    if mrr < config.min_mrr:
        exit_code = _fail(
            f"suggest eval gate FAILED: MRR {mrr:.4f} < {config.min_mrr:.4f}"
        )

    if config.max_cold_ms is not None:
        if cold_ms > config.max_cold_ms:
            exit_code = _fail(
                f"suggest eval gate FAILED: cold {cold_ms:.1f} ms "
                f"> {config.max_cold_ms:.1f} ms"
            )
        else:
            print(
                f"suggest latency gate passed: cold {cold_ms:.1f} ms "
                f"<= {config.max_cold_ms:.1f} ms"
            )

    if config.max_warm_p95_ms is not None:
        if warm_p95 > config.max_warm_p95_ms:
            exit_code = _fail(
                f"suggest eval gate FAILED: warm p95 {warm_p95:.1f} ms "
                f"> {config.max_warm_p95_ms:.1f} ms"
            )
        else:
            print(
                f"suggest latency gate passed: warm p95 {warm_p95:.1f} ms "
                f"<= {config.max_warm_p95_ms:.1f} ms"
            )

    if exit_code == 0:
        print("suggest eval gate passed.")

    return exit_code


if __name__ == "__main__":
    sys.exit(check_gate(config=GateConfig()))
