"""Unit tests for calibrator artifact registration in the builder pipeline."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from resolvekit.builder.models import EntityFilter, ModuleRecipe
from resolvekit.builder.module_catalog import module_entry, module_recipe
from resolvekit.builder.pipeline.packaging import (
    export_domain_datapack,
    validate_packaged_artifacts,
)
from resolvekit.core.store.sqlite_helpers import ensure_sqlite_schema

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_source_db(tmp_path: Path) -> Path:
    """Create a minimal staging SQLite with one geo.country entity."""
    db_path = tmp_path / "source.sqlite"
    ensure_sqlite_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO entities
                (entity_id, entity_type, canonical_name, canonical_name_norm,
                 valid_from, valid_until, attrs_json)
            VALUES (?, ?, ?, ?, NULL, NULL, '{}')
            """,
            ("country/TST", "geo.country", "Testland", "testland"),
        )
        conn.execute(
            """
            INSERT INTO names
                (entity_id, name_kind, value, value_norm, lang, script, is_preferred)
            VALUES (?, 'canonical', 'Testland', 'testland', 'en', '', 1)
            """,
            ("country/TST",),
        )
        conn.commit()
    return db_path


def _minimal_recipe(include_symspell: bool = False) -> ModuleRecipe:
    """Minimal ModuleRecipe for geo.test that mirrors the real catalog shape."""
    return ModuleRecipe(
        module_id="geo.test",
        domain="geo",
        entity_filter=EntityFilter(
            include_entity_types=["geo.country"],
            include_relation_targets=False,
        ),
        include_symspell=include_symspell,
        source_datasets=["test"],
    )


def _tiny_platt_json(path: Path) -> Path:
    """Write a minimal Platt calibrator JSON fixture to *path*."""
    path.write_text(
        json.dumps({"a": -3.5, "b": 0.1, "type": "platt", "version": "1"}),
        encoding="utf-8",
    )
    return path


def _minimal_metadata_payload(
    *,
    domain: str = "geo",
    include_calibrator_artifact: bool = False,
) -> dict:
    """Build a metadata payload suitable for validate_packaged_artifacts tests."""
    artifacts: dict[str, str] = {}
    checksums: dict[str, str] = {"sqlite": "aabbccdd"}
    if include_calibrator_artifact:
        artifacts["calibrator"] = "geo_calibrator.json"
        checksums["calibrator"] = "deadbeef"
    return {
        "datapack_id": f"{domain}-test-v1",
        "module_id": f"{domain}.test",
        "domain_pack_id": domain,
        "entity_schema_version": "1.0",
        "feature_schema_version": f"{domain}.features.v1",
        "index_versions": {"fts": "fts5", "symspell": None},
        "build_timestamp": "2026-01-01T00:00:00Z",
        "source_datasets": ["test"],
        "artifacts": artifacts or None,
        "pack_type": "base",
        "store_type": "sqlite",
        "store_file": "entities.sqlite",
        "checksums": checksums,
    }


# ---------------------------------------------------------------------------
# export_domain_datapack calibrator registration
# ---------------------------------------------------------------------------


def test_export_registers_calibrator(tmp_path: Path) -> None:
    """With calibrator_source_path supplied, metadata registers artifact + checksum."""
    source_db = _minimal_source_db(tmp_path)
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    cal_source = _tiny_platt_json(tmp_path / "geo_calibrator.json")
    recipe = _minimal_recipe()

    export_domain_datapack(
        domain="geo",
        source_db=source_db,
        output_dir=output_dir,
        entity_filter=recipe.entity_filter,
        recipe=recipe,
        version="0.0.0",
        data_version="2026.01",
        calibrator_source_path=cal_source,
    )

    metadata = json.loads((output_dir / "metadata.json").read_text())
    artifacts = metadata.get("artifacts") or {}
    checksums = metadata.get("checksums") or {}

    assert artifacts.get("calibrator") == "geo_calibrator.json", (
        "calibrator must be registered in artifacts"
    )
    assert "calibrator" in checksums, "calibrator checksum must be present"
    assert (output_dir / "geo_calibrator.json").exists(), (
        "calibrator file must be copied into output_dir"
    )


