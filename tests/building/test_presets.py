"""Tests for high-level builder preset plans."""

from __future__ import annotations

from pathlib import Path

from resolvekit.builder.models import BuildOptions
from resolvekit.builder.module_catalog import (
    GEO_MAX_ADMIN_DEPTH,
)
from resolvekit.builder.presets import all_modules, geo, geo_base, org


def test_geo_preset_returns_expected_module_split(tmp_path: Path) -> None:
    options = BuildOptions(
        build_root=tmp_path / "build",
        datapacks_root=tmp_path / "datapacks",
        reports_root=tmp_path / "reports",
    )

    plan = geo(options)

    assert [recipe.module_id for recipe in plan.recipes] == [
        "geo.countries",
        *(f"geo.admin{level}" for level in range(1, GEO_MAX_ADMIN_DEPTH + 1)),
        "geo.cities",
        "geo.regions",
        "geo.continental_unions",
        "geo.continents",
    ]
    assert plan.options == options
    assert plan.recipes[0].entity_filter.include_entity_types == ["geo.country"]
    assert all(
        recipe.entity_filter.include_relation_targets is False
        for recipe in plan.recipes
    )
    assert all(recipe.module_dependencies == [] for recipe in plan.recipes)


def test_geo_base_preset_returns_hierarchy_only(tmp_path: Path) -> None:
    options = BuildOptions(
        build_root=tmp_path / "build",
        datapacks_root=tmp_path / "datapacks",
        reports_root=tmp_path / "reports",
    )

    plan = geo_base(options)

    assert [recipe.module_id for recipe in plan.recipes] == [
        "geo.countries",
        *(f"geo.admin{level}" for level in range(1, GEO_MAX_ADMIN_DEPTH + 1)),
        "geo.cities",
    ]
    assert plan.options == options


def test_all_modules_preset_appends_explicit_org_modules(tmp_path: Path) -> None:
    options = BuildOptions(
        build_root=tmp_path / "build",
        datapacks_root=tmp_path / "datapacks",
        reports_root=tmp_path / "reports",
    )

    plan = all_modules(options)

    assert [recipe.module_id for recipe in plan.recipes] == [
        "geo.countries",
        *(f"geo.admin{level}" for level in range(1, GEO_MAX_ADMIN_DEPTH + 1)),
        "geo.cities",
        "geo.regions",
        "geo.continental_unions",
        "geo.continents",
        "org.providers",
        "org.lenders",
        "org.political_parties",
        "org.companies",
        "org.governments",
        "org.igos",
        "org.data_sources",
    ]


def test_org_preset_returns_explicit_org_module_split(tmp_path: Path) -> None:
    options = BuildOptions(
        build_root=tmp_path / "build",
        datapacks_root=tmp_path / "datapacks",
        reports_root=tmp_path / "reports",
    )

    plan = org(options)

    assert [recipe.module_id for recipe in plan.recipes] == [
        "org.providers",
        "org.lenders",
        "org.political_parties",
        "org.companies",
        "org.governments",
        "org.igos",
        "org.data_sources",
    ]
    assert plan.options == options
    assert plan.recipes[0].entity_filter.include_entity_types == [
        "org.development_finance_provider"
    ]
    assert plan.recipes[0].entity_filter.include_relation_targets is False
    assert all(recipe.module_dependencies == [] for recipe in plan.recipes)
    assert plan.recipes[3].entity_filter.include_entity_types == [
        "org.company",
        "org.corporation",
        "org.subsidiary",
    ]
