"""Rebuild the bundled base-data packs from their upstream sources.

Drives the module-oriented build pipeline (``resolvekit.builder``) for the
curated presets and writes datapacks in place under
``src/resolvekit/_data/<domain>/<subpath>/``. This is the single entry point
for "rebuild the data" — the library ``build()`` is otherwise only exercised
from tests.

A plain build is an *in-place rebuild*: it overwrites the committed packs and
keeps each pack's on-disk version. It does NOT bump versions, touch the release
ledger, or refresh the aggregate ``_data/manifest.json`` — those are separate,
explicit steps (``scripts.release.release_data`` and
``scripts.release.sync_manifest`` respectively).

Geo builds reuse a persistent staging cache at ``data/build/shared/geo/`` so
re-runs only re-fetch coverage units that are not already ``ready``. Set
``scratch=True`` to clear that cache (and resumable run state) and force a full
re-fetch from Data Commons.

The default Data Commons instance (``datacommons.one.org``) serves without an
API key. To use a key-gated instance, set ``DATACOMMONS_API_KEY`` in the
environment before running.

Run via::

    uv run python -m scripts.build.build_data

To customize, edit the kwargs in the ``__main__`` block at the bottom of the
file (or import ``run()`` and pass a BuildDataSettings from a notebook).
"""

from __future__ import annotations

import logging
import shutil
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from resolvekit.builder import build, presets
from resolvekit.builder.models import BuildOptions, BuildOutcome, BuildPlan, BuildStatus

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_BUILD_ROOT = PROJECT_ROOT / "data" / "build"
_DATAPACKS_ROOT = PROJECT_ROOT / "src" / "resolvekit" / "_data"


class BuildTarget(StrEnum):
    """Which curated preset(s) to build."""

    GEO = "geo"
    ORG = "org"
    ALL = "all"


@dataclass(frozen=True, slots=True, kw_only=True)
class BuildDataSettings:
    """Settings for a base-data rebuild.

    Edit these in the ``__main__`` block; there is no CLI parsing.
    """

    target: BuildTarget = BuildTarget.GEO
    # Clear the shared geo staging cache and resumable run state before building,
    # forcing a full re-fetch from Data Commons (a true "from scratch" build).
    scratch: bool = False
    max_workers: int = 6
    # Optional allowlist of module IDs (e.g. {"geo.countries", "geo.regions"}).
    # When set, only matching recipes from the target preset are built; plans
    # left with no recipes are dropped. None builds the full preset.
    modules: frozenset[str] | None = None


def _options(settings: BuildDataSettings) -> BuildOptions:
    """Build options anchored to the repo roots, independent of the cwd."""
    return BuildOptions(
        build_root=_BUILD_ROOT,
        datapacks_root=_DATAPACKS_ROOT,
        max_workers=settings.max_workers,
        reconcile_relation_types=["contained_in", "subsidiary_of"],
    )


def _clear_scratch_state(options: BuildOptions) -> None:
    """Remove the shared geo cache and resumable run state for a fresh build."""
    for path in (options.shared_geo_root, options.runs_root):
        if path.exists():
            logger.info("Clearing %s", path)
            shutil.rmtree(path, ignore_errors=True)


def _plans(settings: BuildDataSettings, options: BuildOptions) -> list[BuildPlan]:
    """Resolve the build plan(s) for the requested target.

    Geo and org build as separate plans so geo's shared-store flow stays
    isolated and each domain's outcome is reported independently. When
    ``settings.modules`` is set, each plan's recipes are filtered to the
    allowlist and empty plans are dropped.
    """
    match settings.target:
        case BuildTarget.GEO:
            base = [presets.geo(options)]
        case BuildTarget.ORG:
            base = [presets.org(options)]
        case BuildTarget.ALL:
            base = [presets.geo(options), presets.org(options)]

    if settings.modules is None:
        return base

    filtered: list[BuildPlan] = []
    for plan in base:
        recipes = [r for r in plan.recipes if r.module_id in settings.modules]
        if recipes:
            filtered.append(plan.model_copy(update={"recipes": recipes}))
    return filtered


