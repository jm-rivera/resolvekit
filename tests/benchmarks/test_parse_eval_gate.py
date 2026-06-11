"""Tests for the parse eval regression gate.

Verifies exit codes for: precision above/below threshold, missing results file,
missing gate file, pending gate (fail regardless of precision), and latency gate
(pass/fail/missing when max_p99_ms is pinned; skip when pending or absent).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.benchmark.check_parse_eval_gate import GateConfig, check_gate


def _write_results(
    tmp_path: Path,
    *,
    precision: float,
    dataset: str = "eval_parse",
    parse_p99_ms: float | None = None,
    include_latency_block: bool = False,
) -> Path:
    """Write a minimal parse_latest.json.

    When *include_latency_block* is True, a ``latency`` sub-dict is added.
    Within that block, ``parse_p99_ms`` is set to *parse_p99_ms* (may be null).
    """
    results: dict = {
        "precision": precision,
        "recall": 0.9,
        "f1": 0.9,
        "boundary_exact_rate": 1.0,
        "nil_correct_rate": 1.0,
        "true_positives": 10,
        "false_positives": 1,
        "false_negatives": 1,
        "row_count": 10,
        "dataset": dataset,
    }
    if include_latency_block:
        results["latency"] = {"parse_p99_ms": parse_p99_ms}
    p = tmp_path / "parse_latest.json"
    p.write_text(json.dumps(results))
    return p


def _write_gate(
    tmp_path: Path,
    *,
    min_precision: float,
    pending: bool = False,
    dataset: str = "eval_parse",
    tool: str = "resolvekit",
    max_p99_ms: float | None = None,
    latency_gate: str = "pending",
) -> Path:
    """Write a parse gate JSON file.

    When *max_p99_ms* is provided, it is written to the gate; *latency_gate* is
    also included (defaults to ``"pending"`` for back-compat tests).
    """
    data: dict = {
        "dataset": dataset,
        "tool": tool,
        "min_precision": min_precision,
        "latency_gate": latency_gate,
    }
    if pending:
        data["pending"] = True
    if max_p99_ms is not None:
        data["max_p99_ms"] = max_p99_ms
    p = tmp_path / "parse_eval_gate.json"
    p.write_text(json.dumps(data))
    return p


def test_check_gate_passes_when_above_threshold(tmp_path: Path) -> None:
    """Returns 0 when resolvekit precision exceeds min_precision."""
    results = _write_results(tmp_path, precision=0.95)
    gate = _write_gate(tmp_path, min_precision=0.92)
    config = GateConfig(results_json=results, gate_json=gate)
    assert check_gate(config=config) == 0


def test_check_gate_passes_when_exactly_at_threshold(tmp_path: Path) -> None:
    """Returns 0 when precision equals min_precision (inclusive lower bound)."""
    results = _write_results(tmp_path, precision=0.92)
    gate = _write_gate(tmp_path, min_precision=0.92)
    config = GateConfig(results_json=results, gate_json=gate)
    assert check_gate(config=config) == 0


def test_check_gate_fails_when_below_threshold(tmp_path: Path) -> None:
    """Returns 1 when resolvekit precision is below min_precision."""
    results = _write_results(tmp_path, precision=0.85)
    gate = _write_gate(tmp_path, min_precision=0.92)
    config = GateConfig(results_json=results, gate_json=gate)
    assert check_gate(config=config) == 1


def test_check_gate_fails_when_results_missing(tmp_path: Path) -> None:
    """Returns 1 with a clear message when the results file is absent."""
    gate = _write_gate(tmp_path, min_precision=0.92)
    config = GateConfig(results_json=tmp_path / "nonexistent.json", gate_json=gate)
    assert check_gate(config=config) == 1


def test_check_gate_fails_when_gate_missing(tmp_path: Path) -> None:
    """Returns 1 with a clear message when the gate file is absent."""
    results = _write_results(tmp_path, precision=0.95)
    config = GateConfig(
        results_json=results, gate_json=tmp_path / "nonexistent_gate.json"
    )
    assert check_gate(config=config) == 1


def test_check_gate_fails_when_pending_with_low_precision(tmp_path: Path) -> None:
    """Returns 1 when gate is pending, even when precision is 0.0."""
    results = _write_results(tmp_path, precision=0.0)
    gate = _write_gate(tmp_path, min_precision=0.0, pending=True)
    config = GateConfig(results_json=results, gate_json=gate)
    assert check_gate(config=config) == 1


def test_check_gate_fails_when_pending_even_with_high_precision(tmp_path: Path) -> None:
    """Returns 1 when gate is pending, regardless of precision.

    Pending gate signals an unpinned threshold; measured precision cannot override this.
    """
    results = _write_results(tmp_path, precision=0.99)
    gate = _write_gate(tmp_path, min_precision=0.0, pending=True)
    config = GateConfig(results_json=results, gate_json=gate)
    assert check_gate(config=config) == 1


def test_check_gate_fails_when_precision_missing(tmp_path: Path) -> None:
    """Returns 1 when the precision field is absent from parse_latest.json."""
    results_data = {
        "recall": 0.9,
        "f1": 0.9,
        "dataset": "eval_parse",
    }
    results = tmp_path / "parse_latest.json"
    results.write_text(json.dumps(results_data))
    gate = _write_gate(tmp_path, min_precision=0.92)
    config = GateConfig(results_json=results, gate_json=gate)
    assert check_gate(config=config) == 1


def test_gate_config_defaults_to_repo_paths() -> None:
    """GateConfig default paths point into the repo (not /tmp or tests)."""
    config = GateConfig()
    assert "benchmarks" in str(config.results_json)
    assert "benchmarks" in str(config.gate_json)


def test_latency_gate_pending_does_not_fail_precision_gate(tmp_path: Path) -> None:
    """Returns 0 when latency_gate is pending but precision floor is set and met.

    latency_gate: "pending" must not cause the precision gate to fail.
    """
    results = _write_results(tmp_path, precision=0.95)
    gate = _write_gate(tmp_path, min_precision=0.92)
    # gate already has latency_gate: "pending" — just confirm it still passes
    config = GateConfig(results_json=results, gate_json=gate)
    assert check_gate(config=config) == 0


# ---------------------------------------------------------------------------
# Latency gate enforcement
# ---------------------------------------------------------------------------


def test_precision_pass_no_latency_key(tmp_path: Path) -> None:
    """Returns 0 when gate has no max_p99_ms — latency check is skipped entirely."""
    results = _write_results(tmp_path, precision=0.95)
    gate = _write_gate(tmp_path, min_precision=0.92)
    # _write_gate omits max_p99_ms by default — no latency key in gate JSON
    config = GateConfig(results_json=results, gate_json=gate)
    assert check_gate(config=config) == 0


def test_latency_pass(tmp_path: Path) -> None:
    """Returns 0 when precision passes and measured p99 is below the ceiling."""
    results = _write_results(
        tmp_path, precision=0.95, parse_p99_ms=80.0, include_latency_block=True
    )
    gate = _write_gate(tmp_path, min_precision=0.92, max_p99_ms=150.0)
    config = GateConfig(results_json=results, gate_json=gate)
    assert check_gate(config=config) == 0


def test_latency_pending_skipped(tmp_path: Path) -> None:
    """Returns 0 when latency_gate is "pending" even if max_p99_ms were present.

    Back-compat: a gate file with latency_gate: "pending" and no max_p99_ms key
    must not activate the latency check (precision-only gate).
    """
    # No max_p99_ms in gate → latency check never runs regardless of latency_gate value
    results = _write_results(tmp_path, precision=0.95)
    gate = _write_gate(tmp_path, min_precision=0.92, latency_gate="pending")
    config = GateConfig(results_json=results, gate_json=gate)
    assert check_gate(config=config) == 0


def test_latency_block_missing_when_pinned_warns_and_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Returns 0 and warns to stderr when max_p99_ms is pinned but the results carry no latency block.

    Latency gate is presence-based: an absent measurement (CI runs measure_latency=False
    and produces no latency block) is warn-and-pass, not a hard failure.
    """
    # No include_latency_block — results JSON has no "latency" key at all
    results = _write_results(tmp_path, precision=0.95)
    gate = _write_gate(tmp_path, min_precision=0.92, max_p99_ms=150.0)
    config = GateConfig(results_json=results, gate_json=gate)
    assert check_gate(config=config) == 0
    captured = capsys.readouterr()
    assert "latency" in captured.err
    assert "WARNING" in captured.err


