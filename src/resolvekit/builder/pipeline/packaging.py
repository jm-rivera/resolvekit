"""Datapack export and packaging-time QA helpers."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from resolvekit.builder.models import (
    EntityFilter,
    ModuleRecipe,
    QualityPolicy,
)
from resolvekit.builder.module_catalog import module_id_for_entity_type
from resolvekit.builder.pipeline.qa import suspicious_drift_issues
from resolvekit.builder.pipeline.types import (
    FEATURE_SCHEMA_BY_DOMAIN,
    BuildExecutionError,
    DomainArtifacts,
)
from resolvekit.builder.sqlite import (
    build_symspell_dictionary,
    compute_selected_ids,
    copy_subset_to_datapack,
    validate_domain_db,
)
from resolvekit.builder.sqlite.context import connect_sqlite, transaction
from resolvekit.builder.utils import ensure_dir, sha256_file, utc_now_iso
from resolvekit.core.datapack import (
    ENTITY_SCHEMA_VERSION,
    NORMALIZER_VERSION,
    DataPackLoader,
    DataPackMetadata,
)

if TYPE_CHECKING:
    from resolvekit.builder.pipeline.core import BuildContext


def package_domain(
    *,
    context: BuildContext,
    recipe: ModuleRecipe,
    domain: str,
    source_db: Path,
    version: str,
    output_path: Path,
    previous_db: Path | None,
    quality_policy: QualityPolicy,
    selected_ids: set[str] | None = None,
    allowed_targets: set[str] | None = None,
) -> DomainArtifacts:
    """Package one domain datapack and enforce domain QA gates.

    The pack is built into a run-scoped work directory and only published to
    *output_path* once every gate passes, so a failed structural or
    suspicious-drop check never overwrites the on-disk (published) pack — the
    invariant that makes in-place rebuild safe.
    """
    if not source_db.exists():
        raise BuildExecutionError(f"Missing staging database for domain '{domain}'.")

    work_dir = context.run_dir / "packaging" / recipe.module_id.replace(".", "_")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    ensure_dir(work_dir)

    # Resolve data_version: prefer an explicitly set caller value; fall back to
    # the existing on-disk pack's data_version so a plain rebuild doesn't reset
    # a CalVer that release_data.py already stamped.
    if "data_version" in context.options.model_fields_set:
        resolved_data_version = context.options.data_version
    else:
        existing_meta_path = output_path / "metadata.json"
        if existing_meta_path.exists():
            try:
                resolved_data_version = (
                    DataPackMetadata.from_file(existing_meta_path).data_version
                    or context.options.data_version
                )
            except Exception:
                resolved_data_version = context.options.data_version
        else:
            resolved_data_version = context.options.data_version

    calibrator_source_path = (
        output_path / f"{recipe.domain}_calibrator.json"
        if recipe.include_calibrator
        else None
    )
    work_sqlite, metrics, issues = export_domain_datapack(
        domain=domain,
        source_db=source_db,
        output_dir=work_dir,
        entity_filter=recipe.entity_filter,
        recipe=recipe,
        version=version,
        data_version=resolved_data_version,
        selected_ids=selected_ids,
        allowed_targets=allowed_targets,
        calibrator_source_path=calibrator_source_path,
    )
    metadata_issues = validate_packaged_artifacts(
        domain_dir=work_dir,
        sqlite_path=work_sqlite,
        include_symspell=recipe.include_symspell,
        include_calibrator=recipe.include_calibrator,
    )
    if metadata_issues:
        raise BuildExecutionError(
            f"Packaged artifacts invalid for {domain}: {metadata_issues}"
        )

    drift_issues = suspicious_drift_issues(
        module_id=recipe.module_id,
        domain=domain,
        current_metrics=metrics,
        quality_policy=quality_policy,
        previous_db=previous_db,
    )

    if issues:
        raise BuildExecutionError(
            f"Packaged datapack failed structural validation for {domain}: {issues}"
        )
    if quality_policy.fail_on_suspicious_drop and drift_issues:
        raise BuildExecutionError(
            f"Suspicious-drop QA failed for {recipe.module_id}/{domain}: {drift_issues}"
        )

    _publish_pack(work_dir=work_dir, output_path=output_path)

    qa_checks = {
        "structural_issues": issues,
        "drift_issues": drift_issues,
        "passed": (not issues and not drift_issues),
    }
    return DomainArtifacts(
        domain=domain,
        datapack_dir=output_path,
        sqlite_path=output_path / "entities.sqlite",
        metrics=metrics,
        qa_checks=qa_checks,
    )


def _publish_pack(*, work_dir: Path, output_path: Path) -> None:
    """Crash-safe publish: stage new pack then atomically swap it in.

    The slow cross-filesystem copy lands on a sibling staging dir
    (``.<name>.incoming``) which is on the same filesystem as *output_path*,
    so the final swap-in is an atomic ``os.replace``.  The previous pack is
    moved aside (``.<name>.prev``) before the swap, giving a rollback target
    if the swap fails.  On success the backup is removed; on failure the
    backup is restored and the exception re-raised.

    The ``.<name>.incoming`` / ``.<name>.prev`` staging dirs are full packs
    (they do contain ``metadata.json``), but ``iter_datapack_dirs`` skips
    dot-prefixed directories, so neither in-flight nor crash-leftover staging
    dirs are mistaken for live datapacks. ``find_latest_datapack_dir`` is only
    ever called with a canonical (non-dotted) module dir, so it is unaffected.
    """
    ensure_dir(output_path.parent)
    staging = output_path.with_name(f".{output_path.name}.incoming")
    backup = output_path.with_name(f".{output_path.name}.prev")

    shutil.rmtree(staging, ignore_errors=True)
    # Copy work_dir → staging (may cross filesystems; that's fine here).
    shutil.move(str(work_dir), str(staging))

    # Move aside existing published pack (atomic on same fs).
    shutil.rmtree(backup, ignore_errors=True)
    if output_path.exists():
        os.replace(output_path, backup)

    # Swap staging into the live location (atomic on same fs).
    try:
        os.replace(str(staging), str(output_path))
    except OSError:
        # Rollback: restore the backup if we have it.
        if backup.exists():
            os.replace(backup, output_path)
        raise

    shutil.rmtree(backup, ignore_errors=True)


def export_domain_datapack(
    *,
    domain: str,
    source_db: Path,
    output_dir: Path,
    entity_filter: EntityFilter,
    recipe: ModuleRecipe,
    version: str,  # module release version (semver/calver)
    data_version: str,  # data vintage CalVer, e.g. "2026.04"
    selected_ids: set[str] | None = None,
    allowed_targets: set[str] | None = None,
    calibrator_source_path: Path | None = None,
) -> tuple[Path, dict[str, float | int], list[str]]:
    """Create filtered datapack SQLite + metadata for one domain.

    Returns the packaged SQLite path, its QA metrics, and any structural
    validation issues. Metrics are embedded in ``metadata.json`` (as
    ``quality_metrics``) so the artifact is self-describing for the release
    ledger, and returned so the caller need not re-validate.

    Always emits ``distribution="bundled"`` metadata; the release script
    (``scripts/release/release_data.py``) upgrades a pack to remote and stamps
    its ``remote_artifacts`` once the GitHub Release URLs and hashes are known.
    """
    sqlite_path = output_dir / "entities.sqlite"
    if sqlite_path.exists():
        sqlite_path.unlink()

    resolved_selected_ids = (
        selected_ids
        if selected_ids is not None
        else compute_selected_ids(source_db, entity_filter)
    )
    copy_subset_to_datapack(
        source_db,
        sqlite_path,
        resolved_selected_ids,
        allowed_targets=allowed_targets,
    )

    metrics, issues = validate_domain_db(
        sqlite_path,
        allow_external_relation_targets=True,
    )

    artifacts: dict[str, str] = {}
    if recipe.include_symspell:
        symspell_path = output_dir / "symspell.dict"
        build_symspell_dictionary(sqlite_path, symspell_path)
        artifacts["symspell"] = symspell_path.name

    if calibrator_source_path is not None and calibrator_source_path.exists():
        cal_dest = output_dir / calibrator_source_path.name
        shutil.copy2(calibrator_source_path, cal_dest)
        artifacts["calibrator"] = cal_dest.name

    checksums = {"sqlite": sha256_file(sqlite_path)}
    if "symspell" in artifacts:
        checksums["symspell"] = sha256_file(output_dir / artifacts["symspell"])
    if "calibrator" in artifacts:
        checksums["calibrator"] = sha256_file(output_dir / artifacts["calibrator"])

    metadata = DataPackMetadata(
        datapack_id=f"{recipe.module_id}-v{version}",
        module_id=recipe.module_id,
        domain_pack_id=domain,
        module_dependencies=_derive_module_dependencies(
            source_db=source_db,
            recipe=recipe,
            selected_ids=resolved_selected_ids,
        ),
        entity_schema_version=ENTITY_SCHEMA_VERSION,
        feature_schema_version=FEATURE_SCHEMA_BY_DOMAIN.get(
            domain, f"{domain}.features.v1"
        ),
        normalizer_version=NORMALIZER_VERSION,
        index_versions={"fts": "fts5", "symspell": artifacts.get("symspell")},
        build_timestamp=utc_now_iso(),
        source_datasets=recipe.source_datasets,
        description=recipe.description,
        artifacts=artifacts or None,
        pack_type="base",
        store_type="sqlite",
        store_file="entities.sqlite",
        checksums=checksums,
        data_version=data_version,
        distribution="bundled",
        min_resolvekit_version="0.1.0a1",
        quality_metrics=dict(metrics),
    )
    metadata.to_file(output_dir / "metadata.json")
    return sqlite_path, metrics, issues


def validate_packaged_artifacts(
    *,
    domain_dir: Path,
    sqlite_path: Path,
    include_symspell: bool,
    include_calibrator: bool = False,
) -> list[str]:
    """Validate required packaged artifacts and metadata consistency."""
    issues: list[str] = []
    metadata_path = domain_dir / "metadata.json"

    if not sqlite_path.exists():
        issues.append(f"Missing sqlite artifact: {sqlite_path.name}")
    if not metadata_path.exists():
        issues.append("Missing metadata.json")
        return issues

    try:
        metadata = DataPackMetadata.from_file(metadata_path)
    except Exception as exc:
        issues.append(f"Invalid metadata.json: {exc}")
        return issues

    if metadata.store_file != "entities.sqlite":
        issues.append(f"Unexpected metadata.store_file={metadata.store_file}")
    if metadata.domain_pack_id.strip() == "":
        issues.append("metadata.domain_pack_id must be non-empty")
    if metadata.feature_schema_version.strip() == "":
        issues.append("metadata.feature_schema_version must be non-empty")

    symspell_name = metadata.artifacts.get("symspell") if metadata.artifacts else None
    calibrator_name = (
        metadata.artifacts.get("calibrator") if metadata.artifacts else None
    )
    issues.extend(
        _validate_metadata_checksums(
            metadata=metadata,
            include_symspell=include_symspell,
            symspell_name=symspell_name,
            include_calibrator=include_calibrator,
            calibrator_name=calibrator_name,
        )
    )

    if include_symspell:
        if not symspell_name:
            issues.append("SymSpell enabled but metadata artifact is missing")
        elif not (domain_dir / symspell_name).exists():
            issues.append(f"Missing symspell artifact: {symspell_name}")

    if include_calibrator:
        if not calibrator_name:
            issues.append("Calibrator enabled but metadata artifact is missing")
        elif not (domain_dir / calibrator_name).exists():
            issues.append(f"Missing calibrator artifact: {calibrator_name}")

    try:
        DataPackLoader(validate_checksums=True).load(domain_dir)
    except Exception as exc:
        issues.append(f"Checksum validation failed: {exc}")

    return issues


def _derive_module_dependencies(
    *,
    source_db: Path,
    recipe: ModuleRecipe,
    selected_ids: set[str],
) -> list[str]:
    """Derive immediate module dependencies from external relation targets."""
    dependencies = list(dict.fromkeys(recipe.module_dependencies))
    if not selected_ids:
        return dependencies

    with connect_sqlite(source_db) as conn, transaction(conn):
        conn.execute("CREATE TEMP TABLE selected_ids(entity_id TEXT PRIMARY KEY)")
        conn.executemany(
            "INSERT INTO selected_ids(entity_id) VALUES (?)",
            [(entity_id,) for entity_id in sorted(selected_ids)],
        )
        rows = conn.execute(
            """
            SELECT DISTINCT target.entity_type
            FROM relations rel
            INNER JOIN selected_ids selected
                ON selected.entity_id = rel.entity_id
            INNER JOIN entities target
                ON target.entity_id = rel.target_id
            LEFT JOIN selected_ids selected_target
                ON selected_target.entity_id = rel.target_id
            WHERE selected_target.entity_id IS NULL
            ORDER BY target.entity_type
            """
        ).fetchall()
        conn.execute("DROP TABLE selected_ids")

    for row in rows:
        entity_type = str(row[0]).strip()
        if not entity_type:
            continue
        module_id = module_id_for_entity_type(entity_type)
        if module_id is None or module_id == recipe.module_id:
            continue
        if module_id not in dependencies:
            dependencies.append(module_id)
    return dependencies


def _validate_metadata_checksums(
    *,
    metadata: DataPackMetadata,
    include_symspell: bool,
    symspell_name: str | None,
    include_calibrator: bool = False,
    calibrator_name: str | None = None,
) -> list[str]:
    """Validate checksum metadata presence before hashing files."""
    issues: list[str] = []
    if not metadata.checksums:
        issues.append("metadata.checksums must be present")
        return issues
    if "sqlite" not in metadata.checksums:
        issues.append("metadata.checksums must include sqlite")
    if include_symspell and symspell_name and "symspell" not in metadata.checksums:
        issues.append("metadata.checksums must include symspell")
    if (
        include_calibrator
        and calibrator_name
        and "calibrator" not in metadata.checksums
    ):
        issues.append("metadata.checksums must include calibrator")
    return issues
