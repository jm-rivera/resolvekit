"""Parse eval regression gate — checks resolvekit precision and latency against committed thresholds.

Reads ``benchmarks/results/parse_latest.json`` (produced by ``python -m benchmarks.parse``)
and ``benchmarks/parse_eval_gate.json`` (committed threshold). Exits non-zero if the gate
is pending or if resolvekit's mention-level precision falls below the threshold.

Latency gate (when ``max_p99_ms`` is pinned): presence-based.  If the results carry a
latency block with a non-null ``parse_p99_ms``, the ceiling is enforced (hard fail on
local-dev).  If the latency block is absent or ``parse_p99_ms`` is null — as happens when
``benchmarks.parse`` runs with ``measure_latency=False`` (the CI default) — the gate
emits a WARNING to stderr and passes (exit 0).  Precision is always blocking.

Configuration: edit GateConfig directly in __main__ (no argparse).
Run: uv run python -m scripts.benchmark.check_parse_eval_gate
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent


@dataclass(frozen=True, kw_only=True)
class GateConfig:
    """Paths for the parse eval gate check.

    Args:
        results_json: Path to the parse benchmark results JSON (parse_latest.json).
        gate_json: Path to the committed gate threshold file (parse_eval_gate.json).
    """

    results_json: Path = _REPO_ROOT / "benchmarks" / "results" / "parse_latest.json"
    gate_json: Path = _REPO_ROOT / "benchmarks" / "parse_eval_gate.json"


def _fail(msg: str) -> int:
    print(msg, file=sys.stderr)
    return 1


def _check_latency(*, gate_data: dict, results: dict) -> int:
    """Enforce numeric latency ceiling when max_p99_ms is pinned in the gate.

    Presence-based: only enforces the ceiling when a measured value is actually present.

    - ``max_p99_ms`` absent or non-numeric → skip (back-compat with ``latency_gate: "pending"``).
    - ``max_p99_ms`` numeric, latency block absent or ``parse_p99_ms`` null → WARNING to
      stderr, return 0 (CI runs ``measure_latency=False`` and produces no latency block;
      the missing measurement is not treated as a failure).
    - ``max_p99_ms`` numeric, measured present and above ceiling → fail (return 1).
    - ``max_p99_ms`` numeric, measured present and within ceiling → pass (return 0).

    Returns 0 when the check passes, is warned-and-passed, or is skipped; 1 on failure.
    """
    max_p99 = gate_data.get("max_p99_ms")
    if not isinstance(max_p99, (int, float)):
        return 0
    measured = (results.get("latency") or {}).get("parse_p99_ms")
    if measured is None:
        print(
            "parse latency gate WARNING: no parse_p99_ms in results "
            "(measure_latency=False) - latency not enforced",
            file=sys.stderr,
        )
        return 0
    if measured > max_p99:
        return _fail(
            f"parse latency gate FAILED: p99 {measured:.2f}ms > {max_p99:.2f}ms"
        )
    print(f"parse latency gate passed: p99 {measured:.2f}ms <= {max_p99:.2f}ms")
    return 0


def check_gate(*, config: GateConfig) -> int:
    """Return 0 if resolvekit parse precision meets the committed threshold, else 1.

    Returns non-zero when the precision floor has not yet been pinned (``pending: true``
    in the gate file), when results or gate files are missing, or when the measured
    precision falls below the floor.  Precision is always blocking and evaluated first;
    only when it passes is the latency ceiling checked (see ``_check_latency``).

    Args:
        config: Paths to the results JSON and gate JSON files.

    Returns:
        0 on pass, 1 on failure or pending gate.
    """
    if not config.gate_json.exists():
        return _fail(f"parse eval gate: gate file not found at {config.gate_json}")

    gate_data = json.loads(config.gate_json.read_text())

    if gate_data.get("pending", False):
        return _fail(
            "parse eval gate not yet pinned — run the repin step: "
            "measure resolvekit precision on the curated parse eval set and set "
            "min_precision = round(measured - 0.05, 2), then remove the pending key."
        )

    min_precision: float = gate_data["min_precision"]

    if not config.results_json.exists():
        return _fail(
            f"parse eval gate: results file not found at {config.results_json}"
        )

    results = json.loads(config.results_json.read_text())
    precision: float | None = results.get("precision")

    if precision is None:
        return _fail("parse eval gate: precision field missing from parse_latest.json")

    if precision < min_precision:
        return _fail(
            f"parse eval gate FAILED: resolvekit parse precision "
            f"{precision:.4f} < {min_precision:.4f}"
        )

    print(
        f"parse eval gate passed: resolvekit parse precision "
        f"{precision:.4f} >= {min_precision:.4f}"
    )

    return _check_latency(gate_data=gate_data, results=results)


if __name__ == "__main__":
    sys.exit(check_gate(config=GateConfig()))
