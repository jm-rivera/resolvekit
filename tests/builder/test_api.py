"""Tests for resolvekit.builder.api — error contract and cache inspection."""

from __future__ import annotations

from pathlib import Path

from resolvekit.builder.api import _inspect_geo_from_cache
from resolvekit.builder.geo_shared import GeoSharedStore
from resolvekit.builder.models import BuildOptions, BuildPlan, ModuleRecipe

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plan(tmp_path: Path) -> BuildPlan:
    """Construct a minimal BuildPlan pointing at tmp_path as the build root."""
    options = BuildOptions(build_root=tmp_path)
    return BuildPlan(
        recipes=[ModuleRecipe(module_id="geo.countries", domain="geo")],
        options=options,
    )


# ---------------------------------------------------------------------------
# _inspect_geo_from_cache — cache miss paths
# ---------------------------------------------------------------------------


def test_cache_miss_when_shared_root_absent(tmp_path: Path) -> None:
    """Returns None when shared_geo_root does not exist."""
    plan = _make_plan(tmp_path)
    result = _inspect_geo_from_cache(plan, [], True)
    assert result is None


def test_cache_miss_when_manifest_absent(tmp_path: Path) -> None:
    """Returns None when shared_geo_root exists but manifest.json is missing."""
    plan = _make_plan(tmp_path)
    shared_root = plan.options.shared_geo_root
    shared_root.mkdir(parents=True)

    result = _inspect_geo_from_cache(plan, [], True)
    assert result is None


def test_cache_miss_on_corrupt_manifest_json(tmp_path: Path) -> None:
    """Returns None (not an exception) when manifest.json contains invalid JSON."""
    plan = _make_plan(tmp_path)
    store = GeoSharedStore(plan.options.shared_geo_root)
    store.ensure_paths()
    store.manifest_path.write_text("{not valid json")

    result = _inspect_geo_from_cache(plan, [], True)
    assert result is None


def test_cache_miss_on_schema_invalid_manifest(tmp_path: Path) -> None:
    """Returns None when manifest.json fails pydantic validation."""
    plan = _make_plan(tmp_path)
    store = GeoSharedStore(plan.options.shared_geo_root)
    store.ensure_paths()
    store.manifest_path.write_text('{"schema_version": "not-an-int"}')

    result = _inspect_geo_from_cache(plan, [], True)
    assert result is None


# ---------------------------------------------------------------------------
# _inspect_geo_from_cache — normal cache miss (no ready units)
# ---------------------------------------------------------------------------


def test_cache_miss_when_no_units_ready(tmp_path: Path) -> None:
    """Returns None when the cache store exists but all units are invalid."""
    plan = _make_plan(tmp_path)
    store = GeoSharedStore(plan.options.shared_geo_root)
    store.ensure_paths()
    # Default manifest has all units in INVALID state.

    result = _inspect_geo_from_cache(plan, ["geo.country"], True)
    assert result is None
