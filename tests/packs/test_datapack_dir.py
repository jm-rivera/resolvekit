"""Tests for DATAPACK_DIR on domain packs."""

from pathlib import Path

from resolvekit.packs.geo.pack import GeoPack
from resolvekit.packs.org.pack import OrgPack


class TestGeoPackDatapackDir:
    """Tests for GeoPack.DATAPACK_DIR."""

    def test_is_path(self):
        """DATAPACK_DIR is a Path instance."""
        assert isinstance(GeoPack.DATAPACK_DIR, Path)

    def test_points_to_data_dir(self):
        """DATAPACK_DIR points to the data/ subdirectory."""
        assert GeoPack.DATAPACK_DIR.name == "data"
        assert GeoPack.DATAPACK_DIR.parent.name == "geo"

    def test_directory_exists(self):
        """The data directory exists on disk."""
        assert GeoPack.DATAPACK_DIR.is_dir()


class TestOrgPackDatapackDir:
    """Tests for OrgPack.DATAPACK_DIR."""

    def test_is_path(self):
        """DATAPACK_DIR is a Path instance."""
        assert isinstance(OrgPack.DATAPACK_DIR, Path)

    def test_points_to_data_dir(self):
        """DATAPACK_DIR points to the data/ subdirectory."""
        assert OrgPack.DATAPACK_DIR.name == "data"
        assert OrgPack.DATAPACK_DIR.parent.name == "org"

    def test_directory_exists(self):
        """The data directory exists on disk."""
        assert OrgPack.DATAPACK_DIR.is_dir()
