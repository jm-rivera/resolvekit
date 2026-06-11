"""Builder for geo DataPacks."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from resolvekit.shared.build import BaseDataPackBuilder


class GeoDataPackBuilder(BaseDataPackBuilder):
    """Builds geo DataPack artifacts.

    Extends BaseDataPackBuilder with geo-specific defaults:
    - domain_pack_id = "geo"
    - feature_schema_version = "geo.features.v1"
    """

    DOMAIN_PACK_ID = "geo"
    FEATURE_SCHEMA_VERSION = "geo.features.v1"

    def set_base_modules(self, base_paths: Sequence[str | Path]) -> None:
        """Set base modules for build-time entity linking.

        Args:
            base_paths: Paths to datapack directories in the base composition.
        """
        from resolvekit.packs.geo.linker import GeoLinker
        from resolvekit.packs.geo.normalizer import GeoNormalizer

        self._open_base_stores(base_paths)
        self._linker = GeoLinker()
        self._normalizer = GeoNormalizer()
