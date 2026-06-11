"""Tests for geo DataPack builder."""

import json
import sqlite3

import pytest


class TestGeoDataPackBuilder:
    """Tests for builder geo datapacks."""

    def test_builds_metadata(self, tmp_path):
        from resolvekit.packs.geo.build.builder import GeoDataPackBuilder

        builder = GeoDataPackBuilder(output_dir=tmp_path)
        metadata = builder.build_metadata(
            datapack_id="geo_test_v1",
            source_datasets=["test_data"],
        )

        assert metadata["datapack_id"] == "geo_test_v1"
        assert metadata["domain_pack_id"] == "geo"
        assert metadata["feature_schema_version"] == "geo.features.v1"

        # Verify file was written
        metadata_path = tmp_path / "metadata.json"
        assert metadata_path.exists()

        with open(metadata_path) as f:
            written = json.load(f)
        assert written["datapack_id"] == "geo_test_v1"

    def test_creates_sqlite_schema(self, tmp_path):
        from resolvekit.packs.geo.build.builder import GeoDataPackBuilder

        builder = GeoDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        # Verify file was created
        assert db_path.exists()

        # Verify schema
        conn = sqlite3.connect(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t[0] for t in tables}

        assert "entities" in table_names
        assert "names" in table_names
        assert "codes" in table_names
        assert "relations" in table_names
        assert "names_fts" in table_names

        conn.close()

    def test_creates_indexes(self, tmp_path):
        from resolvekit.packs.geo.build.builder import GeoDataPackBuilder

        builder = GeoDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        conn = sqlite3.connect(db_path)
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        index_names = {i[0] for i in indexes}

        assert "idx_codes_lookup" in index_names
        assert "idx_names_lookup" in index_names

        conn.close()

    def test_add_entity(self, tmp_path):
        from resolvekit.packs.geo.build.builder import GeoDataPackBuilder

        builder = GeoDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        # Add an entity
        builder.add_entity(
            entity_id="country/USA",
            entity_type="geo.country",
            canonical_name="United States of America",
            canonical_name_norm="united states of america",
        )
        builder.close()

        # Verify
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT * FROM entities WHERE entity_id = ?", ("country/USA",)
        ).fetchone()

        assert row is not None
        assert row[0] == "country/USA"
        assert row[1] == "geo.country"

        conn.close()

    def test_add_name(self, tmp_path):
        from resolvekit.packs.geo.build.builder import GeoDataPackBuilder

        builder = GeoDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        builder.add_entity(
            entity_id="country/USA",
            entity_type="geo.country",
            canonical_name="United States of America",
            canonical_name_norm="united states of america",
        )

        builder.add_name(
            entity_id="country/USA",
            name_kind="alias",
            value="USA",
            value_norm="usa",
            lang="en",
        )
        builder.close()

        # Verify
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT * FROM names WHERE entity_id = ? AND name_kind = ?",
            ("country/USA", "alias"),
        ).fetchone()

        assert row is not None
        assert row[2] == "USA"

        conn.close()

    def test_add_code(self, tmp_path):
        from resolvekit.packs.geo.build.builder import GeoDataPackBuilder

        builder = GeoDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        builder.add_entity(
            entity_id="country/USA",
            entity_type="geo.country",
            canonical_name="United States of America",
            canonical_name_norm="united states of america",
        )

        builder.add_code(
            entity_id="country/USA",
            system="iso2",
            value="US",
            value_norm="us",
        )
        builder.close()

        # Verify
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT * FROM codes WHERE entity_id = ? AND system = ?",
            ("country/USA", "iso2"),
        ).fetchone()

        assert row is not None
        assert row[2] == "US"

        conn.close()

    def test_finalize_builds_fts(self, tmp_path):
        from resolvekit.packs.geo.build.builder import GeoDataPackBuilder

        builder = GeoDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        builder.add_entity(
            entity_id="country/USA",
            entity_type="geo.country",
            canonical_name="United States of America",
            canonical_name_norm="united states of america",
        )

        builder.add_name(
            entity_id="country/USA",
            name_kind="canonical",
            value="United States of America",
            value_norm="united states of america",
            lang="en",
        )

        builder.finalize()
        builder.close()

        # Verify FTS index has data
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT * FROM names_fts WHERE names_fts MATCH ?",
            ("united",),
        ).fetchone()

        assert row is not None

        conn.close()


