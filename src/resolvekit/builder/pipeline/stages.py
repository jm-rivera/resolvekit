"""Pipeline stage implementations.

Stage functions live here and are wired into ``core.STAGE_FUNCTIONS``.
See ``STAGES`` in ``types.py`` for the authoritative stage-addition checklist.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

from resolvekit.builder.datapack_layout import iter_datapack_dirs
from resolvekit.builder.pipeline.changelog import stage_changelog
from resolvekit.builder.pipeline.chunk import (
    extract_chunk,
    materialize_chunk,
    normalize_chunk,
    retry_parallel_stage,
    retry_sequential_stage,
)
from resolvekit.builder.pipeline.enrich import stage_enrich
from resolvekit.builder.pipeline.packaging import package_domain
from resolvekit.builder.sqlite import (
    compute_selected_ids,
    ensure_sqlite_schema,
    rebuild_fts,
    staging_db_path,
    validate_domain_db,
)
from resolvekit.builder.utils import ensure_dir, json_write, utc_now_iso
from resolvekit.core.datapack import DataPackMetadata
from resolvekit.core.module_registry import module_id_to_suffix

if TYPE_CHECKING:
    from resolvekit.builder.models import ModuleRecipe
    from resolvekit.builder.pipeline.core import BuildContext

from resolvekit.builder.pipeline.discover import (
    _discover_domain,
    _persist_discover_progress,
)
from resolvekit.builder.pipeline.geo_staging import (
    _geo_merge_to_shared_store,
    _has_geo_recipes,
    canonical_staging_db,
)
from resolvekit.builder.pipeline.reconcile import _reconcile_domain_targets
from resolvekit.builder.pipeline.types import (
    STAGES,
    BuildExecutionError,
    ReleaseCandidate,
    serialize_release_candidate,
)
from resolvekit.builder.sources.datacommons.canonicalize import (
    canonicalize_relation_targets,
)
from resolvekit.builder.sources.discovery_events import DiscoverProgress

logger = logging.getLogger(__name__)

__all__ = [
    "stage_canonicalize",
    "stage_changelog",
    "stage_discover",
    "stage_enrich",
    "stage_extract",
    "stage_materialize",
    "stage_normalize",
    "stage_package",
    "stage_prepare",
    "stage_reconcile",
    "stage_validate",
]


def _datapack_output_path(
    *,
    root: Path,
    module_id: str,
    domain: str,
) -> Path:
    """Resolve the directory where a module's packaged datapack is written.

    Uses the v1 flat layout: ``<root>/<domain>/<subpath>/`` where
    ``subpath = module_id.split('.', 1)[1].replace('.', '_')``.
    No version subdir — on-disk metadata carries the version.
    """
    suffix = module_id_to_suffix(module_id)
    if suffix is None:
        raise BuildExecutionError(
            f"Cannot derive subpath for module_id={module_id!r}: no '.'"
        )
    return root / domain / suffix


# Version assigned to a module that has no pack on disk yet. A plain build
# never bumps; the release path (scripts/release/release_data.py) stamps the
# published version (CalVer). This is just a stable placeholder for first builds.
_INITIAL_VERSION = "0.0.0"


def _resolve_inplace_versions(context: BuildContext) -> dict[str, str]:
    """Preserve each module's existing on-disk version (in-place rebuild).

    A plain build does not bump or enforce immutability — it rebuilds whatever
    is on disk and keeps its version. A module with no pack yet starts at
    ``_INITIAL_VERSION``. The release path owns the published version.
    """
    versions: dict[str, str] = {}
    for recipe in context.plan.recipes:
        output_path = _datapack_output_path(
            root=context.options.datapacks_root,
            module_id=recipe.module_id,
            domain=recipe.domain,
        )
        versions[recipe.module_id] = _ondisk_version(output_path) or _INITIAL_VERSION
    return versions


def _ondisk_version(output_path: Path) -> str | None:
    """Parse the version from an existing pack's ``metadata.json``, if present."""
    meta_path = output_path / "metadata.json"
    if not meta_path.exists():
        return None
    try:
        datapack_id = DataPackMetadata.from_file(meta_path).datapack_id
    except Exception:
        return None
    _head, sep, version = datapack_id.rpartition("-v")
    if not sep or not version:
        return None
    return version


