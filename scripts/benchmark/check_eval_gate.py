"""Eval regression gate — checks resolvekit accuracy against the committed threshold.

Reads ``benchmarks/results/latest.json`` (produced by ``python -m benchmarks``) and
``benchmarks/eval_gate.json`` (committed threshold). Exits non-zero if the gate is
pending or if resolvekit's accuracy falls below the threshold.

Configuration: edit GateConfig directly in __main__ (no argparse).
Run: uv run python -m scripts.benchmark.check_eval_gate
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent


@dataclass(frozen=True, kw_only=True)
class GateConfig:
    """Paths for the gate check.

    Args:
        results_json: Path to the benchmark results JSON (latest.json).
        gate_json: Path to the committed gate threshold file (eval_gate.json).
    """

    results_json: Path = _REPO_ROOT / "benchmarks" / "results" / "latest.json"
    gate_json: Path = _REPO_ROOT / "benchmarks" / "eval_gate.json"


def check_gate(*, config: GateConfig) -> int:
    """Return 0 if resolvekit eval accuracy meets the committed threshold, else 1.

    Returns non-zero immediately when the gate has ``pending: true``, regardless
    of measured accuracy — the threshold must be pinned before the gate is active.

    Args:
        config: Paths to the results JSON and gate JSON files.

    Returns:
        0 on pass, 1 on failure or pending gate.
    """
    gate_data = json.loads(config.gate_json.read_text())

    if gate_data.get("pending", False):
        print(
            "eval gate not yet pinned — run the repin step: "
            "measure resolvekit accuracy on the curated eval set and set "
            "min_accuracy = round(measured - 0.05, 2), then remove the pending key.",
            file=sys.stderr,
        )
        return 1

    expected_dataset: str = gate_data["dataset"]
    expected_tool: str = gate_data["tool"]
    min_accuracy: float = gate_data["min_accuracy"]

    results = json.loads(config.results_json.read_text())
    tools: list[dict] = results.get("tools", [])

    # Find the entry for (dataset, tool) — the eval restriction ensures at most one.
    entry: dict | None = None
    for t in tools:
        if t.get("dataset") == expected_dataset and t.get("name") == expected_tool:
            entry = t
            break

    if entry is None:
        print(
            f"eval gate: no result found for tool={expected_tool!r} "
            f"on dataset={expected_dataset!r} in {config.results_json}",
            file=sys.stderr,
        )
        return 1

    accuracy: float | None = entry.get("metrics", {}).get("accuracy", {}).get("overall")
    if accuracy is None:
        print(
            f"eval gate: accuracy.overall missing for {expected_tool!r} "
            f"on {expected_dataset!r}",
            file=sys.stderr,
        )
        return 1

    if accuracy < min_accuracy:
        print(
            f"eval gate FAILED: {expected_tool} eval accuracy "
            f"{accuracy:.4f} < {min_accuracy:.4f}",
            file=sys.stderr,
        )
        return 1

    print(
        f"eval gate passed: {expected_tool} eval accuracy "
        f"{accuracy:.4f} >= {min_accuracy:.4f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(check_gate(config=GateConfig()))
