"""Installed module discovery and explicit runtime registrations.

Discovery precedence (first occurrence wins on ``module_id`` conflict):

1. Bundled manifest at ``resolvekit/_data/manifest.json`` (authoritative).
2. Explicitly registered modules via :func:`register_module`.
3. ``resolvekit.modules`` entry points (for third-party distributions).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from functools import lru_cache
from importlib import metadata as importlib_metadata
from importlib import resources
from pathlib import Path
from typing import Any

from resolvekit.core.datapack import DataPackMetadata
from resolvekit.core.errors import DataModuleNotFoundError, ModuleRegistryError

__all__ = [
    "DataModuleNotFoundError",
    "ModuleRegistryError",
    "get_canonical_manifest_paths",
    "get_manifest_overrides",
    "get_module_path",
    "is_module_remote",
    "iter_manifest_entries",
    "list_available_modules",
    "load_module_metadata",
    "module_id_to_suffix",
    "register_module",
    "unregister_module",
]

logger = logging.getLogger(__name__)

_MODULE_ENTRYPOINT_GROUP = "resolvekit.modules"
_MANIFEST_FILENAME = "manifest.json"
# Manifest fields authoritative over on-disk metadata.json. The manifest
# at _data/manifest.json may reclassify packs after they were built;
# on-disk metadata may lag. Distribution-state fields always override.
# Checksums only override for packs the manifest calls remote — bundled
# packs' on-disk metadata + sqlite agree by construction at build time.
_MANIFEST_DISTRIBUTION_FIELDS: tuple[str, ...] = (
    "distribution",
    "remote_artifacts",
)
_MANIFEST_REMOTE_ONLY_FIELDS: tuple[str, ...] = ("checksums",)
_registered: dict[str, Path] = {}


def module_id_to_suffix(module_id: str) -> str | None:
    """Convert ``geo.admin1`` -> ``admin1``; ``geo.sub.thing`` -> ``sub_thing``.

    Returns ``None`` when the module id has no ``.`` separator or a trailing
    empty component — signals to the caller that the id cannot be mapped to
    an on-disk layout under ``_data/<domain>/<suffix>/``.
    """
    parts = module_id.split(".", 1)
    if len(parts) != 2 or not parts[1]:
        return None
    return parts[1].replace(".", "_")


def register_module(module_id: str, path: str | Path) -> None:
    """Register a module datapack directory for runtime discovery."""
    _registered[module_id] = Path(path)


def unregister_module(module_id: str) -> None:
    """Remove a previously registered module."""
    _registered.pop(module_id, None)


def get_module_path(module_id: str) -> Path:
    """Resolve one installed or explicitly registered module to its datapack path."""
    available = list_available_modules()
    if module_id in available:
        return available[module_id]
    raise DataModuleNotFoundError(module_id, searched=sorted(available))


def list_available_modules() -> dict[str, Path]:
    """List installed or explicitly registered module datapacks.

    Precedence order (first occurrence wins on ``module_id`` conflict):

    1. Entries in the bundled ``_data/manifest.json`` — authoritative.
    2. Explicitly registered modules (:func:`register_module`) — additive.
    3. ``resolvekit.modules`` entry points — additive, for third-party packs.
    """
    available: dict[str, Path] = {}

    for module_id, path in _iter_manifest_modules():
        if module_id in available:
            continue
        if _is_valid_module_dir(path, expected_module_id=module_id):
            available[module_id] = path

    for module_id, path in _registered.items():
        if module_id in available:
            continue
        if _is_valid_module_dir(path, expected_module_id=module_id):
            available[module_id] = path

    for entry_point in _iter_module_entry_points():
        if entry_point.name in available:
            continue
        try:
            path = _load_module_path_from_entry_point(entry_point)
        except Exception as exc:  # pragma: no cover - defensive provider isolation
            logger.warning(
                "Skipping invalid ResolveKit module provider '%s': %s",
                entry_point.name,
                exc,
            )
            continue
        if _is_valid_module_dir(path, expected_module_id=entry_point.name):
            available[entry_point.name] = path

    return available


def _iter_manifest_modules() -> Iterator[tuple[str, Path]]:
    """Yield ``(module_id, path)`` for every module listed in the bundled manifest.

    The manifest lives at ``resolvekit/_data/manifest.json``. Each ``modules``
    entry is expected to have ``module_id`` and ``domain`` fields; the on-disk
    directory is resolved as ``_data/<domain>/<suffix>/`` where
    ``suffix = module_id.split(".", 1)[1].replace(".", "_")``.

    A missing manifest is tolerated (returns nothing). Malformed entries are
    logged and skipped so one bad entry doesn't poison the whole registry.
    """
    for module_id, path, _entry in iter_manifest_entries():
        yield module_id, path


def iter_manifest_entries() -> Iterator[tuple[str, Path, dict[str, Any]]]:
    """Iterate ``(module_id, path, raw_entry)`` tuples from the bundled manifest.

    Backed by a process-lifetime cache (:func:`_load_manifest_entries`) so the
    JSON file is read and validated once, not on every discovery / override /
    metadata call.  Tests that need a fresh read monkeypatch this function
    directly, bypassing the cache.
    """
    yield from _load_manifest_entries()


@lru_cache(maxsize=1)
def _load_manifest_entries() -> tuple[tuple[str, Path, dict[str, Any]], ...]:
    """Parse and validate ``_data/manifest.json`` once per process.

    The manifest is a static artifact shipped inside the wheel; its contents
    do not change at runtime.  Returns an empty tuple on missing or malformed
    manifest.  Individual malformed entries are logged and skipped.
    """
    data_root = _locate_data_root()
    if data_root is None:
        return ()

    manifest_path = data_root / _MANIFEST_FILENAME
    if not manifest_path.is_file():
        return ()

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read ResolveKit manifest %s: %s", manifest_path, exc)
        return ()

    entries = payload.get("modules") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        logger.warning(
            "ResolveKit manifest %s has no 'modules' list; skipping manifest discovery",
            manifest_path,
        )
        return ()

    resolved: list[tuple[str, Path, dict[str, Any]]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            logger.warning("Skipping non-object manifest entry: %r", entry)
            continue
        module_id = entry.get("module_id")
        domain = entry.get("domain")
        if not isinstance(module_id, str) or not module_id:
            logger.warning("Skipping manifest entry without 'module_id': %r", entry)
            continue
        if not isinstance(domain, str) or not domain:
            logger.warning("Skipping manifest entry '%s' without 'domain'", module_id)
            continue

        suffix = module_id_to_suffix(module_id)
        if suffix is None:
            logger.warning(
                "Skipping manifest entry '%s': cannot derive on-disk suffix",
                module_id,
            )
            continue

        resolved.append((module_id, data_root / domain / suffix, entry))

    return tuple(resolved)


def get_manifest_overrides() -> dict[str, dict[str, Any]]:
    """Return per-module field overrides sourced from the bundled manifest.

    The manifest at ``_data/manifest.json`` is authoritative for
    distribution-state fields (``distribution``, ``remote_artifacts``). For
    remote packs, ``checksums`` is also authoritative — the release asset is
    the canonical binary. For bundled packs, ``checksums`` is NOT overridden:
    the on-disk metadata.json was written by the builder together with the
    in-wheel sqlite, so they agree by construction, and taking the manifest's
    checksum would break verification whenever the manifest is a step behind
    a rebuild.

    Returns ``{module_id: {field: value}}``. Absent fields are omitted from
    each module's inner dict. A missing or malformed manifest returns an
    empty dict (not an error).
    """
    overrides: dict[str, dict[str, Any]] = {}
    for module_id, _path, entry in iter_manifest_entries():
        module_overrides: dict[str, Any] = {}
        for field in _MANIFEST_DISTRIBUTION_FIELDS:
            if field in entry:
                module_overrides[field] = entry[field]
        # Checksums only propagate for modules the manifest calls remote.
        if entry.get("distribution") == "remote":
            for field in _MANIFEST_REMOTE_ONLY_FIELDS:
                if field in entry:
                    module_overrides[field] = entry[field]
        if module_overrides:
            overrides[module_id] = module_overrides
    return overrides


def load_module_metadata(
    module_id: str,
    path: Path,
    *,
    overrides: dict[str, dict[str, Any]] | None = None,
) -> DataPackMetadata:
    """Load metadata.json and overlay manifest-sourced overrides.

    The bundled manifest at ``_data/manifest.json`` is authoritative for the
    fields listed in :data:`_MANIFEST_DISTRIBUTION_FIELDS` (``distribution``,
    ``remote_artifacts``) and, for remote packs only, ``checksums``. The
    on-disk ``metadata.json`` may lag the manifest when a pack is
    reclassified to remote distribution.

    Use this helper (not ``DataPackMetadata.from_file``) whenever a caller
    intends to act on distribution state — downloads, cache lookups, the
    ``cache_status`` report.

    Args:
        module_id: Logical module identifier used as the manifest key.
        path: Datapack directory on disk (contains ``metadata.json``).
        overrides: Optional pre-computed manifest overrides. When ``None``
            the manifest is read on every call — pass a cached dict in hot
            paths to amortize the file read.

    Returns:
        A :class:`DataPackMetadata` instance with any manifest-authoritative
        fields already merged in. Structural override values (e.g.
        ``remote_artifacts`` as nested dicts in the manifest) are re-validated
        so they become proper Pydantic submodels rather than raw dicts.
    """
    metadata = DataPackMetadata.from_file(path / "metadata.json")
    effective_overrides = (
        overrides if overrides is not None else get_manifest_overrides()
    )
    override = effective_overrides.get(module_id)
    if override:
        metadata = DataPackMetadata.model_validate(
            {**metadata.model_dump(), **override}
        )
    return metadata


def is_module_remote(module_id: str) -> bool:
    """Return True if *module_id* is a remote-distribution module.

    Consults the manifest first (authoritative). Falls back to the on-disk
    ``metadata.json`` when the manifest is absent or does not list the
    module. Unknown modules return ``False`` (treated as bundled).
    """
    overrides = get_manifest_overrides()
    override = overrides.get(module_id)
    if override and "distribution" in override:
        return bool(override["distribution"] == "remote")

    # Fallback: look up via the live module registry + on-disk metadata
    try:
        available = list_available_modules()
    except Exception:  # pragma: no cover - defensive
        return False
    path = available.get(module_id)
    if path is None:
        return False
    try:
        metadata = DataPackMetadata.from_file(path / "metadata.json")
    except Exception:  # pragma: no cover - defensive
        return False
    return metadata.distribution == "remote"


def get_canonical_manifest_paths() -> dict[str, Path]:
    """Return ``{module_id: canonical_on_disk_path}`` for every manifest entry.

    The path points into the bundled ``src/resolvekit/_data/`` tree.  Callers
    use this to gate manifest-authoritative overrides to packs loaded from
    the canonical location — ad-hoc paths (tmp fixtures, third-party clones)
    keep their on-disk distribution verbatim.
    """
    return {module_id: path for module_id, path, _ in iter_manifest_entries()}


def _locate_data_root() -> Path | None:
    """Return the filesystem path to resolvekit/_data/ if available.

    Uses importlib.resources for compatibility across wheel, editable,
    and source installations. Returns None if the directory can't be
    located or the package isn't importable in this runtime.
    """
    try:
        traversable = resources.files("resolvekit") / "_data"
    except (ModuleNotFoundError, FileNotFoundError):  # pragma: no cover - defensive
        return None

    # Happy path: importlib.resources backed by a real filesystem directory.
    try:
        candidate = Path(str(traversable))
    except TypeError:  # pragma: no cover - zipimport / non-path loader
        return None

    if not candidate.is_dir():
        return None
    return candidate


def _load_module_path_from_entry_point(entry_point: Any) -> Path:
    provider = entry_point.load()
    candidate = provider() if callable(provider) else provider
    if isinstance(candidate, Path):
        return candidate
    if isinstance(candidate, str):
        return Path(candidate)
    raise ModuleRegistryError(
        f"Module provider '{entry_point.name}' returned unsupported value: "
        f"{type(candidate).__name__}"
    )


def _iter_module_entry_points() -> list[Any]:
    entry_points = importlib_metadata.entry_points()
    if hasattr(entry_points, "select"):
        return list(entry_points.select(group=_MODULE_ENTRYPOINT_GROUP))
    return list(entry_points.get(_MODULE_ENTRYPOINT_GROUP, ()))


def _is_valid_module_dir(path: Path, *, expected_module_id: str) -> bool:
    try:
        metadata = DataPackMetadata.from_file(path / "metadata.json")
    except Exception:
        return False
    return metadata.module_id == expected_module_id


def _reset_registrations() -> None:
    """Clear explicit module registrations (for testing)."""
    _registered.clear()


def _reset_manifest_cache() -> None:
    """Clear the cached manifest payload (for testing)."""
    _load_manifest_entries.cache_clear()