def _snapshot_previous_datapack(
    context: BuildContext, module_id: str, output_path: Path
) -> Path | None:
    """Copy the existing packed SQLite aside before this build overwrites it.

    Returns the run-scoped snapshot path (the baseline for the drift gate and
    changelog diff), or ``None`` when no prior pack exists at *output_path*
    (a first build, with nothing to compare against).
    """
    existing = output_path / "entities.sqlite"
    # A remote module ships a 0-byte placeholder entities.sqlite until its real
    # pack is built and published as a release asset. That placeholder is not a
    # baseline to diff against, so the first real build treats it as "no prior
    # pack" (same as a brand-new module) rather than crashing the drift gate and
    # changelog diff on a table-less database.
    if not existing.exists() or existing.stat().st_size == 0:
        return None
    # Use the full module_id (domain-inclusive) to avoid collisions between
    # modules sharing a suffix across domains (e.g. "geo.countries" and
    # "org.countries" both have suffix "countries").
    safe_key = module_id.replace(".", "_")
    snapshot = context.run_dir / "previous_packs" / safe_key / "entities.sqlite"
    if snapshot.exists():
        # Idempotent: if already captured this run_id, reuse it so a retry
        # or resume doesn't re-snapshot a pack we already overwrote.
        return snapshot
    ensure_dir(snapshot.parent)
    shutil.copy2(existing, snapshot)
    return snapshot


def stage_prepare(context: BuildContext) -> None:
    """Create run folders and save initial run metadata."""
    for directory in (
        context.run_dir,
        context.raw_dir,
        context.normalized_dir,
        context.staging_dir,
        context.reports_dir,
        context.options.datapacks_root,
        context.options.registry_path.parent,
    ):
        ensure_dir(directory)

    # Initialize shared geo store when geo recipes are present.
    if _has_geo_recipes(context):
        context.geo_shared.ensure_paths()
        context.geo_shared.set_source_instance(context.options.datacommons_instance)

    context.state.initialize_stages(list(STAGES))

    if not context.plan_path.exists():
        json_write(context.plan_path, context.plan.model_dump(mode="json"))

    context.state.set_meta("version_candidates", _resolve_inplace_versions(context))
    context.state.set_meta("prepared_at", utc_now_iso())


def stage_discover(context: BuildContext) -> None:
    """Discover domain entity IDs and persist chunk inventory.

    For geo domains, checks shared geo coverage first and only discovers
    entity types whose coverage units are not already ``ready``.
    """
    domains = sorted({recipe.domain for recipe in context.plan.recipes})
    if not domains:
        raise BuildExecutionError("No domains requested by recipes.")

    discover_progress = DiscoverProgress()
    context.state.set_meta(
        "discover_progress",
        discover_progress.model_dump(mode="json", exclude_none=True),
    )
    context.state.set_meta("discovered_chunks", {})

    for domain in domains:
        _discover_domain(
            context=context,
            domain=domain,
            progress=discover_progress,
        )

    _persist_discover_progress(context, discover_progress, force=True)


def stage_extract(context: BuildContext) -> None:
    """Fetch raw payloads for pending or retryable chunks."""
    retry_parallel_stage(
        context=context,
        stage="extract",
        load_chunks=lambda max_retries: context.state.chunks_for_stage(
            "extract",
            max_retries,
        ),
        process=extract_chunk,
    )


def stage_normalize(context: BuildContext) -> None:
    """Normalize raw chunk payloads to canonical row payloads."""
    retry_parallel_stage(
        context=context,
        stage="normalize",
        load_chunks=lambda max_retries: context.state.chunks_for_stage(
            "normalize",
            max_retries,
        ),
        process=normalize_chunk,
    )


def stage_materialize(context: BuildContext) -> None:
    """Insert normalized rows into per-domain staging SQLite files.

    For geo domains, materialized data is also merged into the shared geo
    store using an interruption-safe temporary DB workflow.
    """
    for domain in context.state.domains():
        ensure_sqlite_schema(staging_db_path(context.staging_dir, domain))

    retry_sequential_stage(
        context=context,
        stage="materialize",
        load_chunks=lambda max_retries: context.state.chunks_for_stage(
            "materialize",
            max_retries,
        ),
        process=materialize_chunk,
    )

    for domain in context.state.domains():
        if domain == "geo":
            continue  # shared store FTS is rebuilt after merge
        db_path = staging_db_path(context.staging_dir, domain)
        if db_path.exists():
            rebuild_fts(db_path)

    # Merge geo data into shared store with interruption safety.
    if "geo" in context.state.domains():
        _geo_merge_to_shared_store(context)


