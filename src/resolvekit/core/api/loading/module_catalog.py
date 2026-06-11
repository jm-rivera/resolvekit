"""Module discovery, dependency resolution, and remote-data availability checks.

These helpers are called during ``Resolver.from_modules`` / ``auto``
construction to find, filter, and validate the set of datapacks to load.
"""

from __future__ import annotations

import logging
from collections import deque
from pathlib import Path

from resolvekit.core.api.loading.paths import _expand_datapack_input
from resolvekit.core.datapack import DataPackMetadata, LoadedDataPack
from resolvekit.core.errors import (
    DataModuleNotFoundError,
    DataPackNotAvailableError,
    MissingModuleDependencyError,
    NoModulesInstalledError,
    UnsupportedStoreError,
)
from resolvekit.core.module_registry import list_available_modules
from resolvekit.core.overlay_loader import OverlayLoader

logger = logging.getLogger(__name__)


def _ensure_remote_data_available(
    datapack_paths: list[str | Path],
    pack_filter: set[str],
) -> None:
    """Pre-scan all datapacks and handle remote data availability.

    Scans all modules to find which are remote and uncached, then either
    batch-downloads them (if auto_download is enabled) or raises a single
    error listing ALL missing modules with total size.

    Only considers modules whose ``domain_pack_id`` is in *pack_filter*
    (when non-empty), matching the filtering that
    ``_load_and_separate_datapacks`` will apply later.
    """
    from resolvekit.core.config import get_auto_download, get_offline
    from resolvekit.core.module_registry import (
        get_manifest_overrides,
        load_module_metadata,
    )
    from resolvekit.core.remote import (
        download_module_data,
        is_cached,
    )

    manifest_overrides = get_manifest_overrides()
    missing: list[tuple[DataPackMetadata, Path]] = []

    for path_or_name in datapack_paths:
        path = Path(path_or_name)
        meta_path = path / "metadata.json"
        if not meta_path.exists():
            continue
        # ``module_id`` is needed to key manifest overrides, but we only have
        # it after parsing metadata — load once, then apply overrides.
        base = DataPackMetadata.from_file(meta_path)
        metadata = load_module_metadata(
            base.module_id, path, overrides=manifest_overrides
        )
        if pack_filter and metadata.domain_pack_id not in pack_filter:
            continue
        if metadata.distribution != "remote":
            continue
        if is_cached(metadata):
            continue
        missing.append((metadata, path))

    if not missing:
        return

    if get_offline() or not get_auto_download():
        module_ids = [m.module_id for m, _ in missing]
        total_mb = sum(m.download_size_mb or 0 for m, _ in missing)
        raise DataPackNotAvailableError(
            module_ids=module_ids,
            total_size_mb=total_mb or None,
        )

    # Auto-download all missing
    logger.info(
        "Auto-downloading %d remote module(s): %s",
        len(missing),
        ", ".join(m.module_id for m, _ in missing),
    )
    for metadata, pkg_dir in missing:
        download_module_data(metadata, pkg_dir)


def _load_and_separate_datapacks(
    datapack_paths: list[str | Path],
    pack_filter: set[str],
) -> tuple[dict[str, LoadedDataPack], dict[str, LoadedDataPack]]:
    """Load datapacks and separate into base and overlay packs.

    Only loads and validates datapacks whose domain is in pack_filter (if specified).
    This prevents validation errors for unrequested domains.

    Datapack paths must be explicit filesystem datapack paths.
    """
    from resolvekit.core.datapack import DataPackLoader

    loader = DataPackLoader()
    base_packs: dict[str, LoadedDataPack] = {}
    overlay_packs: dict[str, LoadedDataPack] = {}

    for path_or_name in datapack_paths:
        for resolved_path in _expand_datapack_input(path_or_name):
            # Check filter BEFORE loading to avoid triggering downloads
            # for excluded remote packs
            if pack_filter:
                meta_path = resolved_path / "metadata.json"
                if meta_path.exists():
                    metadata = DataPackMetadata.from_file(meta_path)
                    if metadata.domain_pack_id not in pack_filter:
                        continue

            loaded = loader.load(resolved_path)

            if loaded.metadata.store_type != "sqlite":
                raise UnsupportedStoreError(loaded.metadata.store_type)

            module_id = loaded.module_id
            if loaded.metadata.is_overlay:
                overlay_packs[module_id] = loaded
            else:
                base_packs[module_id] = loaded

    return base_packs, overlay_packs


def _remote_dependency_uncached(
    module_id: str,
    available: dict[str, Path],
    manifest_overrides: dict[str, dict[str, object]],
) -> bool:
    """Return True if ``module_id`` is a remote-distribution module whose data
    is not in the local cache.

    Such a dependency may be absent from a load set without error: remote
    packs the user hasn't downloaded are not hard errors (partial caches are
    first-class, and ``Resolver.auto()`` never triggers a network fetch).
    Bundled dependencies and unknown module ids stay hard errors.
    """
    from resolvekit.core.module_registry import load_module_metadata
    from resolvekit.core.remote import is_cached

    if module_id not in available:
        return False
    path = available[module_id]
    if not (path / "metadata.json").exists():
        return False
    metadata = load_module_metadata(module_id, path, overrides=manifest_overrides)
    return metadata.distribution == "remote" and not is_cached(metadata)


