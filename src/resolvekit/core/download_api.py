"""Public API for downloading and managing remote data packs."""

from __future__ import annotations

import logging
from pathlib import Path

from resolvekit.core.config import get_cache_dir
from resolvekit.core.datapack import DataPackMetadata
from resolvekit.core.errors import DataModuleNotFoundError
from resolvekit.core.module_registry import (
    get_manifest_overrides,
    list_available_modules,
    load_module_metadata,
)
from resolvekit.core.remote import (
    clear_all_cache,
    clear_module_cache,
    download_module_data,
    is_cached,
)

logger = logging.getLogger(__name__)


def download(target: str, *, force: bool = False) -> dict[str, Path]:
    """Download remote module data.

    Args:
        target: Module ID (``"geo.cities"``) or domain (``"geo"``)
        force: Re-download even if cached

    Returns:
        Dict of module_id -> cache_path for downloaded modules
    """
    return _download_modules(_resolve_download_targets(target), force=force)


def download_all(*, force: bool = False) -> dict[str, Path]:
    """Download all installed remote modules."""
    available = list_available_modules()
    overrides = get_manifest_overrides()
    modules = {
        module_id: (load_module_metadata(module_id, path, overrides=overrides), path)
        for module_id, path in available.items()
    }
    return _download_modules(modules, force=force)


def _download_modules(
    modules: dict[str, tuple[DataPackMetadata, Path]],
    *,
    force: bool,
) -> dict[str, Path]:
    """Shared download loop for remote modules."""
    results: dict[str, Path] = {}
    for module_id, (metadata, package_dir) in modules.items():
        if metadata.distribution != "remote":
            logger.debug("Skipping bundled module %s", module_id)
            continue
        if not force and is_cached(metadata):
            logger.info("Module %s already cached, skipping.", module_id)
            results[module_id] = get_cache_dir() / module_id
            continue
        path = download_module_data(metadata, package_dir)
        results[module_id] = path
    return results


def clear_cache(target: str | None = None) -> None:
    """Clear cached module data.

    Args:
        target: Module ID to clear, or None to clear all.
    """
    if target is None:
        clear_all_cache()
    else:
        clear_module_cache(target)


def _resolve_download_targets(
    target: str,
) -> dict[str, tuple[DataPackMetadata, Path]]:
    """Resolve a download target to module metadata + package paths.

    Supports module IDs (``"geo.cities"``) and domains (``"geo"``).
    """
    available = list_available_modules()
    overrides = get_manifest_overrides()
    modules: dict[str, tuple[DataPackMetadata, Path]] = {}

    # Check if target is an exact module ID
    if target in available:
        path = available[target]
        metadata = load_module_metadata(target, path, overrides=overrides)
        modules[target] = (metadata, path)
        return modules

    # Treat as a domain: match all modules whose module_id starts with "target."
    prefix = target + "."
    for module_id, path in available.items():
        if module_id.startswith(prefix):
            metadata = load_module_metadata(module_id, path, overrides=overrides)
            modules[module_id] = (metadata, path)

    if not modules:
        raise DataModuleNotFoundError(target, searched=sorted(available))

    return modules