def test_export_omits_calibrator_when_source_none(tmp_path: Path) -> None:
    """When calibrator_source_path is None, no calibrator key appears."""
    source_db = _minimal_source_db(tmp_path)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    recipe = _minimal_recipe()

    export_domain_datapack(
        domain="geo",
        source_db=source_db,
        output_dir=output_dir,
        entity_filter=recipe.entity_filter,
        recipe=recipe,
        version="0.0.0",
        data_version="2026.01",
        calibrator_source_path=None,
    )

    metadata = json.loads((output_dir / "metadata.json").read_text())
    artifacts = metadata.get("artifacts") or {}
    checksums = metadata.get("checksums") or {}

    assert "calibrator" not in artifacts
    assert "calibrator" not in checksums


# ---------------------------------------------------------------------------
# validate_packaged_artifacts calibrator presence check
# ---------------------------------------------------------------------------


def test_validate_flags_missing_calibrator(tmp_path: Path) -> None:
    """include_calibrator=True but no artifact → issue list is non-empty."""
    domain_dir = tmp_path / "geo"
    domain_dir.mkdir()

    sqlite_path = domain_dir / "entities.sqlite"
    sqlite_path.write_bytes(b"x")

    payload = _minimal_metadata_payload(include_calibrator_artifact=False)
    (domain_dir / "metadata.json").write_text(json.dumps(payload))

    issues = validate_packaged_artifacts(
        domain_dir=domain_dir,
        sqlite_path=sqlite_path,
        include_symspell=False,
        include_calibrator=True,
    )

    assert any("calibrator" in issue.lower() for issue in issues), (
        f"Expected a calibrator-related issue, got: {issues}"
    )


def test_validate_passes_when_calibrator_disabled(tmp_path: Path) -> None:
    """include_calibrator=False (default) ignores absent calibrator artifact."""
    domain_dir = tmp_path / "geo"
    domain_dir.mkdir()

    sqlite_path = domain_dir / "entities.sqlite"
    sqlite_path.write_bytes(b"x")

    payload = _minimal_metadata_payload(include_calibrator_artifact=False)
    (domain_dir / "metadata.json").write_text(json.dumps(payload))

    issues = validate_packaged_artifacts(
        domain_dir=domain_dir,
        sqlite_path=sqlite_path,
        include_symspell=False,
        include_calibrator=False,
    )

    # Only non-calibrator issues (e.g. checksum mismatch on the sqlite stub) may
    # appear; no calibrator-specific complaint should be present.
    assert not any("calibrator" in issue.lower() for issue in issues)


def test_validate_flags_missing_calibrator_file(tmp_path: Path) -> None:
    """Artifact registered in metadata but file absent → file-missing issue."""
    domain_dir = tmp_path / "geo"
    domain_dir.mkdir()

    sqlite_path = domain_dir / "entities.sqlite"
    sqlite_path.write_bytes(b"x")

    payload = _minimal_metadata_payload(include_calibrator_artifact=True)
    # Do NOT create geo_calibrator.json in domain_dir — file is absent.
    (domain_dir / "metadata.json").write_text(json.dumps(payload))

    issues = validate_packaged_artifacts(
        domain_dir=domain_dir,
        sqlite_path=sqlite_path,
        include_symspell=False,
        include_calibrator=True,
    )

    assert any("calibrator" in issue.lower() for issue in issues), (
        f"Expected a calibrator-related issue for missing file, got: {issues}"
    )


# ---------------------------------------------------------------------------
# module_recipe propagates include_calibrator from catalog entry
# ---------------------------------------------------------------------------


def test_module_recipe_propagates_include_calibrator() -> None:
    """geo.countries catalog entry has include_calibrator=True; recipe reflects it."""
    countries_entry = module_entry("geo.countries")
    assert countries_entry.include_calibrator is True, (
        "geo.countries catalog entry must set include_calibrator=True"
    )

    countries_recipe = module_recipe(countries_entry)
    assert countries_recipe.include_calibrator is True, (
        "module_recipe must propagate include_calibrator=True from the catalog entry"
    )


@pytest.mark.parametrize(
    "module_id",
    [
        "geo.admin1",
        "geo.regions",
        "geo.continental_unions",
        "geo.cities",
        "org.providers",
    ],
)
def test_non_countries_entries_have_include_calibrator_false(module_id: str) -> None:
    """Non-countries entries must default include_calibrator to False."""
    entry = module_entry(module_id)
    recipe = module_recipe(entry)
    assert entry.include_calibrator is False, (
        f"{module_id} catalog entry should not set include_calibrator"
    )
    assert recipe.include_calibrator is False, (
        f"{module_id} recipe should default include_calibrator to False"
    )
