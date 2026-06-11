"""Prune old build run intermediates under ``data/build/runs/``.

This standalone maintenance step keeps the *N* most-recently-modified run
directories and deletes the rest. Recency is determined by directory mtime,
independent of the release ledger. Run directories are resumable build state,
not releases — pruning them only discards the ability to ``resume()`` those
specific runs.
"""

from __future__ import annotations

import logging
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from resolvekit.builder.models import BuildOptions

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_KEEP = 5


@dataclass(frozen=True, slots=True, kw_only=True)
class PruneSettings:
    keep: int = DEFAULT_KEEP
    build_root: Path | None = None
    dry_run: bool = False


def prune_run_intermediates(
    *, runs_root: Path, keep: int, dry_run: bool = False
) -> list[Path]:
    """Delete all but the *keep* most-recently-modified run dirs under *runs_root*.

    Returns the run directories selected for deletion (deleted unless
    *dry_run*). Recency is by directory mtime — independent of the ledger.
    """
    if keep < 0:
        raise ValueError(f"keep must be >= 0, got {keep}")
    if not runs_root.exists():
        return []

    run_dirs = sorted(
        (entry for entry in runs_root.iterdir() if entry.is_dir()),
        key=lambda entry: entry.stat().st_mtime,
        reverse=True,
    )
    stale = run_dirs[keep:]
    for run_dir in stale:
        if not dry_run:
            shutil.rmtree(run_dir, ignore_errors=True)
        logger.info(
            "%s run intermediate: %s",
            "WOULD PRUNE" if dry_run else "PRUNED",
            run_dir.name,
        )
    return stale


def main(
    *, keep: int = DEFAULT_KEEP, build_root: Path | None = None, dry_run: bool = False
) -> None:
    """Prune run intermediates, keeping the *keep* most recent run directories."""
    options = (
        BuildOptions(build_root=build_root)
        if build_root is not None
        else BuildOptions(build_root=PROJECT_ROOT / "data" / "build")
    )
    pruned = prune_run_intermediates(
        runs_root=options.runs_root, keep=keep, dry_run=dry_run
    )
    logger.info(
        "%s %d run intermediate(s); kept the %d most recent under %s",
        "Would prune" if dry_run else "Pruned",
        len(pruned),
        keep,
        options.runs_root,
    )


def run(*, settings: PruneSettings) -> None:
    """Entry point that delegates to ``main`` from a ``PruneSettings`` object."""
    main(keep=settings.keep, build_root=settings.build_root, dry_run=settings.dry_run)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(
            "prune_run_intermediates.py takes no CLI arguments. Configure it by "
            "editing PruneSettings(...) in this block (e.g. dry_run=True, keep=10)."
        )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run(settings=PruneSettings())
