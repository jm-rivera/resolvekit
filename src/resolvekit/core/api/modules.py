"""Catalog discovery surface — what modules ship with resolvekit."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from resolvekit.core import module_registry
from resolvekit.core.config import get_cache_dir
from resolvekit.core.remote import is_cached

__all__ = ["ModuleInfo", "modules"]


class ModuleInfo(BaseModel):
    """Catalog metadata for one installed module.

    Returned by :func:`resolvekit.modules`. Includes both identity metadata
    and cache state so callers need not call a separate ``cache_status()``
    function.
    """

    model_config = ConfigDict(frozen=True)

    module_id: str
    domain: str
    entity_types: tuple[str, ...]
    distribution: Literal["bundled", "remote"]
    size_mb: float | None = Field(
        default=None,
        description=(
            "Uncompressed on-disk size in MB; None when the module "
            "is remote and not yet downloaded."
        ),
    )
    download_size_mb: float | None = Field(
        default=None,
        description=(
            "Compressed wire size in MB for remote modules; None for bundled modules."
        ),
    )
    is_available: bool = Field(
        description=(
            "True when the module's data is usable now without "
            "triggering a download (always True for bundled "
            "modules; True for remote modules whose data is on "
            "disk)."
        ),
    )
    remote_url: str | None
    data_version: str | None = Field(
        default=None,
        description=(
            "Per-module CalVer (e.g. '2026.04'). Differs from "
            "Resolver.info()['data_version'], which aggregates "
            "across all loaded modules into a single string."
        ),
    )
    cache_path: Path | None = Field(
        default=None,
        description=(
            "On-disk cache path for remote modules when the data is "
            "present locally; None for bundled modules or uncached remote modules."
        ),
    )


def modules() -> list[ModuleInfo]:
    """List every module installed in this resolvekit installation.

    Returns the full catalog: bundled modules (always available) plus
    remote modules (``is_available=True`` only when their data is on
    disk). Reads the manifest and on-disk cache state — never the
    network.

    Returns:
        List of :class:`ModuleInfo`, sorted by ``module_id``.
    """
    overrides = module_registry.get_manifest_overrides()
    result: list[ModuleInfo] = []

    for module_id, path, raw_entry in module_registry.iter_manifest_entries():
        metadata = module_registry.load_module_metadata(
            module_id, path, overrides=overrides
        )
        if metadata.distribution == "bundled":
            is_available = True
            cache_path: Path | None = None
        else:
            is_available = is_cached(metadata)
            cache_path = (
                (get_cache_dir() / metadata.module_id) if is_available else None
            )

        result.append(
            ModuleInfo(
                module_id=metadata.module_id,
                domain=metadata.domain_pack_id,
                entity_types=tuple(raw_entry.get("entity_types", ())),
                distribution=metadata.distribution,
                size_mb=raw_entry.get("size_mb"),
                download_size_mb=metadata.download_size_mb,
                is_available=is_available,
                remote_url=metadata.remote_url,
                data_version=metadata.data_version,
                cache_path=cache_path,
            )
        )

    return sorted(result, key=lambda m: m.module_id)
