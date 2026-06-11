"""Regenerate the bundled module manifest from the on-disk datapacks.

The aggregate manifest at ``src/resolvekit/_data/manifest.json`` is the
authoritative, wheel-shipped index that ``resolvekit.core.module_registry``
loads and that ``scripts.release.verify_bundled_data`` checks SQLite checksums
against. A rebuild changes every pack's SQLite content, so the manifest's
``checksums.sqlite`` and ``size_mb`` go stale. This script rebuilds the manifest
deterministically so those never have to be hand-edited.

Source of truth per field:
- ``distribution``, ``domain``, ``entity_types`` come from the **module catalog**
  (``module_catalog.catalog_entries``), not from each pack's ``metadata.json``.
  A plain ``build()`` writes ``distribution="bundled"`` into every pack; the
  catalog (via ``REMOTE_MODULE_IDS``) decides what actually ships remotely.
- For **bundled** modules, ``checksums.sqlite`` and ``size_mb`` are computed from
  the built SQLite file (the local file is the shipped data).
- For **remote** modules, the per-artifact spec lives in
  ``metadata.remote_artifacts`` (one entry per downloadable file: sqlite plus
  every key in ``artifacts``). ``release_data`` stamps it with the current
  release's URLs and asset hashes. The manifest displays only the sqlite URL
  plus the total download size — readers needing full per-artifact info load
  the pack's metadata.json. If a remote pack's SQLite is materialized (rebuilt)
  and its hash no longer matches the released checksum, the script warns that
  the ``.gz`` asset is stale (re-run release_data).

This script does NOT touch per-module ``metadata.json`` (a build already writes
correct checksums there) nor the release ledger.

Run via::

    uv run python -m scripts.release.sync_manifest                  # write
    RESOLVEKIT_MANIFEST_DRY_RUN=1 uv run python -m scripts.release.sync_manifest   # diff only
    RESOLVEKIT_MANIFEST_CHECK=1   uv run python -m scripts.release.sync_manifest   # exit 1 on drift
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from resolvekit.builder.datapack_layout import module_pack_dir
from resolvekit.builder.module_catalog import (
    DistributionStrategy,
    catalog_entries,
)
from resolvekit.builder.utils import sha256_file
from resolvekit.core.datapack import DataPackMetadata
from scripts.release._common import PROJECT_ROOT

logger = logging.getLogger(__name__)

DATA_ROOT = PROJECT_ROOT / "src" / "resolvekit" / "_data"
MANIFEST_PATH = DATA_ROOT / "manifest.json"
SCHEMA_VERSION = 1

MANIFEST_DRY_RUN_ENV = "RESOLVEKIT_MANIFEST_DRY_RUN"
MANIFEST_CHECK_ENV = "RESOLVEKIT_MANIFEST_CHECK"


@dataclass(frozen=True, slots=True, kw_only=True)
class SyncManifestSettings:
    """Settings for a manifest regeneration."""

    # Print a unified diff and exit without writing.
    dry_run: bool = False
    # Exit non-zero if the on-disk manifest differs from the regenerated one
    # (no write). For CI / pre-commit guards.
    check: bool = False


def _size_mb(path: Path) -> float:
    """Megabytes (binary), rounded to 2 decimals to match the manifest."""
    return round(path.stat().st_size / (1024 * 1024), 2)


def _bundled_row(entry: Any, *, size_mb: float, sqlite_sha: str) -> dict[str, Any]:
    """Canonical-ordered manifest row for a bundled module."""
    return {
        "module_id": entry.module_id,
        "distribution": entry.distribution.value,
        "domain": entry.domain,
        "entity_types": list(entry.include_entity_types),
        "size_mb": size_mb,
        "checksums": {"sqlite": sqlite_sha},
    }


def _remote_row(
    entry: Any,
    *,
    size_mb: float,
    remote_artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Canonical-ordered manifest row for a remote module.

    Carries ``remote_artifacts`` structurally so the runtime override
    mechanism (``module_registry._MANIFEST_DISTRIBUTION_FIELDS``) can promote
    a pack from bundled to remote without re-reading its on-disk metadata.
    Display fields (``remote_url``, ``download_size_mb``) are derived from
    ``remote_artifacts['sqlite']`` by ``DataPackMetadata`` properties.
    """
    return {
        "module_id": entry.module_id,
        "distribution": entry.distribution.value,
        "domain": entry.domain,
        "entity_types": list(entry.include_entity_types),
        "size_mb": size_mb,
        "remote_artifacts": remote_artifacts,
    }