def stage_canonicalize(context: BuildContext) -> None:
    """Rewrite DC relation targets to canonical entity_ids before reconcile.

    For each domain staging DB, builds the dcid→entity_id map once, bulk-
    rewrites targets that resolve via the map, and deletes rows whose target
    carries an unmodeled prefix with a per-prefix dropped-count metric.

    Must run after materialize (entities + dcid codes must exist) and before
    reconcile (which expects canonical target_ids for cross-pack hydration).
    """
    reports: dict[str, dict[str, object]] = {}
    for domain in context.state.domains():
        db_path = canonical_staging_db(context, domain, phase="canonicalize")
        if not db_path or not db_path.exists():
            # No staging data for this domain yet — nothing to canonicalize.
            reports[domain] = {"skipped": "no staging DB"}
            continue

        if db_path == context.geo_shared.db_path:
            # Geo uses the shared store; hold the refresh lock while mutating
            # so concurrent readers see a consistent snapshot (mirrors
            # stage_reconcile's lock guard).
            with context.geo_shared.refresh_lock():
                report = canonicalize_relation_targets(db_path=db_path)
        else:
            report = canonicalize_relation_targets(db_path=db_path)

        logger.info(
            "canonicalize[%s]: rewrote %d, kept %d, dropped %r",
            domain,
            report.rewritten,
            report.kept,
            report.dropped_by_prefix,
        )
        reports[domain] = {
            "rewritten": report.rewritten,
            "kept": report.kept,
            "dropped_by_prefix": report.dropped_by_prefix,
        }

    context.state.set_meta("staging_canonicalize", reports)


def stage_reconcile(context: BuildContext) -> None:
    """Hydrate missing relation targets in bounded rounds before validation."""
    if not context.options.reconcile_relation_closure:
        context.state.set_meta("staging_reconcile", {"enabled": False})
        return

    relation_types = [
        value
        for value in dict.fromkeys(context.options.reconcile_relation_types)
        if value.strip()
    ]
    if not relation_types:
        context.state.set_meta(
            "staging_reconcile",
            {"enabled": True, "skipped": "no relation types configured"},
        )
        return

    reports: dict[str, dict[str, Any]] = {}
    for domain in context.state.domains():
        adapter = context.adapters.get(domain)
        if adapter is None:
            raise BuildExecutionError(
                f"No source adapter registered for domain '{domain}'."
            )

        db_path = canonical_staging_db(context, domain, phase="reconcile")
        if not db_path or not db_path.exists():
            raise BuildExecutionError(f"Missing staging DB for domain '{domain}'.")

        if db_path == context.geo_shared.db_path:
            # reconcile and package must read the same DB; lock is cheap insurance
            # under single-build-at-a-time.
            with context.geo_shared.refresh_lock():
                report = _reconcile_domain_targets(
                    context=context,
                    domain=domain,
                    relation_types=relation_types,
                    db_path=db_path,
                )
        else:
            report = _reconcile_domain_targets(
                context=context,
                domain=domain,
                relation_types=relation_types,
                db_path=db_path,
            )
        reports[domain] = report

        if int(report["hydrated_entities"]) > 0:
            rebuild_fts(db_path)

    context.state.set_meta("staging_reconcile", reports)


def stage_validate(context: BuildContext) -> None:
    """Validate staging domain DBs and persist metrics/check outputs."""
    domain_metrics: dict[str, dict[str, float | int]] = {}
    structural_issues: dict[str, list[str]] = {}

    for domain in context.state.domains():
        db_path = canonical_staging_db(context, domain, phase="validate")
        if not db_path or not db_path.exists():
            raise BuildExecutionError(f"Missing staging DB for domain '{domain}'.")

        metrics, issues = validate_domain_db(
            db_path,
            allow_external_relation_targets=True,
        )
        domain_metrics[domain] = metrics
        structural_issues[domain] = issues

    context.state.set_meta("staging_metrics", domain_metrics)
    context.state.set_meta("staging_structural_issues", structural_issues)

    blocking = {
        domain: issues for domain, issues in structural_issues.items() if issues
    }
    if blocking:
        raise BuildExecutionError(
            f"Structural validation failed: {json.dumps(blocking, indent=2)}"
        )