def _validate_module_dependencies(
    base_packs: dict[str, LoadedDataPack],
    overlay_packs: dict[str, LoadedDataPack],
    pack_filter: set[str],
) -> None:
    from resolvekit.core.module_registry import get_manifest_overrides

    available_module_ids = set(base_packs) | set(overlay_packs)
    registry: dict[str, Path] | None = None
    manifest_overrides: dict[str, dict[str, object]] | None = None
    for loaded in [*base_packs.values(), *overlay_packs.values()]:
        if pack_filter and loaded.pack_id not in pack_filter:
            continue

        missing = [
            module_id
            for module_id in loaded.metadata.module_dependencies
            if module_id not in available_module_ids
        ]
        if missing:
            # An absent dependency is only a hard error when its data could
            # have been loaded — a declared dep on a remote pack the user
            # hasn't downloaded is skipped, mirroring the auto-mode intent in
            # _resolve_requested_module_paths.
            if registry is None:
                registry = list_available_modules()
                manifest_overrides = get_manifest_overrides()
            assert manifest_overrides is not None
            missing = [
                module_id
                for module_id in missing
                if not _remote_dependency_uncached(
                    module_id, registry, manifest_overrides
                )
            ]
        if missing:
            raise MissingModuleDependencyError(loaded.module_id, missing)


def _validate_overlay_relationships(
    overlay_packs: dict[str, LoadedDataPack],
    base_packs: dict[str, LoadedDataPack],
    pack_filter: set[str],
) -> None:
    """Validate overlay → base relationships exist and are compatible.

    Only validates overlays whose domain is in pack_filter (if specified).
    """
    overlay_loader = OverlayLoader()

    for overlay in overlay_packs.values():
        # Skip validation if domain not in filter
        if pack_filter and overlay.pack_id not in pack_filter:
            continue

        missing = [
            module_id
            for module_id in overlay.metadata.base_module_ids or []
            if module_id not in base_packs
        ]
        if missing:
            raise MissingModuleDependencyError(overlay.module_id, missing)
        overlay_loader.load(overlay.base_path, base_modules=base_packs)


def _module_data_locally_available(
    module_id: str,
    path: Path,
    manifest_overrides: dict[str, dict[str, object]],
) -> bool:
    """Return True if the module's sqlite is present on disk or in cache.

    Used by ``Resolver.auto()`` / ``from_modules(None)`` to silently skip
    remote modules the user hasn't opted into downloading.
    """
    from resolvekit.core.module_registry import load_module_metadata
    from resolvekit.core.remote import is_cached

    if not (path / "metadata.json").exists():
        return False
    metadata = load_module_metadata(module_id, path, overrides=manifest_overrides)
    if metadata.distribution == "bundled":
        return (path / metadata.store_file).exists()
    return is_cached(metadata)


def _resolve_requested_module_paths(
    module_ids: list[str] | None,
) -> dict[str, Path]:
    from resolvekit.core.module_registry import (
        get_manifest_overrides,
        load_module_metadata,
    )

    available = list_available_modules()
    manifest_overrides = get_manifest_overrides()
    auto_mode = module_ids is None
    if auto_mode:
        if not available:
            raise NoModulesInstalledError()
        # For ``Resolver.auto()`` / ``from_modules(None)`` we only pick up
        # modules whose data is actually present locally: bundled (sqlite
        # shipped in the wheel) or remote packs already cached under
        # ``~/.cache/resolvekit/``. Remote modules the user hasn't
        # explicitly opted into are silently skipped — per v1-scope §225,
        # auto() never triggers a network fetch.
        requested = [
            module_id
            for module_id in available
            if _module_data_locally_available(
                module_id, available[module_id], manifest_overrides
            )
        ]
        if not requested:
            raise NoModulesInstalledError()
    else:
        assert module_ids is not None
        requested = list(dict.fromkeys(module_ids))

    resolved: dict[str, Path] = {}
    queue = deque(requested)
    while queue:
        module_id = queue.popleft()
        if module_id in resolved:
            continue
        if module_id not in available:
            raise DataModuleNotFoundError(module_id, searched=sorted(available))
        path = available[module_id]
        resolved[module_id] = path

        metadata = load_module_metadata(module_id, path, overrides=manifest_overrides)
        for dependency in metadata.module_dependencies:
            if dependency in resolved:
                continue
            # In auto mode, silently skip dependencies whose data isn't
            # locally available (remote packs the user hasn't downloaded
            # are not hard errors — see v1-scope §225). In explicit mode,
            # likewise skip remote-uncached dependencies so requesting one
            # module never transitively forces sibling downloads; unknown
            # module ids are still queued so the queue-loop's own
            # ``module_id not in available`` check raises
            # ``DataModuleNotFoundError``.
            if auto_mode and (
                dependency not in available
                or not _module_data_locally_available(
                    dependency, available[dependency], manifest_overrides
                )
            ):
                continue
            if not auto_mode and _remote_dependency_uncached(
                dependency, available, manifest_overrides
            ):
                continue
            queue.append(dependency)
        if metadata.is_overlay:
            for dependency in metadata.base_module_ids or []:
                if dependency in resolved:
                    continue
                if auto_mode and (
                    dependency not in available
                    or not _module_data_locally_available(
                        dependency, available[dependency], manifest_overrides
                    )
                ):
                    continue
                queue.append(dependency)

    return resolved
