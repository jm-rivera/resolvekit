"""Public API for module-oriented base-data build orchestration."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from typing import Any, cast

import pydantic

import resolvekit.builder.pipeline as pipeline_module
from resolvekit.builder._outcomes import _failed_inspection_outcome, _failed_outcome
from resolvekit.builder.geo_shared import (
    COVERAGE_UNITS,
    UNIT_ENTITY_TYPE_MAP,
    GeoSharedStore,
    required_units_for_entity_types,
)
from resolvekit.builder.inspection import (
    DomainInspection,
    EntityClassificationSummary,
    InspectionOutcome,
)
from resolvekit.builder.models import (
    BuildOptions,
    BuildOutcome,
    BuildPlan,
    ReleaseRecord,
)
from resolvekit.builder.pipeline import BuildContext, execute_build
from resolvekit.builder.registry import list_releases as _list_releases
from resolvekit.builder.sources.protocol import (
    InspectableSourceAdapter,
    SourceAdapter,
    adapter_supports_inspection,
)
from resolvekit.builder.utils import ensure_dir, json_write, new_run_id, utc_now_iso

RESUME_MUTABLE_OPTION_FIELDS = frozenset(
    {
        "max_workers",
        "max_retries",
        "retry_base_delay_sec",
        "retry_max_delay_sec",
    }
)


def build(
    plan: BuildPlan,
    *,
    adapter_builder: Callable[[BuildPlan], dict[str, SourceAdapter]] | None = None,
) -> BuildOutcome:
    """Run a full build for the provided plan.

    Caller errors (BuildPlan validation, missing run dir) raise;
    content-level failures collect into outcome.errors.

    adapter_builder: optional factory overriding the default registry (used for testing/injection).
    """
    run_id = plan.run_id or new_run_id()
    started_at = utc_now_iso()
    try:
        context = BuildContext(
            plan=plan,
            run_id=run_id,
            started_at=started_at,
            adapter_builder=adapter_builder or pipeline_module.build_adapter_registry,
        )
    except Exception as exc:
        return _failed_outcome(run_id=run_id, started_at=started_at, exc=exc)
    return execute_build(context)


def _inspect_geo_from_cache(
    plan: BuildPlan,
    requested_types: list[str],
    include_relation_targets: bool,
) -> DomainInspection | None:
    """Return a synthetic geo inspection from the shared cache, or None."""
    shared_root = plan.options.shared_geo_root
    if not shared_root.exists():
        return None
    geo_shared = GeoSharedStore(shared_root)
    if not geo_shared.manifest_path.exists():
        return None

    # Only the manifest read is treated as a cache miss; bugs below propagate.
    try:
        manifest = geo_shared.read_manifest()
    except (OSError, json.JSONDecodeError, pydantic.ValidationError):
        return None

    cached_instance = manifest.source_instance
    if (
        cached_instance is not None
        and cached_instance != plan.options.datacommons_instance
    ):
        return None

    entity_types = {t.strip() for t in requested_types if t.strip()}
    if entity_types:
        required = required_units_for_entity_types(entity_types)
    else:
        # Open filter (no entity types specified) means all geo types.
        required = set(COVERAGE_UNITS)
    if not required or geo_shared.missing_units(required):
        return None

    # Only count directly requested units, not transitive dependencies.
    if entity_types:
        direct_units = GeoSharedStore.entity_types_to_units(entity_types)
        if include_relation_targets:
            direct_units = required
    else:
        direct_units = required

    units = geo_shared.coverage_units()
    total = sum(units[name].entity_count for name in direct_units if name in units)
    canonical_type_counts = {
        UNIT_ENTITY_TYPE_MAP[name]: units[name].entity_count
        for name in direct_units
        if name in units and units[name].entity_count > 0
    }

    return DomainInspection(
        domain="geo",
        requested_entity_types=sorted(entity_types),
        include_relation_targets=include_relation_targets,
        discovered_entity_count=total,
        classification=EntityClassificationSummary(
            canonical_type_counts=canonical_type_counts,
        ),
        sample_entities=[],
        warnings=["Inspection served from shared geo cache; no API calls made."],
    )


def inspect(
    plan: BuildPlan,
    *,
    adapter_builder: Callable[[BuildPlan], dict[str, SourceAdapter]] | None = None,
) -> InspectionOutcome:
    """Inspect source coverage for the provided plan.

    Caller errors (BuildPlan validation, missing run dir) raise;
    content-level failures collect into outcome.errors.
    """
    run_id = plan.run_id or new_run_id()
    started_at = utc_now_iso()
    try:
        builder = adapter_builder or pipeline_module.build_inspection_adapter_registry
        adapters = builder(plan)
    except Exception as exc:
        return _failed_inspection_outcome(
            run_id=run_id,
            started_at=started_at,
            exc=exc,
        )

    domains: list[Any] = []
    errors: list[str] = []
    requested_types = _requested_entity_types_by_domain(plan)
    relation_targets = _relation_targets_by_domain(plan)

    for domain in sorted({recipe.domain for recipe in plan.recipes if recipe.domain}):
        if domain == "geo" and adapter_builder is None:
            cached = _inspect_geo_from_cache(
                plan,
                requested_types.get(domain, []),
                relation_targets.get(domain, True),
            )
            if cached is not None:
                domains.append(cached)
                continue

        adapter = adapters.get(domain)
        if adapter is None:
            errors.append(f"LookupError: no adapter registered for domain '{domain}'.")
            continue
        if not adapter_supports_inspection(adapter):
            errors.append(
                f"TypeError: adapter for domain '{domain}' does not support inspection."
            )
            continue
        inspectable = cast(InspectableSourceAdapter, adapter)

        try:
            domains.append(
                inspectable.inspect_domain(
                    domain,
                    include_entity_types=requested_types.get(domain, []),
                    include_relation_targets=relation_targets.get(domain, True),
                )
            )
        except Exception as exc:
            errors.append(f"{domain}: {type(exc).__name__}: {exc}")

    report_path = plan.options.reports_root / "inspection" / f"{run_id}.json"
    ensure_dir(report_path.parent)
    outcome = InspectionOutcome(
        run_id=run_id,
        domains=domains,
        errors=errors,
        started_at=started_at,
    )
    json_write(report_path, outcome.model_dump(mode="json"))
    return outcome.model_copy(
        update={"reports": {"inspection_report": str(report_path)}}
    )


def resume(
    run_id: str,
    options: BuildOptions | None = None,
    *,
    adapter_builder: Callable[[BuildPlan], dict[str, SourceAdapter]] | None = None,
) -> BuildOutcome:
    """Resume a previously failed or interrupted run.

    Caller errors (BuildPlan validation, missing run dir) raise;
    content-level failures collect into outcome.errors.

    adapter_builder: optional factory overriding the default registry (used for testing/injection).
    """
    lookup_options = options or BuildOptions()
    run_dir = lookup_options.runs_root / run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    plan_path = run_dir / "plan.json"
    if not plan_path.exists():
        raise FileNotFoundError(f"Run plan not found: {plan_path}")

    plan = BuildPlan.model_validate(json.loads(plan_path.read_text(encoding="utf-8")))
    merged_options = _merge_resume_options(plan.options, options)
    if merged_options != plan.options:
        plan = plan.model_copy(update={"options": merged_options})

    started_at = utc_now_iso()
    try:
        context = BuildContext(
            plan=plan,
            run_id=run_id,
            started_at=started_at,
            resume_mode=True,
            adapter_builder=adapter_builder or pipeline_module.build_adapter_registry,
        )
    except Exception as exc:
        return _failed_outcome(run_id=run_id, started_at=started_at, exc=exc)
    return execute_build(context)


def list_releases(
    module_id: str | None = None,
    options: BuildOptions | None = None,
) -> list[ReleaseRecord]:
    """List successful releases from registry."""
    return _list_releases(options=options or BuildOptions(), module_id=module_id)


def _requested_entity_types_by_domain(plan: BuildPlan) -> dict[str, list[str]]:
    requested: defaultdict[str, list[str]] = defaultdict(list)
    for recipe in plan.recipes:
        for entity_type in recipe.entity_filter.include_entity_types:
            normalized = entity_type.strip()
            if normalized and normalized not in requested[recipe.domain]:
                requested[recipe.domain].append(normalized)
    return dict(requested)


def _relation_targets_by_domain(plan: BuildPlan) -> dict[str, bool]:
    requested: dict[str, bool] = {}
    for recipe in plan.recipes:
        requested[recipe.domain] = requested.get(recipe.domain, False) or bool(
            recipe.entity_filter.include_relation_targets
        )
    return requested


def _merge_resume_options(
    original: BuildOptions,
    override: BuildOptions | None,
) -> BuildOptions:
    """Allow retry-tuning overrides only, preserving run-shaping options."""
    if override is None:
        return original

    original_values = original.model_dump(mode="python")
    override_values = override.model_dump(mode="python")
    explicit_override_fields = set(override.model_fields_set)

    changed_fields = {
        name
        for name in explicit_override_fields
        if override_values[name] != original_values[name]
    }
    disallowed = sorted(changed_fields - RESUME_MUTABLE_OPTION_FIELDS)
    if disallowed:
        fields = ", ".join(disallowed)
        raise ValueError(
            f"resume() cannot change run-shaping options: {fields}. "
            "Only retry/concurrency fields may be overridden."
        )

    updates = {name: override_values[name] for name in changed_fields}
    if not updates:
        return original
    return original.model_copy(update=updates)
