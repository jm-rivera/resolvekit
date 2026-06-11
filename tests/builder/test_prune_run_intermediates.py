"""Unit tests for the run-intermediate prune script.

(scripts/data_maintenance/prune_run_intermediates.py)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.data_maintenance.prune_run_intermediates import (
    main,
    prune_run_intermediates,
)


def _make_run_dir(runs_root: Path, name: str, *, mtime: float) -> Path:
    """Create a run dir with a file and a fixed mtime (for deterministic order)."""
    run_dir = runs_root / name
    run_dir.mkdir(parents=True)
    (run_dir / "state.sqlite").write_text("x")
    os.utime(run_dir, (mtime, mtime))
    return run_dir


def test_keeps_most_recent_and_prunes_the_rest(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    # mtimes ascending: r0 oldest ... r4 newest.
    dirs = [_make_run_dir(runs_root, f"r{i}", mtime=1000 + i) for i in range(5)]

    pruned = prune_run_intermediates(runs_root=runs_root, keep=2)

    assert {p.name for p in pruned} == {"r0", "r1", "r2"}
    # The two newest survive; the rest are gone.
    assert {d.name for d in runs_root.iterdir()} == {"r3", "r4"}
    assert all(not d.exists() for d in dirs[:3])


def test_dry_run_deletes_nothing(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    for i in range(4):
        _make_run_dir(runs_root, f"r{i}", mtime=1000 + i)

    pruned = prune_run_intermediates(runs_root=runs_root, keep=1, dry_run=True)

    assert {p.name for p in pruned} == {"r0", "r1", "r2"}
    # Nothing actually removed.
    assert {d.name for d in runs_root.iterdir()} == {"r0", "r1", "r2", "r3"}


def test_keep_at_or_above_count_is_noop(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    for i in range(3):
        _make_run_dir(runs_root, f"r{i}", mtime=1000 + i)

    assert prune_run_intermediates(runs_root=runs_root, keep=5) == []
    assert len(list(runs_root.iterdir())) == 3


def test_missing_runs_root_returns_empty(tmp_path: Path) -> None:
    assert prune_run_intermediates(runs_root=tmp_path / "nope", keep=3) == []


def test_negative_keep_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="keep must be >= 0"):
        prune_run_intermediates(runs_root=tmp_path, keep=-1)


def test_ignores_loose_files(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _make_run_dir(runs_root, "r0", mtime=1000)
    (runs_root / "stray.txt").write_text("not a run dir")

    # Only the one run dir exists; keeping 5 prunes nothing, loose file untouched.
    assert prune_run_intermediates(runs_root=runs_root, keep=5) == []
    assert (runs_root / "stray.txt").exists()


def test_main_resolves_runs_root_from_build_root(tmp_path: Path) -> None:
    build_root = tmp_path / "build"
    runs_root = build_root / "runs"
    runs_root.mkdir(parents=True)
    for i in range(4):
        _make_run_dir(runs_root, f"r{i}", mtime=1000 + i)

    main(keep=1, build_root=build_root)

    assert {d.name for d in runs_root.iterdir()} == {"r3"}