def build_manifest() -> tuple[dict[str, Any], list[str]]:
    """Build the manifest dict from catalog + on-disk packs.

    Bundled rows are computed from the local SQLite (it is the shipped data).
    Remote rows are derived from ``metadata.remote_artifacts['sqlite']``
    (``release_data`` stamps it with the release URL and per-artifact hashes).

    Returns ``(manifest, stale_remote_module_ids)`` where the second element
    lists remote modules whose materialized (rebuilt) SQLite no longer matches
    the released checksum — i.e. the ``.gz`` asset is stale and release_data
    must be re-run before the manifest is trustworthy.
    """
    modules: list[dict[str, Any]] = []
    stale_remote: list[str] = []

    for entry in catalog_entries():
        pack_dir = module_pack_dir(module_id=entry.module_id, datapacks_root=DATA_ROOT)
        meta_path = pack_dir / "metadata.json"
        if not meta_path.exists():
            logger.info("Skip %s (no pack at %s)", entry.module_id, pack_dir)
            continue

        metadata = DataPackMetadata.from_file(meta_path)
        sqlite_path = pack_dir / metadata.store_file
        materialized = sqlite_path.exists() and sqlite_path.stat().st_size > 0

        if entry.distribution is DistributionStrategy.REMOTE:
            if (
                not metadata.remote_artifacts
                or "sqlite" not in metadata.remote_artifacts
            ):
                logger.warning(
                    "Skip %s (no release info in metadata — run "
                    "scripts.release.release_data first)",
                    entry.module_id,
                )
                continue
            sqlite_spec = metadata.remote_artifacts["sqlite"]
            if materialized and sqlite_spec.sha256 != sha256_file(sqlite_path):
                stale_remote.append(entry.module_id)
            modules.append(
                _remote_row(
                    entry,
                    size_mb=metadata.download_size_mb or 0.0,
                    remote_artifacts={
                        atype: spec.model_dump()
                        for atype, spec in metadata.remote_artifacts.items()
                    },
                )
            )
            continue

        # Bundled: the local SQLite is the shipped data.
        if not materialized:
            logger.warning(
                "Skip %s (no materialized SQLite at %s)", entry.module_id, sqlite_path
            )
            continue
        modules.append(
            _bundled_row(
                entry,
                size_mb=_size_mb(sqlite_path),
                sqlite_sha=sha256_file(sqlite_path),
            )
        )

    return {"schema_version": SCHEMA_VERSION, "modules": modules}, stale_remote


def _render(manifest: dict[str, Any]) -> str:
    """Serialize to the canonical manifest text (indent=2, trailing newline)."""
    return json.dumps(manifest, indent=2) + "\n"


def _emit_diff(old_text: str, new_text: str) -> None:
    sys.stdout.writelines(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile="manifest.json (current)",
            tofile="manifest.json (regenerated)",
        )
    )


def run(*, settings: SyncManifestSettings) -> None:
    """Regenerate the manifest; behaviour depends on dry_run / check flags."""
    manifest, stale_remote = build_manifest()
    new_text = _render(manifest)
    old_text = (
        MANIFEST_PATH.read_text(encoding="utf-8") if MANIFEST_PATH.exists() else ""
    )

    if stale_remote:
        logger.warning(
            "Remote module(s) changed since last release: %s. Their "
            "remote_artifacts URLs and hashes are stale — cut a new data release "
            "(scripts.release.release_data) to publish refreshed .gz assets.",
            ", ".join(stale_remote),
        )

    module_count = len(manifest["modules"])

    if new_text == old_text:
        logger.info("Manifest already in sync (%d module(s)).", module_count)
        return

    if settings.check:
        logger.error("Manifest is out of sync with on-disk packs:")
        _emit_diff(old_text, new_text)
        sys.exit(1)

    if settings.dry_run:
        logger.info("Dry run — would update manifest (%d module(s)):", module_count)
        _emit_diff(old_text, new_text)
        return

    MANIFEST_PATH.write_text(new_text, encoding="utf-8")
    logger.info("Wrote %s (%d module(s)).", MANIFEST_PATH, module_count)


def main() -> None:
    """Entry point for direct invocation; edit settings below to customize."""
    run(
        settings=SyncManifestSettings(
            dry_run=os.environ.get(MANIFEST_DRY_RUN_ENV) == "1",
            check=os.environ.get(MANIFEST_CHECK_ENV) == "1",
        )
    )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(
            "sync_manifest.py takes no CLI arguments. Set "
            "RESOLVEKIT_MANIFEST_DRY_RUN=1 (diff only) or "
            "RESOLVEKIT_MANIFEST_CHECK=1 (exit 1 on drift)."
        )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    main()
