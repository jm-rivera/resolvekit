"""Tests for the eval regression gate.

Verifies exit codes for: accuracy above/below threshold, missing tool entry,
and pending gate (fail regardless of accuracy).
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.benchmark.check_eval_gate import GateConfig, check_gate


def _write_results(tmp_path: Path, *, accuracy: float, dataset: str, tool: str) -> Path:
    """Write a minimal latest.json with one tool result."""
    results = {
        "tools": [
            {
                "dataset": dataset,
                "name": tool,
                "metrics": {
                    "accuracy": {"overall": accuracy},
                },
            }
        ]
    }
    p = tmp_path / "latest.json"
    p.write_text(json.dumps(results))
    return p


def _write_gate(
    tmp_path: Path,
    *,
    min_accuracy: float,
    pending: bool = False,
    dataset: str = "eval_geo",
    tool: str = "resolvekit",
) -> Path:
    """Write a gate JSON file."""
    data: dict = {
        "dataset": dataset,
        "tool": tool,
        "min_accuracy": min_accuracy,
    }
    if pending:
        data["pending"] = True
    p = tmp_path / "eval_gate.json"
    p.write_text(json.dumps(data))
    return p


def test_check_gate_passes_when_above_threshold(tmp_path: Path) -> None:
    """Returns 0 when resolvekit accuracy exceeds min_accuracy."""
    results = _write_results(
        tmp_path, accuracy=0.80, dataset="eval_geo", tool="resolvekit"
    )
    gate = _write_gate(tmp_path, min_accuracy=0.70)
    config = GateConfig(results_json=results, gate_json=gate)
    assert check_gate(config=config) == 0


def test_check_gate_passes_when_exactly_at_threshold(tmp_path: Path) -> None:
    """Returns 0 when accuracy equals min_accuracy (inclusive lower bound)."""
    results = _write_results(
        tmp_path, accuracy=0.70, dataset="eval_geo", tool="resolvekit"
    )
    gate = _write_gate(tmp_path, min_accuracy=0.70)
    config = GateConfig(results_json=results, gate_json=gate)
    assert check_gate(config=config) == 0


def test_check_gate_fails_when_below_threshold(tmp_path: Path) -> None:
    """Returns 1 when resolvekit accuracy is below min_accuracy."""
    results = _write_results(
        tmp_path, accuracy=0.65, dataset="eval_geo", tool="resolvekit"
    )
    gate = _write_gate(tmp_path, min_accuracy=0.70)
    config = GateConfig(results_json=results, gate_json=gate)
    assert check_gate(config=config) == 1


def test_check_gate_fails_when_tool_missing(tmp_path: Path) -> None:
    """Returns 1 with a clear message when the tool entry is absent from results."""
    results_data = {"tools": []}
    results = tmp_path / "latest.json"
    results.write_text(json.dumps(results_data))
    gate = _write_gate(tmp_path, min_accuracy=0.70)
    config = GateConfig(results_json=results, gate_json=gate)
    assert check_gate(config=config) == 1


def test_check_gate_fails_when_pending_with_low_accuracy(tmp_path: Path) -> None:
    """Returns 1 when gate is pending, even when accuracy is 0.0 (below any real threshold)."""
    results = _write_results(
        tmp_path, accuracy=0.0, dataset="eval_geo", tool="resolvekit"
    )
    gate = _write_gate(tmp_path, min_accuracy=0.0, pending=True)
    config = GateConfig(results_json=results, gate_json=gate)
    assert check_gate(config=config) == 1


def test_check_gate_fails_when_pending_even_with_high_accuracy(tmp_path: Path) -> None:
    """Returns 1 when gate is pending, regardless of accuracy.

    Pending gate signals an unpinned threshold; accuracy cannot override this.
    """
    results = _write_results(
        tmp_path, accuracy=0.99, dataset="eval_geo", tool="resolvekit"
    )
    gate = _write_gate(tmp_path, min_accuracy=0.0, pending=True)
    config = GateConfig(results_json=results, gate_json=gate)
    assert check_gate(config=config) == 1


def test_check_gate_fails_when_accuracy_missing(tmp_path: Path) -> None:
    """Returns 1 when the accuracy.overall field is absent from the tool result."""
    results_data = {
        "tools": [
            {
                "dataset": "eval_geo",
                "name": "resolvekit",
                "metrics": {},
            }
        ]
    }
    results = tmp_path / "latest.json"
    results.write_text(json.dumps(results_data))
    gate = _write_gate(tmp_path, min_accuracy=0.70)
    config = GateConfig(results_json=results, gate_json=gate)
    assert check_gate(config=config) == 1


def test_gate_config_defaults_to_repo_paths() -> None:
    """GateConfig default paths point into the repo (not /tmp or tests)."""
    config = GateConfig()
    assert "benchmarks" in str(config.results_json)
    assert "benchmarks" in str(config.gate_json)
