"""High-level preset build plans."""

from __future__ import annotations

from resolvekit.builder.models import BuildOptions, BuildPlan
from resolvekit.builder.module_catalog import (
    build_plan_from_entries,
    geo_base_entries,
    geo_entries,
    org_entries,
)


def geo(options: BuildOptions | None = None) -> BuildPlan:
    """Return the expanded curated geo module build plan."""
    return build_plan_from_entries(geo_entries(), options=options)


def geo_base(options: BuildOptions | None = None) -> BuildPlan:
    """Return the compact geo hierarchy build plan."""
    return build_plan_from_entries(geo_base_entries(), options=options)


def org(options: BuildOptions | None = None) -> BuildPlan:
    """Return the explicit org module build plan."""
    return build_plan_from_entries(org_entries(), options=options)


def all_modules(options: BuildOptions | None = None) -> BuildPlan:
    """Return the inspection-first all-modules plan."""
    base_plan = geo(options=options)
    org_plan = org(options=base_plan.options)
    return base_plan.model_copy(
        update={
            "recipes": [
                *base_plan.recipes,
                *org_plan.recipes,
            ]
        }
    )