def stage_package(context: BuildContext) -> None:
    """Export recipe datapacks from staging DBs with QA checks.

    For geo recipes, the staging source is resolved as follows:
    - The shared geo store is the canonical source once required coverage is ready.
    - Non-geo domains continue to package from the run-local staging DB.
    """
    versions = context.state.get_meta("version_candidates", default={})
    if not versions:
        raise BuildExecutionError("Missing version candidates. Did prepare stage run?")

    # Resolve the selected entity ids for every packageable recipe
    # before packaging any, so the cross-pack ``allowed_targets`` set is known
    # up front.
    packageable: list[tuple[ModuleRecipe, str, Path, set[str]]] = []
    skipped_modules: list[dict[str, str]] = []
    for recipe in context.plan.recipes:
        recipe_id = recipe.module_id
        version = str(versions[recipe_id])
        staging_db = canonical_staging_db(context, recipe.domain, phase="package")
        if staging_db is None or not staging_db.exists():
            skipped_modules.append(
                {
                    "module_id": recipe_id,
                    "domain": recipe.domain,
                    "reason": "no discovered entities",
                }
            )
            continue

        selected_ids = compute_selected_ids(staging_db, recipe.entity_filter)
        if not selected_ids:
            skipped_modules.append(
                {
                    "module_id": recipe_id,
                    "domain": recipe.domain,
                    "reason": "no selected entities after filtering",
                }
            )
            continue

        packageable.append((recipe, version, staging_db, selected_ids))

    # Relation edges may only point at entities that some pack actually ships.
    # The allowed-target set is every selected id in this build plus every id in
    # the packs already on disk for modules this run does not rebuild (other
    # domains). This keeps cross-pack (admin2 -> admin1) and cross-domain
    # (org agency -> country/*) edges while dropping edges to never-shipped
    # entities (geo containers of unshipped place types, OECD channel parents).
    built_module_ids = {recipe.module_id for recipe, _, _, _ in packageable}
    allowed_targets: set[str] = set()
    for _, _, _, selected_ids in packageable:
        allowed_targets |= selected_ids
    allowed_targets |= _external_shipped_ids(
        datapacks_root=context.options.datapacks_root,
        exclude_module_ids=built_module_ids,
    )

    # Package each pack, dropping relation edges to unshipped targets.
    candidates: list[ReleaseCandidate] = []
    for recipe, version, staging_db, selected_ids in packageable:
        output_path = _datapack_output_path(
            root=context.options.datapacks_root,
            module_id=recipe.module_id,
            domain=recipe.domain,
        )
        ensure_dir(output_path)

        # Snapshot the pack we are about to overwrite; it is the drift/changelog
        # baseline. Must happen before package_domain rewrites entities.sqlite.
        previous_db = _snapshot_previous_datapack(
            context, recipe.module_id, output_path
        )
        policy = recipe.quality_policy or context.plan.quality_policy

        # One recipe packages exactly one domain; domain_artifacts stays a
        # dict (keyed by domain) because changelog/promote iterate it.
        artifact = package_domain(
            context=context,
            recipe=recipe,
            domain=recipe.domain,
            source_db=staging_db,
            version=version,
            output_path=output_path,
            previous_db=previous_db,
            quality_policy=policy,
            selected_ids=selected_ids,
            allowed_targets=allowed_targets,
        )

        candidates.append(
            ReleaseCandidate(
                recipe=recipe,
                version=version,
                output_path=output_path,
                domain_artifacts={recipe.domain: artifact},
                previous_db_path=previous_db,
            )
        )

    context.release_candidates = candidates
    context.state.set_meta(
        "release_candidates",
        [serialize_release_candidate(c) for c in candidates],
    )
    context.state.set_meta("skipped_modules", skipped_modules)


def _external_shipped_ids(
    *, datapacks_root: Path, exclude_module_ids: set[str]
) -> set[str]:
    """Union the entity ids of every on-disk pack this run does not rebuild.

    Lets ``stage_package`` keep relation targets that live in other domains'
    packs (a fresh build only repackages its own modules). Packs whose module
    is in *exclude_module_ids* are skipped — this run resupplies their ids from
    fresh ``selected_ids``. Packs without a local ``entities.sqlite`` (remote
    tier) contribute nothing, so edges into them are not preserved.
    """
    if not datapacks_root.exists():
        return set()
    ids: set[str] = set()
    for pack_dir in iter_datapack_dirs(datapacks_root=datapacks_root):
        meta_path = pack_dir / "metadata.json"
        try:
            module_id = DataPackMetadata.from_file(meta_path).module_id
        except Exception:
            module_id = None
        if module_id in exclude_module_ids:
            continue
        db_path = pack_dir / "entities.sqlite"
        if not db_path.exists():
            continue
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
                ids.update(
                    row[0] for row in conn.execute("SELECT entity_id FROM entities")
                )
        except sqlite3.OperationalError:
            # File exists but has no entities table (e.g. 0-byte placeholder
            # written by a prior interrupted build). Skip it — this pack has
            # no shipped ids to preserve.
            pass
    return ids
