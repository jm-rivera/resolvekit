"""GenericDataPackBuilder — BaseDataPackBuilder subclass for domain="custom"."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from resolvekit.shared.build.base_builder import BaseDataPackBuilder


class GenericDataPackBuilder(BaseDataPackBuilder):
    """Builds custom-domain DataPack artifacts.

    Extends ``BaseDataPackBuilder`` for the ``"custom"`` domain:

    - ``DOMAIN_PACK_ID = "custom"``
    - ``FEATURE_SCHEMA_VERSION = "custom.features.v1"``

    ``set_base_modules`` wires ``BaseLinker`` + ``_CustomBuildNormalizer`` so
    that build-time and query-time normalization agree for custom packs (both
    use NFC + casefold, not NFKC).
    """

    DOMAIN_PACK_ID = "custom"
    FEATURE_SCHEMA_VERSION = "custom.features.v1"

    def set_base_modules(self, base_paths: Sequence[str | Path]) -> None:
        """Set base modules for build-time entity linking.

        Args:
            base_paths: Paths to datapack directories in the base composition.
        """
        from resolvekit.core.byod.build import _CustomBuildNormalizer
        from resolvekit.core.linking.base_linker import BaseLinker

        self._open_base_stores(base_paths)
        self._linker = BaseLinker()
        self._normalizer = _CustomBuildNormalizer()