class TestGeoOverlayMetadata:
    """Tests for geo build_overlay_metadata."""

    def test_builds_overlay_metadata_with_geo_defaults(self, tmp_path):
        from resolvekit.packs.geo.build.builder import GeoDataPackBuilder

        builder = GeoDataPackBuilder(output_dir=tmp_path)
        metadata = builder.build_overlay_metadata(
            datapack_id="geo_overlay_v1",
            base_module_ids=["geo.base"],
            source_datasets=["custom_data"],
            link_keys=["iso3"],
        )

        assert metadata["datapack_id"] == "geo_overlay_v1"
        assert metadata["domain_pack_id"] == "geo"
        assert metadata["feature_schema_version"] == "geo.features.v1"
        assert metadata["pack_type"] == "overlay"
        assert metadata["base_module_ids"] == ["geo.base"]
        assert metadata["link_keys"] == ["iso3"]
        assert metadata["allow_new_entities"] is False

    def test_overlay_metadata_writes_to_file(self, tmp_path):
        from resolvekit.packs.geo.build.builder import GeoDataPackBuilder

        builder = GeoDataPackBuilder(output_dir=tmp_path)
        builder.build_overlay_metadata(
            datapack_id="geo_overlay_v1",
            base_module_ids=["geo.base"],
            source_datasets=["custom_data"],
            link_keys=["iso3"],
        )

        metadata_path = tmp_path / "metadata.json"
        assert metadata_path.exists()

        with open(metadata_path) as f:
            written = json.load(f)

        assert written["pack_type"] == "overlay"
        assert written["base_module_ids"] == ["geo.base"]

    def test_overlay_metadata_rejects_empty_base_id(self, tmp_path):
        from resolvekit.packs.geo.build.builder import GeoDataPackBuilder

        builder = GeoDataPackBuilder(output_dir=tmp_path)

        with pytest.raises(ValueError, match="base_module_ids must not be empty"):
            builder.build_overlay_metadata(
                datapack_id="geo_overlay_v1",
                base_module_ids=[],
                source_datasets=["custom_data"],
                link_keys=["iso3"],
            )


class TestGeoSetBaseModules:
    """Tests for geo set_base_modules and link_and_add."""

    def _create_base_module(self, base_dir):
        """Create a geo base pack with test entities."""
        from resolvekit.packs.geo.build.builder import GeoDataPackBuilder

        base_dir.mkdir(parents=True, exist_ok=True)
        with GeoDataPackBuilder(output_dir=base_dir) as builder:
            builder.create_database()
            builder.add_entity(
                entity_id="geo/FRA",
                entity_type="geo.country",
                canonical_name="France",
                canonical_name_norm="france",
                attrs={"population": 65000000},
            )
            builder.add_code(
                entity_id="geo/FRA",
                system="iso3",
                value="FRA",
                value_norm="fra",
            )
            builder.add_entity(
                entity_id="geo/DEU",
                entity_type="geo.country",
                canonical_name="Germany",
                canonical_name_norm="germany",
            )
            builder.add_code(
                entity_id="geo/DEU",
                system="iso3",
                value="DEU",
                value_norm="deu",
            )
            builder.finalize()

    def test_link_and_add_end_to_end(self, tmp_path):
        """Full workflow: create base, link overlay, build metadata."""
        from resolvekit.packs.geo.build.builder import GeoDataPackBuilder

        base_dir = tmp_path / "base"
        self._create_base_module(base_dir)

        overlay_dir = tmp_path / "overlay"
        with GeoDataPackBuilder(output_dir=overlay_dir) as builder:
            builder.create_database()
            builder.set_base_modules([base_dir])

            result_fra = builder.link_and_add(
                codes={"iso3": "FRA"},
                canonical_name="French Republic",
                attrs={"gdp_usd": 2700000000000},
            )

            result_deu = builder.link_and_add(
                codes={"iso3": "DEU"},
                attrs={"gdp_usd": 4200000000000},
            )

            builder.finalize()
            builder.build_overlay_metadata(
                datapack_id="geo_enrichment_v1",
                base_module_ids=["geo.base"],
                source_datasets=["custom_data"],
                link_keys=["iso3"],
            )

        assert result_fra.is_success
        assert result_fra.entity_id == "geo/FRA"
        assert result_deu.is_success
        assert result_deu.entity_id == "geo/DEU"

        # Verify overlay database
        conn = sqlite3.connect(overlay_dir / "entities.sqlite")
        rows = conn.execute(
            "SELECT entity_id FROM entities ORDER BY entity_id"
        ).fetchall()
        conn.close()
        assert len(rows) == 2
        assert rows[0][0] == "geo/DEU"
        assert rows[1][0] == "geo/FRA"

        # Verify metadata
        with open(overlay_dir / "metadata.json") as f:
            metadata = json.load(f)
        assert metadata["pack_type"] == "overlay"
        assert metadata["base_module_ids"] == ["geo.base"]

    def test_context_manager_cleans_up_base_store(self, tmp_path):
        from resolvekit.packs.geo.build.builder import GeoDataPackBuilder

        base_dir = tmp_path / "base"
        self._create_base_module(base_dir)

        overlay_dir = tmp_path / "overlay"
        builder = GeoDataPackBuilder(output_dir=overlay_dir)
        builder.create_database()
        builder.set_base_modules([base_dir])
        assert builder._base_store is not None

        builder.close()
        assert builder._base_store is None
