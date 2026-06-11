"""Geo-specific helpers used by stage_prepare/discover/materialize/package.

Two related concerns coexist here because they share state and run
in tight succession during a build:

* Coverage policy — what units are required, ready, missing
  (_geo_required_units, _geo_coverage_status, _set_geo_coverage_meta,
  _has_geo_recipes).
* Staging routing — which DB to read/write, how shared/run-local
  layers merge (canonical_staging_db, _staging_db_candidates,
  _geo_merge_to_shared_store, _compute_geo_seed_frontier).

Both touch context.geo_shared and the geo_shared_coverage meta, so
splitting them across modules would introduce import cycles for
marginal clarity gain.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from resolvekit.builder.geo_shared import (
    COVERAGE_UNITS,
    UNIT_ENTITY_TYPE_MAP,
    UNIT_STATE_READY,
    GeoCoverageMeta,
    required_units_for_entity_types,
)
from resolvekit.builder.sqlite import rebuild_fts, staging_db_path

if TYPE_CHECKING:
    from resolvekit.builder.pipeline.core import BuildContext

from resolvekit.builder.pipeline.types import BuildExecutionError


def _has_geo_recipes(context: BuildContext) -> bool:
    """Check if any recipe in the plan is for the geo domain."""
    return any(recipe.domain == "geo" for recipe in context.plan.recipes)


def _geo_coverage_status(context: BuildContext) -> tuple[set[str], set[str], set[str]]:
    required = _geo_required_units(context)
    all_units = context.geo_shared.coverage_units()
    ready = {name for name, u in all_units.items() if u.state == UNIT_STATE_READY}
    missing = required - ready if required else set()
    return required, ready, missing


def _set_geo_coverage_meta(
    context: BuildContext,
    status: tuple[set[str], set[str], set[str]] | None = None,
) -> GeoCoverageMeta:
    required, ready, missing = status or _geo_coverage_status(context)
    meta = GeoCoverageMeta(
        required_units=sorted(required),
        ready_units=sorted(ready),
        missing_units=sorted(missing),
    )
    context.state.set_meta(
        "geo_shared_coverage",
        meta.model_dump(mode="json", exclude_none=True),
    )
    return meta


def _geo_required_units(context: BuildContext) -> set[str]:
    """Determine which geo coverage units are required by the current plan."""
    entity_types: set[str] = set()
    for recipe in context.plan.recipes:
        if recipe.domain != "geo":
            continue
        if recipe.entity_filter.include_entity_types:
            entity_types.update(recipe.entity_filter.include_entity_types)
        else:
            # Open filter — all coverage units are required.
            return set(COVERAGE_UNITS)
    return required_units_for_entity_types(entity_types)


def _compute_geo_seed_frontier(
    context: BuildContext,
    missing_units: set[str],
    *,
    ready_units: set[str],
) -> dict[str, list[str]] | None:
    """Build a seed_frontier dict from cached entity IDs.

    Returns a mapping from coverage unit name to entity ID lists for all
    ready units that are transitive parents of the missing units.
    """
    if not ready_units:
        return None

    hierarchy_units = ["countries"] + [f"admin{i}" for i in range(1, 7)]
    frontier: dict[str, list[str]] = {}

    for unit_name in hierarchy_units:
        if unit_name in ready_units and unit_name not in missing_units:
            entity_type = UNIT_ENTITY_TYPE_MAP[unit_name]
            ids = context.geo_shared.query_entity_ids_by_type(entity_type)
            if ids:
                frontier[unit_name] = ids
        else:
            break  # Stop at first gap — can't skip non-consecutive levels.

    return frontier if frontier else None


def _geo_merge_to_shared_store(context: BuildContext) -> None:
    """Merge run-local geo staging into the shared geo store.

    Uses the interruption-safe temp-DB merge flow from the design:
    for each coverage unit being refreshed, data is validated in a
    temporary DB, then atomically merged into the shared store.
    """
    run_staging_db = staging_db_path(context.staging_dir, "geo")
    if not run_staging_db.exists():
        return

    geo_coverage_meta = GeoCoverageMeta.model_validate(
        context.state.get_meta("geo_shared_coverage", default={})
    )
    missing_units = set(geo_coverage_meta.missing_units)
    if not missing_units:
        # Nothing was refreshed — no merge needed.
        return

    shared = context.geo_shared
    merge_report: dict[str, dict[str, Any]] = {}

    with shared.refresh_lock():
        for unit_name in sorted(missing_units):
            if not shared.can_claim_refresh(unit_name, context.run_id):
                continue

            shared.mark_refreshing(unit_name, context.run_id, locked=True)
            entity_count = shared.merge_temp_db(run_staging_db, unit_name)
            shared.mark_ready(
                unit_name,
                context.run_id,
                entity_count=entity_count,
                locked=True,
            )
            merge_report[unit_name] = {
                "entity_count": entity_count,
                "state": "ready",
            }

        # Rebuild FTS on the shared store after all merges.
        if merge_report:
            rebuild_fts(shared.db_path)

    context.state.set_meta("geo_shared_merge", merge_report)
    _set_geo_coverage_meta(context)


@dataclass(frozen=True, slots=True)
class _StagingDbCandidates:
    """Candidate staging DB paths for a domain, before policy applies.

    ``run_db`` is always populated but may not exist on disk. ``shared_db``
    is populated only for the geo domain.
    """

    run_db: Path
    shared_db: Path | None


def _staging_db_candidates(context: BuildContext, domain: str) -> _StagingDbCandidates:
    """Resolve the candidate DB paths for one domain.

    Coverage state and policy decisions live in the wrappers below.
    """
    run_db = staging_db_path(context.staging_dir, domain)
    if domain != "geo":
        return _StagingDbCandidates(run_db=run_db, shared_db=None)
    return _StagingDbCandidates(run_db=run_db, shared_db=context.geo_shared.db_path)


def canonical_staging_db(
    context: BuildContext,
    domain: str,
    *,
    phase: Literal["canonicalize", "reconcile", "validate", "enrich", "package"],
) -> Path | None:
    """Resolve the one staging DB a stage reads/writes for a domain.

    Geo returns the shared store once the plan's required coverage is ready
    there; non-geo returns the run-local staging DB if it exists. All phases
    resolve identically so reconcile/validate/enrich/package never disagree.

    Returns ``None`` for a domain with no staging data. Raises
    ``BuildExecutionError`` for geo when required coverage is incomplete but a
    run-local slice exists — refusing to build a datapack from a partial geo
    set (preserves ``_resolve_staging_db``'s gate for every phase).

    ``phase`` is accepted for call-site self-documentation and forward
    compatibility; all phases share the same resolution logic today.
    """
    _ = phase  # reserved for forward-compat; resolution is uniform across phases
    cand = _staging_db_candidates(context, domain)
    if cand.shared_db is None:
        # Non-geo: run-local if it exists, else None.
        return cand.run_db if cand.run_db.exists() else None
    required, _, missing = _geo_coverage_status(context)
    if required and not missing and cand.shared_db.exists():
        return cand.shared_db
    if not required:
        return None
    if cand.run_db.exists():
        raise BuildExecutionError(
            "Shared geo coverage is incomplete after refresh: "
            f"missing_units={sorted(missing)}"
        )
    return None
