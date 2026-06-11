"""Loader for datapacks with overlay support and base module tracking."""

import logging
from pathlib import Path

from resolvekit.core.datapack import (
    DataPackLoader,
    DataPackMetadata,
    LoadedDataPack,
)
from resolvekit.core.errors import (
    IncompatibleFeatureSchemaError,
    IncompatibleVersionError,
    MissingModuleDependencyError,
)
from resolvekit.core.version import check_version_compatibility

logger = logging.getLogger(__name__)


class LoadedOverlayPack(LoadedDataPack):
    """A loaded datapack that may reference other datapacks as base modules."""

    def __init__(
        self,
        metadata: DataPackMetadata,
        base_path: Path,
        base_modules: dict[str, LoadedDataPack] | None = None,
    ):
        super().__init__(metadata, base_path)
        self._base_modules = dict(base_modules or {})

    @property
    def base_modules(self) -> dict[str, LoadedDataPack]:
        """Return the base module mapping for overlays."""
        return dict(self._base_modules)


class OverlayLoader:
    """Loads datapacks and enforces overlay→base module version constraints."""

    def __init__(self, validate_checksums: bool = True):
        """Initialize the loader.

        Args:
            validate_checksums: Whether to validate artifact checksums
        """
        self._base_loader = DataPackLoader(validate_checksums=validate_checksums)

    def load(
        self,
        path: Path | str,
        base_modules: dict[str, LoadedDataPack] | None = None,
    ) -> LoadedOverlayPack:
        """Load a datapack from a directory.

        Args:
            path: Path to datapack directory
            base_modules: Dict mapping module IDs to loaded base modules

        Returns:
            LoadedOverlayPack instance

        Raises:
            FileNotFoundError: If directory or required files missing
            MissingModuleDependencyError: If overlay's base modules are missing
            IncompatibleVersionError: If major version mismatch with base
            ValueError: If metadata invalid
        """
        path = Path(path)

        meta_path = path / "metadata.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"Metadata not found: {meta_path}")

        metadata = DataPackMetadata.from_file(meta_path)

        if not metadata.is_overlay:
            loaded = self._base_loader.load(path)
            return LoadedOverlayPack(
                metadata=loaded.metadata,
                base_path=path,
                base_modules={},
            )

        base_modules = base_modules or {}
        required_base_module_ids = metadata.base_module_ids or []
        missing = [
            module_id
            for module_id in required_base_module_ids
            if module_id not in base_modules
        ]
        if missing:
            raise MissingModuleDependencyError(metadata.module_id, missing)

        resolved_base_modules = {
            module_id: base_modules[module_id] for module_id in required_base_module_ids
        }
        for base_module in resolved_base_modules.values():
            self._check_version_compatibility(
                base_version=base_module.metadata.entity_schema_version,
                overlay_version=metadata.entity_schema_version,
                overlay_id=metadata.datapack_id,
            )
            self._check_feature_schema_compatibility(
                expected_version=base_module.metadata.feature_schema_version,
                actual_version=metadata.feature_schema_version,
                pack_id=metadata.domain_pack_id,
            )

        loaded = self._base_loader.load(path)

        return LoadedOverlayPack(
            metadata=loaded.metadata,
            base_path=path,
            base_modules=resolved_base_modules,
        )

    def _check_version_compatibility(
        self,
        base_version: str,
        overlay_version: str,
        overlay_id: str,
    ) -> None:
        """Check version compatibility between base and overlay.

        Args:
            base_version: Base pack entity schema version
            overlay_version: Overlay pack entity schema version
            overlay_id: Overlay pack ID (for error messages)

        Raises:
            IncompatibleVersionError: If major version mismatch
        """
        check = check_version_compatibility(base_version, overlay_version)

        if not check.compatible:
            raise IncompatibleVersionError(
                base_version=base_version,
                overlay_version=overlay_version,
                field="entity_schema_version",
            )

        if check.warning:
            logger.warning(
                "Version mismatch for %s: %s (base: %s, overlay: %s)",
                overlay_id,
                check.warning,
                base_version,
                overlay_version,
            )

    def _check_feature_schema_compatibility(
        self,
        expected_version: str,
        actual_version: str,
        pack_id: str,
    ) -> None:
        """Require exact feature schema matches for overlays."""
        if expected_version == actual_version:
            return
        raise IncompatibleFeatureSchemaError(
            pack_id=pack_id,
            datapack_version=actual_version,
            extractor_version=expected_version,
        )
