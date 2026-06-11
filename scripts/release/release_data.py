"""Release orchestration for data packs.

Orchestrates the process of preparing data pack releases:
1. Reads existing datapacks from ``src/resolvekit/_data/`` (v1 canonical
   layout, module path = ``_data/<domain>/<subpath>/``).
2. Determines distribution strategy per module from catalog
3. For remote modules: computes sha256, generates ``remote_url``
4. Writes updated ``metadata.json`` with distribution info
5. Outputs a manifest JSON for the GitHub Release

Run via::

    RESOLVEKIT_RELEASE_CALVER=2026.1 uv run python -m scripts.release.release_data

Dry run by default (safe to invoke locally). Set ``RESOLVEKIT_RELEASE_EXECUTE=1``
to perform an actual release.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import cast

from resolvekit.builder.datapack_layout import find_latest_datapack_dir, module_pack_dir
from resolvekit.builder.models import BuildOptions, ReleaseRecord
from resolvekit.builder.module_catalog import (
    DistributionStrategy,
    catalog_entries,
    module_id_to_package_name,
)
from resolvekit.builder.registry import append_releases
from resolvekit.builder.utils import sha256_file
from resolvekit.core.datapack import DataPackMetadata, RemoteArtifactSpec
from scripts.release._common import PROJECT_ROOT

logger = logging.getLogger(__name__)

GITHUB_REPO = "jm-rivera/resolvekit"
DATAPACKS_ROOT = PROJECT_ROOT / "src" / "resolvekit" / "_data"

RELEASE_CALVER_ENV = "RESOLVEKIT_RELEASE_CALVER"
RELEASE_EXECUTE_ENV = "RESOLVEKIT_RELEASE_EXECUTE"

# The release path owns the registry. ``build()`` rebuilds in place and writes
# no ledger rows; this script is the single place a release is recorded.
BUILD_ROOT = PROJECT_ROOT / "data" / "build"


def _release_tag_exists(tag: str) -> bool:
    """Return True if a GitHub release with the given tag already exists.

    The GitHub release tag is the canonical record of what has been published.
    Using it as the immutability source means the guard works on a fresh
    clone, doesn't drift between machines, and matches the actual state
    ``gh release create`` will see when the script gets to that step.
    """
    return (
        subprocess.run(
            ["gh", "release", "view", tag, "--json", "tagName"],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def _ledger_record(
    *, module_id: str, calver: str, module_dir: Path, metadata: DataPackMetadata
) -> ReleaseRecord:
    """Build a ledger row for a released module from its on-disk metadata."""
    domain = module_id.partition(".")[0]
    metrics = {
        f"{domain}.{name}": value
        for name, value in (metadata.quality_metrics or {}).items()
    }
    return ReleaseRecord(
        module_id=module_id,
        version=calver,
        run_id=f"data-v{calver}",
        output_path=module_dir,
        domains=[domain],
        metrics=metrics,
        reports={},
    )


def _asset_name(module_id: str, local_filename: str) -> str:
    """Release asset filename for one artifact (gzip-compressed).

    Combines the module's package slug with the local filename so all assets
    for a release sit in a flat, collision-free namespace::

        geo.cities + entities.sqlite -> geo-cities-entities.sqlite.gz
        geo.cities + symspell.dict   -> geo-cities-symspell.dict.gz
    """
    slug = module_id_to_package_name(module_id).removeprefix("resolvekit-")
    return f"{slug}-{local_filename}.gz"


def _gzip_file(src: Path, dst: Path) -> None:
    """Gzip-compress *src* into *dst* using streaming to avoid loading into RAM."""
    with src.open("rb") as f_in, gzip.open(dst, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)


def _asset_url(calver: str, asset_name: str) -> str:
    """Build the GitHub Release download URL for one asset.

    If RESOLVEKIT_RELEASE_BASE_URL is set, it overrides the GitHub base URL.
    The env var must end without a trailing slash; the tag + asset path is
    appended as ``/<tag>/<asset>`` so mirrors serve the same path shape.
    """
    tag = f"data-v{calver}"
    base_override = (
        os.environ.get("RESOLVEKIT_RELEASE_BASE_URL", "").strip().rstrip("/")
    )
    if base_override:
        return f"{base_override}/{tag}/{asset_name}"
    return f"https://github.com/{GITHUB_REPO}/releases/download/{tag}/{asset_name}"


def _iter_artifact_files(
    source_dir: Path, metadata: DataPackMetadata
) -> list[tuple[str, str, Path]]:
    """Enumerate (artifact_type, local_filename, source_path) for every remote artifact.

    ``sqlite`` is always first; the order of additional artifacts follows the
    insertion order of ``metadata.artifacts`` so the generated remote_artifacts
    dict and the asset list are deterministic.
    """
    items: list[tuple[str, str, Path]] = [
        ("sqlite", metadata.store_file, source_dir / metadata.store_file),
    ]
    if metadata.artifacts:
        for atype, fname in metadata.artifacts.items():
            items.append((atype, fname, source_dir / fname))
    return items


def _prepare_remote_module(
    source_dir: Path,
    metadata: DataPackMetadata,
    calver: str,
    *,
    dry_run: bool,
) -> tuple[dict[str, object], list[dict[str, object]]] | None:
    """Prepare a remote module: gzip every artifact, compute hashes, build specs.

    Returns ``(metadata_updates, asset_infos)`` where ``asset_infos`` has one
    entry per artifact (sqlite + each in ``metadata.artifacts``). Returns
    ``None`` if any artifact file is missing on disk.
    """
    artifact_items = _iter_artifact_files(source_dir, metadata)

    for _atype, _fname, src_path in artifact_items:
        if not src_path.exists():
            logger.error(
                "ERROR %s: artifact not found at %s", metadata.module_id, src_path
            )
            return None

    remote_artifacts: dict[str, RemoteArtifactSpec | dict[str, object]] = {}
    assets: list[dict[str, object]] = []

    for atype, local_filename, src_path in artifact_items:
        asset_name = _asset_name(metadata.module_id, local_filename)
        url = _asset_url(calver, asset_name)
        decompressed_sha256 = sha256_file(src_path)
        decompressed_mb = round(src_path.stat().st_size / (1024 * 1024), 2)

        # Use the prefixed asset_name as the on-disk basename so uploads land
        # under unique names — `gh release upload path#label` only sets the
        # display label, not the asset name; the server name is the basename.
        gz_path = src_path.with_name(asset_name)
        if not dry_run:
            logger.info("GZIP %s -> %s", src_path.name, gz_path.name)
            _gzip_file(src_path, gz_path)
            gz_sha256 = sha256_file(gz_path)
            compressed_mb = round(gz_path.stat().st_size / (1024 * 1024), 2)
        else:
            gz_sha256 = "<dry-run>"
            compressed_mb = None

        remote_artifacts[atype] = RemoteArtifactSpec(
            url=url,
            sha256=decompressed_sha256,
            gz_sha256=gz_sha256,
            size_mb=decompressed_mb,
        )
        assets.append(
            {
                "module_id": metadata.module_id,
                "artifact_type": atype,
                "local_path": str(gz_path),
                "asset_name": asset_name,
                "sha256_gz": gz_sha256,
                "sha256_decompressed": decompressed_sha256,
                "size_mb": decompressed_mb,
                "compressed_mb": compressed_mb,
            }
        )

    updates: dict[str, object] = {
        "remote_artifacts": remote_artifacts,
        # Remote packs don't carry a top-level checksums dict;
        # every artifact's SHA lives in its RemoteArtifactSpec.
        "checksums": None,
    }
    return updates, assets


def run(
    calver: str,
    *,
    dry_run: bool = False,
) -> dict[str, object]:
    """Prepare a data release for the given CalVer version.

    Args:
        calver: Calendar-version string for the release tag.
        dry_run: Preview without writing files.

    Returns a manifest dict suitable for writing to JSON.
    """
    release_tag = f"data-v{calver}"
    assets: list[dict[str, object]] = []

    entries = catalog_entries()

    # Immutability guard: refuse to re-publish a CalVer that already has a
    # GitHub release tag. The GitHub release page is the canonical source of
    # truth — once data-v$CALVER exists there, anyone consuming the pinned
    # metadata expects those bytes. Re-running the script with the same
    # calver would otherwise produce assets that fail to upload (gh refuses
    # duplicate tags) but only after gzipping every artifact.
    options = BuildOptions(build_root=BUILD_ROOT, datapacks_root=DATAPACKS_ROOT)
    if not dry_run and _release_tag_exists(release_tag):
        raise RuntimeError(
            f"Refusing to re-release {release_tag}: a GitHub release tag "
            f"with that name already exists. Bump the calver."
        )
    if dry_run and _release_tag_exists(release_tag):
        logger.warning(
            "WOULD CONFLICT: GitHub release tag %s already exists", release_tag
        )

    for entry in entries:
        module_dir = module_pack_dir(
            module_id=entry.module_id, datapacks_root=DATAPACKS_ROOT
        )
        if not module_dir.exists():
            logger.info("SKIP %s (no datapack at %s)", entry.module_id, module_dir)
            continue

        # Supports both v1 flat layout and the legacy versioned layout.
        source_dir = find_latest_datapack_dir(module_dir=module_dir)
        if source_dir is None:
            logger.info(
                "SKIP %s (no datapack contents in %s)", entry.module_id, module_dir
            )
            continue

        meta_path = source_dir / "metadata.json"
        metadata = DataPackMetadata.from_file(meta_path)
        is_remote = entry.distribution == DistributionStrategy.REMOTE

        updates: dict[str, object] = {
            "datapack_id": f"{entry.module_id}-v{calver}",
            "distribution": entry.distribution.value,
            "data_version": calver,
        }

        if is_remote:
            result = _prepare_remote_module(
                source_dir, metadata, calver, dry_run=dry_run
            )
            if result is None:
                continue
            remote_updates, asset_infos = result
            updates.update(remote_updates)
            assets.extend(asset_infos)

        # Write updated metadata
        updated_meta = metadata.model_copy(update=updates)

        if not dry_run:
            updated_meta.to_file(meta_path)
            logger.info("UPDATED %s", meta_path)

            # Record the ledger row immediately after the metadata write so
            # that a mid-loop failure leaves a consistent prefix: modules
            # 0..k are both stamped AND ledgered, and a re-run's conflict
            # check correctly refuses the already-released ones.
            record = _ledger_record(
                module_id=entry.module_id,
                calver=calver,
                module_dir=source_dir,
                metadata=updated_meta,
            )
            append_releases(options, [record])
            logger.info("Recorded %s@%s in the ledger", entry.module_id, calver)
        else:
            logger.info("DRY-RUN %s dist=%s", entry.module_id, entry.distribution.value)

    manifest: dict[str, object] = {
        "release_tag": release_tag,
        "calver": calver,
        "assets": assets,
    }

    manifest_path = PROJECT_ROOT / "release-manifest.json"
    if not dry_run:
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        logger.info("Manifest written to %s", manifest_path)

    return manifest


def main(
    *,
    calver: str | None = None,
    dry_run: bool = False,
) -> None:
    """Prepare a data release.

    Args:
        calver: CalVer version string (e.g. ``"2026.1"``). If ``None``,
            reads from the ``RESOLVEKIT_RELEASE_CALVER`` environment variable.
        dry_run: Preview changes without writing files.

    Raises:
        RuntimeError: If *calver* is ``None`` and the environment variable is
            unset.
    """
    effective_calver = calver or os.environ.get(RELEASE_CALVER_ENV)
    if not effective_calver:
        raise RuntimeError(
            f"Set {RELEASE_CALVER_ENV} or pass calver= explicitly "
            f"(e.g. {RELEASE_CALVER_ENV}=2026.1)."
        )
    print(f"Preparing data release: data-v{effective_calver}")
    manifest = run(
        effective_calver,
        dry_run=dry_run,
    )
    release_tag = manifest["release_tag"]
    asset_list = cast(list[dict[str, object]], manifest["assets"])
    print(f"\nRelease tag: {release_tag}")
    print(f"Remote assets: {len(asset_list)}")

    for asset in asset_list:
        compressed = (
            f" -> {asset['compressed_mb']} MB gz" if asset.get("compressed_mb") else ""
        )
        print(
            f"  {asset['asset_name']}  ({asset['size_mb']} MB{compressed})"
            f"  sha256_gz:{str(asset['sha256_gz'])[:16]}..."
        )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(
            "release_data takes no CLI arguments. Set RESOLVEKIT_RELEASE_CALVER "
            "(e.g. 2026.1); set RESOLVEKIT_RELEASE_EXECUTE=1 for a real release "
            "(default is a dry run)."
        )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Dry run by default so the script is safe to invoke locally; CI sets
    # RESOLVEKIT_RELEASE_EXECUTE=1 to perform an actual release.
    execute = os.environ.get(RELEASE_EXECUTE_ENV) == "1"
    main(dry_run=not execute)