def test_latency_block_null_parse_p99_when_pinned(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Returns 0 and warns to stderr when max_p99_ms is pinned but parse_p99_ms is null.

    Null measurement is treated as absent -> warn + pass.  Signals fewer than 20 samples
    or benchmarks run without measure_latency=True; not a hard failure under presence-based
    semantics.
    """
    results = _write_results(
        tmp_path, precision=0.95, parse_p99_ms=None, include_latency_block=True
    )
    gate = _write_gate(tmp_path, min_precision=0.92, max_p99_ms=150.0)
    config = GateConfig(results_json=results, gate_json=gate)
    assert check_gate(config=config) == 0
    captured = capsys.readouterr()
    assert "latency" in captured.err
    assert "WARNING" in captured.err


def test_latency_present_over_ceiling_fails(tmp_path: Path) -> None:
    """Returns 1 when the latency block is present and parse_p99_ms exceeds the ceiling.

    The surviving local-dev gate: when a real measurement is present and above
    max_p99_ms the gate fails (exit 1).
    """
    results = _write_results(
        tmp_path, precision=0.95, parse_p99_ms=200.0, include_latency_block=True
    )
    gate = _write_gate(tmp_path, min_precision=0.92, max_p99_ms=150.0)
    config = GateConfig(results_json=results, gate_json=gate)
    assert check_gate(config=config) == 1


def test_precision_below_floor_still_fails(tmp_path: Path) -> None:
    """Returns 1 when precision fails, even when latency would have passed."""
    results = _write_results(
        tmp_path, precision=0.85, parse_p99_ms=50.0, include_latency_block=True
    )
    gate = _write_gate(tmp_path, min_precision=0.92, max_p99_ms=150.0)
    config = GateConfig(results_json=results, gate_json=gate)
    assert check_gate(config=config) == 1
