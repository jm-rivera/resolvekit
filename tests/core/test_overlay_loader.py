"""Tests for OverlayLoader - loads overlays with linking and version checking."""

import json
import sqlite3
from pathlib import Path

import pytest

from resolvekit.core.datapack import NORMALIZER_VERSION


class TestOverlayLoader:
    """Tests for OverlayLoader."""

    def _create_base_module(self, tmp_path: Path, module_id: str = "geo.base") -> Path:
        """Create a minimal base module for testing."""
        pack_dir = tmp_path / module_id
        pack_dir.mkdir()

        metadata = {
            "datapack_id": f"{module_id}-v1",
            "module_id": module_id,
            "domain_pack_id": "geo",
            "entity_schema_version": "1.0.0",
            "feature_schema_version": "geo.features.v1",
            "normalizer_version": NORMALIZER_VERSION,
            "build_timestamp": "2024-01-15T10:00:00Z",
            "pack_type": "base",
            "store_type": "sqlite",
            "store_file": "entities.sqlite",
        }
        (pack_dir / "metadata.json").write_text(json.dumps(metadata))

        db_path = pack_dir / "entities.sqlite"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE entities (entity_id TEXT PRIMARY KEY)")
        conn.close()

        return pack_dir

    def _create_overlay_pack(
        self,
        tmp_path: Path,
        module_id: str = "geo.overlay",
        base_module_id: str = "geo.base",
        entity_schema_version: str = "1.0.0",
    ) -> Path:
        """Create a minimal overlay pack for testing."""
        pack_dir = tmp_path / module_id
        pack_dir.mkdir()

        metadata = {
            "datapack_id": f"{module_id}-v1",
            "module_id": module_id,
            "domain_pack_id": "geo",
            "entity_schema_version": entity_schema_version,
            "feature_schema_version": "geo.features.v1",
            "normalizer_version": NORMALIZER_VERSION,
            "build_timestamp": "2024-01-15T12:00:00Z",
            "pack_type": "overlay",
            "base_module_ids": [base_module_id],
            "link_keys": ["dcid", "iso3"],
            "store_type": "sqlite",
            "store_file": "entities.sqlite",
        }
        (pack_dir / "metadata.json").write_text(json.dumps(metadata))

        db_path = pack_dir / "entities.sqlite"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE entities (entity_id TEXT PRIMARY KEY)")
        conn.close()

        return pack_dir

    def test_load_base_module(self, tmp_path):
        """OverlayLoader loads a base pack."""
        from resolvekit.core.overlay_loader import OverlayLoader

        base_dir = self._create_base_module(tmp_path)

        loader = OverlayLoader()
        loaded = loader.load(base_dir)

        assert loaded.metadata.pack_type == "base"
        assert loaded.metadata.module_id == "geo.base"

    def test_load_overlay_validates_base_exists(self, tmp_path):
        """OverlayLoader raises if overlay's base pack not found."""
        from resolvekit.core import MissingModuleDependencyError
        from resolvekit.core.overlay_loader import OverlayLoader

        overlay_dir = self._create_overlay_pack(tmp_path, base_module_id="geo.missing")

        loader = OverlayLoader()

        with pytest.raises(MissingModuleDependencyError) as exc:
            loader.load(overlay_dir, base_modules={})

        # Check that error mentions the overlay ID
        assert "geo.overlay" in str(exc.value)

    def test_load_overlay_with_base_module(self, tmp_path):
        """OverlayLoader loads overlay when a base module is provided."""
        from resolvekit.core.overlay_loader import OverlayLoader

        base_dir = self._create_base_module(tmp_path)
        overlay_dir = self._create_overlay_pack(tmp_path)

        loader = OverlayLoader()
        base_loaded = loader.load(base_dir)

        overlay_loaded = loader.load(
            overlay_dir,
            base_modules={"geo.base": base_loaded},
        )

        assert overlay_loaded.metadata.pack_type == "overlay"
        assert overlay_loaded.metadata.base_module_ids == ["geo.base"]

    def test_load_overlay_version_mismatch_major_raises(self, tmp_path):
        """OverlayLoader raises on major version mismatch."""
        from resolvekit.core import IncompatibleVersionError
        from resolvekit.core.overlay_loader import OverlayLoader

        base_dir = self._create_base_module(tmp_path)
        overlay_dir = self._create_overlay_pack(
            tmp_path,
            entity_schema_version="2.0.0",  # Major mismatch
        )

        loader = OverlayLoader()
        base_loaded = loader.load(base_dir)

        with pytest.raises(IncompatibleVersionError) as exc:
            loader.load(
                overlay_dir,
                base_modules={"geo.base": base_loaded},
            )

        assert "2.0.0" in str(exc.value)
        assert "1.0.0" in str(exc.value)

    def test_load_overlay_version_mismatch_minor_warns(self, tmp_path, caplog):
        """OverlayLoader warns on minor version mismatch."""
        import logging

        from resolvekit.core.overlay_loader import OverlayLoader

        base_dir = self._create_base_module(tmp_path)
        overlay_dir = self._create_overlay_pack(
            tmp_path,
            entity_schema_version="1.1.0",  # Minor mismatch
        )

        loader = OverlayLoader()
        base_loaded = loader.load(base_dir)

        with caplog.at_level(logging.WARNING):
            overlay_loaded = loader.load(
                overlay_dir,
                base_modules={"geo.base": base_loaded},
            )

        # Should still load but warn
        assert overlay_loaded is not None
        assert "1.1.0" in caplog.text or "minor" in caplog.text.lower()

    def test_load_overlay_same_version_no_warning(self, tmp_path, caplog):
        """OverlayLoader doesn't warn when versions match."""
        import logging

        from resolvekit.core.overlay_loader import OverlayLoader

        base_dir = self._create_base_module(tmp_path)
        overlay_dir = self._create_overlay_pack(tmp_path, entity_schema_version="1.0.0")

        loader = OverlayLoader()
        base_loaded = loader.load(base_dir)

        with caplog.at_level(logging.WARNING):
            loader.load(
                overlay_dir,
                base_modules={"geo.base": base_loaded},
            )

        # No version warnings
        assert "version" not in caplog.text.lower()

    def test_load_base_pack_skips_version_check(self, tmp_path):
        """OverlayLoader skips version check for base packs."""
        from resolvekit.core.overlay_loader import OverlayLoader

        base_dir = self._create_base_module(tmp_path)

        loader = OverlayLoader()
        # Should not raise even without base_modules
        loaded = loader.load(base_dir)

        assert loaded.metadata.pack_type == "base"

    def test_load_overlay_stores_base_reference(self, tmp_path):
        """OverlayLoader includes base reference in loaded overlay."""
        from resolvekit.core.overlay_loader import OverlayLoader

        base_dir = self._create_base_module(tmp_path)
        overlay_dir = self._create_overlay_pack(tmp_path)

        loader = OverlayLoader()
        base_loaded = loader.load(base_dir)

        overlay_loaded = loader.load(
            overlay_dir,
            base_modules={"geo.base": base_loaded},
        )

        assert overlay_loaded.base_modules["geo.base"].metadata.module_id == "geo.base"

    def test_load_overlay_feature_schema_mismatch_raises(self, tmp_path):
        """OverlayLoader requires exact feature schema matches."""
        from resolvekit.core import IncompatibleFeatureSchemaError
        from resolvekit.core.overlay_loader import OverlayLoader

        base_dir = self._create_base_module(tmp_path)
        overlay_dir = self._create_overlay_pack(tmp_path)

        overlay_metadata = json.loads((overlay_dir / "metadata.json").read_text())
        overlay_metadata["feature_schema_version"] = "geo.features.v2"
        (overlay_dir / "metadata.json").write_text(json.dumps(overlay_metadata))

        loader = OverlayLoader()
        base_loaded = loader.load(base_dir)

        with pytest.raises(IncompatibleFeatureSchemaError):
            loader.load(
                overlay_dir,
                base_modules={"geo.base": base_loaded},
            )