def _log_outcome(outcome: BuildOutcome) -> None:
    """Log a one-line summary plus per-module metrics and any errors."""
    logger.info(
        "Build %s at stage=%s run_id=%s (%d module(s) produced)",
        outcome.status.value,
        outcome.stage,
        outcome.run_id,
        len(outcome.releases),
    )
    for record in outcome.releases:
        entity_count = record.metrics.get(f"{record.domains[0]}.entity_count")
        suffix = f" entities={int(entity_count)}" if entity_count is not None else ""
        logger.info("  built %s%s", record.module_id, suffix)
    for error in outcome.errors:
        logger.error("  %s", error)


def run(*, settings: BuildDataSettings) -> list[BuildOutcome]:
    """Rebuild the requested packs and return one outcome per plan.

    Raises ``SystemExit(1)`` if any plan fails so the process surfaces a
    non-zero exit code to callers and CI.
    """
    options = _options(settings)
    if settings.scratch:
        _clear_scratch_state(options)

    outcomes: list[BuildOutcome] = []
    failed = False
    for plan in _plans(settings, options):
        domains = sorted({recipe.domain for recipe in plan.recipes})
        logger.info(
            "Building %s (%d recipe(s)) from %s",
            ", ".join(domains),
            len(plan.recipes),
            options.datacommons_instance,
        )
        outcome = build(plan)
        _log_outcome(outcome)
        outcomes.append(outcome)
        failed = failed or outcome.status is not BuildStatus.SUCCESS

    if failed:
        raise SystemExit(1)
    return outcomes


def build_all_bundles(
    *, settings: BuildDataSettings | None = None
) -> list[BuildOutcome]:
    """Rebuild all curated packs AND geo.continents in one pass.

    Runs the normal geo+org build (via ``run()``) then rebuilds
    ``geo.continents`` as a final step so the continents pack is never
    left at a different ``entity_schema_version`` than the rest of the
    fleet.  Use this entry point whenever ``ENTITY_SCHEMA_VERSION`` in
    ``resolvekit.core.datapack`` changes — ``build_data.py`` alone does
    not touch continents.

    Run context: must be invoked via ``uv run python -m scripts.build.build_data``
    (or ``uv run python -c "from scripts.build.build_data import
    build_all_bundles; ..."``).  The ``scripts.build.build_continents``
    import only resolves when the repo root is on ``sys.path``, which
    ``uv run`` ensures automatically.

    Args:
        settings: Optional build settings.  Defaults to
            ``BuildDataSettings(target=BuildTarget.ALL)`` so both geo
            and org are rebuilt.  Pass an explicit instance to restrict
            to a single domain or enable scratch mode.

    Returns:
        Outcomes from the normal build.  The continents build exits the
        process on failure (``SystemExit(1)``) rather than returning an
        outcome; successful completion is implicit in a clean return.
    """
    if settings is None:
        settings = BuildDataSettings(target=BuildTarget.ALL)
    outcomes = run(settings=settings)

    # Continents is a standalone seed-driven pack not covered by the
    # presets in run(); import and call it directly so it stays in lock
    # step with the rest of the fleet on every schema-version change.
    from scripts.build.build_continents import (
        main as _build_continents,
    )

    logger.info("Running geo.continents build as final step")
    _build_continents()

    return outcomes


def main() -> None:
    """Entry point for direct invocation; edit settings below to customize."""
    run(settings=BuildDataSettings())


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(
            "build_data.py takes no CLI arguments. Configure it by editing "
            "BuildDataSettings(...) in this block (e.g. target=BuildTarget.ALL, "
            "scratch=True)."
        )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # To rebuild all bundles including geo.continents, call:
    #   build_all_bundles()
    # instead of main() above.  Not executed by default — runs a full build.
    main()
