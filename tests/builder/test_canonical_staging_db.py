"""Unit tests for canonical_staging_db — the single staging-DB resolver.

Verifies the four resolution cases described in the function docstring:
  - geo, coverage ready → shared store
  - geo, required + incomplete + run-local exists → raise BuildExecutionError
  - geo, not required → None
  - non-geo, run-local exists → run-local
  - non-geo, no run-local → None

Also asserts that the deleted legacy helpers are gone from the module.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from resolvekit.builder.geo_shared import (
    COVERAGE_UNITS,
    GeoSharedStore,
)
from resolvekit.builder.pipeline.geo_staging import canonical_staging_db
from resolvekit.builder.pipeline.types import BuildExecutionError
from resolvekit.builder.sqlite import ensure_sqlite_schema, staging_db_path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_recipe(domain: str) -> SimpleNamespace:
    """Minimal recipe stub that supplies domain and an open entity filter."""
    return SimpleNamespace(
        domain=domain,
        entity_filter=SimpleNamespace(include_entity_types=None),
    )


def _make_context(
    tmp_path: Path,
    *,
    domain_in_plan: str = "geo",
    staging_dir: Path | None = None,
) -> SimpleNamespace:
    """Build a minimal BuildContext stub backed by a real GeoSharedStore."""
    staging = staging_dir or (tmp_path / "staging")
    staging.mkdir(parents=True, exist_ok=True)

    shared = GeoSharedStore(tmp_path / "shared_geo")
    shared.ensure_paths()

    return SimpleNamespace(
        staging_dir=staging,
        geo_shared=shared,
        plan=SimpleNamespace(recipes=[_make_recipe(domain_in_plan)]),
    )


def _mark_all_units_ready(shared: GeoSharedStore, run_id: str = "test-run") -> None:
    """Forcibly mark every coverage unit ready so canonical_staging_db returns shared."""
    with shared.refresh_lock():
        for unit_name in COVERAGE_UNITS:
            shared.mark_refreshing(unit_name, run_id, locked=True)
            shared.mark_ready(unit_name, run_id, entity_count=1, locked=True)


# ---------------------------------------------------------------------------
# geo domain — coverage ready → shared store
# ---------------------------------------------------------------------------


def test_canonical_staging_db_returns_shared_for_ready_geo(tmp_path: Path) -> None:
    """Returns the shared store path when geo coverage is complete and shared DB exists."""
    ctx = _make_context(tmp_path, domain_in_plan="geo")
    _mark_all_units_ready(ctx.geo_shared)

    result = canonical_staging_db(ctx, "geo", phase="package")

    assert result == ctx.geo_shared.db_path
    assert result is not None


# ---------------------------------------------------------------------------
# geo domain — required + incomplete + run-local exists → raise
# ---------------------------------------------------------------------------


def test_canonical_staging_db_raises_for_incomplete_geo_with_run_local(
    tmp_path: Path,
) -> None:
    """Raises BuildExecutionError when geo is required, incomplete, and run-local exists."""
    ctx = _make_context(tmp_path, domain_in_plan="geo")
    # Leave coverage units in their default (not-ready) state — required but missing.
    # Create a run-local DB so the "run_db.exists()" branch triggers the raise.
    run_local = staging_db_path(ctx.staging_dir, "geo")
    ensure_sqlite_schema(run_local)

    with pytest.raises(BuildExecutionError, match="incomplete"):
        canonical_staging_db(ctx, "geo", phase="reconcile")


# ---------------------------------------------------------------------------
# geo domain — not required → None
# ---------------------------------------------------------------------------


def test_canonical_staging_db_returns_none_for_geo_not_required(tmp_path: Path) -> None:
    """Returns None when the plan has no geo recipe (geo not required)."""
    # Plan has only an org recipe — geo required_units is empty.
    ctx = _make_context(tmp_path, domain_in_plan="org")

    result = canonical_staging_db(ctx, "geo", phase="enrich")

    assert result is None


# ---------------------------------------------------------------------------
# non-geo domain — run-local exists → run-local
# ---------------------------------------------------------------------------


def test_canonical_staging_db_returns_run_local_for_non_geo(tmp_path: Path) -> None:
    """Returns the run-local path for a non-geo domain when it exists."""
    ctx = _make_context(tmp_path, domain_in_plan="org")
    run_local = staging_db_path(ctx.staging_dir, "org")
    ensure_sqlite_schema(run_local)

    result = canonical_staging_db(ctx, "org", phase="validate")

    assert result == run_local


# ---------------------------------------------------------------------------
# non-geo domain — no run-local → None
# ---------------------------------------------------------------------------


def test_canonical_staging_db_returns_none_for_non_geo_no_run_local(
    tmp_path: Path,
) -> None:
    """Returns None for a non-geo domain when no run-local DB exists."""
    ctx = _make_context(tmp_path, domain_in_plan="org")
    # Do NOT create a run-local DB.

    result = canonical_staging_db(ctx, "org", phase="enrich")

    assert result is None


# ---------------------------------------------------------------------------
# Deleted-symbol guard: _resolve_staging_db and _enrichment_target_db are gone
# ---------------------------------------------------------------------------


def test_legacy_resolvers_deleted_from_geo_staging() -> None:
    """_resolve_staging_db and _enrichment_target_db must not exist in geo_staging."""
    import resolvekit.builder.pipeline.geo_staging as geo_staging_mod

    assert not hasattr(geo_staging_mod, "_resolve_staging_db"), (
        "_resolve_staging_db still present — was it deleted from geo_staging.py?"
    )
    assert not hasattr(geo_staging_mod, "_enrichment_target_db"), (
        "_enrichment_target_db still present — was it deleted from geo_staging.py?"
    )
