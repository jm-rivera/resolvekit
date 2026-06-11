"""Tests for BaseDataPackBuilder."""

import json
import sqlite3

import pytest


class TestBaseDataPackBuilderInit:
    """Tests for BaseDataPackBuilder initialization."""

    def test_init_creates_output_directory(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        output_dir = tmp_path / "new_dir"
        BaseDataPackBuilder(output_dir=output_dir)

        assert output_dir.exists()


class TestCreateDatabase:
    """Tests for create_database method."""

    def test_create_database_returns_path(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        assert db_path.exists()
        assert db_path.name == "test.db"

    def test_create_database_creates_tables(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

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

    def test_create_database_creates_indexes(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        conn = sqlite3.connect(db_path)
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        index_names = {i[0] for i in indexes}

        assert "idx_codes_lookup" in index_names
        assert "idx_names_lookup" in index_names

        conn.close()


class TestAddEntity:
    """Tests for add_entity method."""

    def test_add_entity_without_database_raises(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)

        with pytest.raises(RuntimeError, match="Database not created"):
            builder.add_entity(
                entity_id="org/test",
                entity_type="org.company",
                canonical_name="Test Corp",
                canonical_name_norm="test corp",
            )

    def test_add_entity_inserts_row(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        builder.add_entity(
            entity_id="org/test",
            entity_type="org.company",
            canonical_name="Test Corp",
            canonical_name_norm="test corp",
        )
        builder.close()

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT * FROM entities WHERE entity_id = ?", ("org/test",)
        ).fetchone()

        assert row is not None
        assert row[0] == "org/test"
        assert row[1] == "org.company"
        assert row[2] == "Test Corp"
        assert row[3] == "test corp"

        conn.close()

    def test_add_entity_with_attrs(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        builder.add_entity(
            entity_id="org/test",
            entity_type="org.company",
            canonical_name="Test Corp",
            canonical_name_norm="test corp",
            attrs={"country": "US", "industry": "tech"},
        )
        builder.close()

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT attrs_json FROM entities WHERE entity_id = ?", ("org/test",)
        ).fetchone()

        attrs = json.loads(row[0])
        assert attrs["country"] == "US"
        assert attrs["industry"] == "tech"

        conn.close()


class TestAddName:
    """Tests for add_name method."""

    def test_add_name_without_database_raises(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)

        with pytest.raises(RuntimeError, match="Database not created"):
            builder.add_name(
                entity_id="org/test",
                name_kind="alias",
                value="Test",
                value_norm="test",
            )

    def test_add_name_rejects_missing_entity(self, tmp_path):
        """Foreign key enforcement should reject names for non-existent entities."""
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)
        builder.create_database("test.db")

        # Don't add the entity first - FK should reject this
        with pytest.raises(sqlite3.IntegrityError):
            builder.add_name(
                entity_id="org/nonexistent",
                name_kind="alias",
                value="Test",
                value_norm="test",
            )

    def test_add_name_inserts_row(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        builder.add_entity(
            entity_id="org/test",
            entity_type="org.company",
            canonical_name="Test Corp",
            canonical_name_norm="test corp",
        )

        builder.add_name(
            entity_id="org/test",
            name_kind="alias",
            value="TC",
            value_norm="tc",
            lang="en",
        )
        builder.close()

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT * FROM names WHERE entity_id = ? AND name_kind = ?",
            ("org/test", "alias"),
        ).fetchone()

        assert row is not None
        assert row[2] == "TC"
        assert row[3] == "tc"
        assert row[4] == "en"

        conn.close()


class TestAddCode:
    """Tests for add_code method."""

    def test_add_code_without_database_raises(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)

        with pytest.raises(RuntimeError, match="Database not created"):
            builder.add_code(
                entity_id="org/test",
                system="lei",
                value="123456",
                value_norm="123456",
            )

    def test_add_code_inserts_row(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        builder.add_entity(
            entity_id="org/test",
            entity_type="org.company",
            canonical_name="Test Corp",
            canonical_name_norm="test corp",
        )

        builder.add_code(
            entity_id="org/test",
            system="lei",
            value="ABC123",
            value_norm="abc123",
        )
        builder.close()

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT * FROM codes WHERE entity_id = ? AND system = ?",
            ("org/test", "lei"),
        ).fetchone()

        assert row is not None
        assert row[2] == "ABC123"
        assert row[3] == "abc123"

        conn.close()

    def test_add_code_replaces_duplicate(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        builder.add_entity(
            entity_id="org/test",
            entity_type="org.company",
            canonical_name="Test Corp",
            canonical_name_norm="test corp",
        )

        builder.add_code(
            entity_id="org/test",
            system="lei",
            value="OLD123",
            value_norm="old123",
        )

        builder.add_code(
            entity_id="org/test",
            system="lei",
            value="NEW456",
            value_norm="new456",
        )
        builder.close()

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT * FROM codes WHERE entity_id = ? AND system = ?",
            ("org/test", "lei"),
        ).fetchall()

        assert len(rows) == 1
        assert rows[0][2] == "NEW456"

        conn.close()


class TestAddRelation:
    """Tests for add_relation method."""

    def test_add_relation_without_database_raises(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)

        with pytest.raises(RuntimeError, match="Database not created"):
            builder.add_relation(
                entity_id="org/child",
                relation_type="parent_org",
                target_id="org/parent",
            )

    def test_add_relation_inserts_row(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        builder.add_entity(
            entity_id="org/parent",
            entity_type="org.company",
            canonical_name="Parent Corp",
            canonical_name_norm="parent corp",
        )

        builder.add_entity(
            entity_id="org/child",
            entity_type="org.company",
            canonical_name="Child Corp",
            canonical_name_norm="child corp",
        )

        builder.add_relation(
            entity_id="org/child",
            relation_type="parent_org",
            target_id="org/parent",
        )
        builder.close()

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT * FROM relations WHERE entity_id = ? AND relation_type = ?",
            ("org/child", "parent_org"),
        ).fetchone()

        assert row is not None
        assert row[2] == "org/parent"

        conn.close()


class TestFinalize:
    """Tests for finalize method."""

    def test_finalize_without_database_raises(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)

        with pytest.raises(RuntimeError, match="Database not created"):
            builder.finalize()

    def test_finalize_rebuilds_fts(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        builder.add_entity(
            entity_id="org/test",
            entity_type="org.company",
            canonical_name="Test Corporation",
            canonical_name_norm="test corporation",
        )

        builder.add_name(
            entity_id="org/test",
            name_kind="alias",
            value="TestCorp",
            value_norm="testcorp",
            lang="en",
        )

        builder.finalize()
        builder.close()

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT * FROM names_fts WHERE names_fts MATCH ?",
            ("test",),
        ).fetchone()

        assert row is not None

        conn.close()

    def test_add_entity_inserts_canonical_name_into_names_table(self, tmp_path):
        """Canonical names should be searchable without explicit add_name call."""
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        # Only call add_entity, NOT add_name
        builder.add_entity(
            entity_id="org/acme",
            entity_type="org.company",
            canonical_name="Acme Corporation",
            canonical_name_norm="acme corporation",
        )

        builder.finalize()
        builder.close()

        conn = sqlite3.connect(db_path)

        # Verify canonical name is in names table
        row = conn.execute(
            "SELECT name_kind, value, is_preferred FROM names WHERE entity_id = ?",
            ("org/acme",),
        ).fetchone()
        assert row is not None
        assert row[0] == "canonical"
        assert row[1] == "Acme Corporation"
        assert row[2] == 1  # is_preferred

        # Verify canonical name is searchable via FTS
        fts_row = conn.execute(
            "SELECT entity_id FROM names_fts WHERE names_fts MATCH ?",
            ("acme",),
        ).fetchone()
        assert fts_row is not None
        assert fts_row[0] == "org/acme"

        conn.close()


class TestBuildMetadata:
    """Tests for build_metadata method."""

    def test_build_metadata_returns_dict(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)
        metadata = builder.build_metadata(
            datapack_id="test_pack_v1",
            domain_pack_id="org",
            source_datasets=["test_data"],
        )

        assert metadata["datapack_id"] == "test_pack_v1"
        assert metadata["domain_pack_id"] == "org"
        assert "build_timestamp" in metadata
        assert metadata["source_datasets"] == ["test_data"]
        assert metadata["pack_type"] == "base"  # A2 baseline pin

    def test_build_metadata_writes_file(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)
        builder.build_metadata(
            datapack_id="test_pack_v1",
            domain_pack_id="org",
            source_datasets=["test_data"],
        )

        metadata_path = tmp_path / "metadata.json"
        assert metadata_path.exists()

        with open(metadata_path) as f:
            written = json.load(f)

        assert written["datapack_id"] == "test_pack_v1"
        assert written["domain_pack_id"] == "org"


class TestBuildOverlayMetadata:
    """Tests for build_overlay_metadata method."""

    def test_build_overlay_metadata_returns_dict(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)
        metadata = builder.build_overlay_metadata(
            datapack_id="overlay_v1",
            domain_pack_id="geo",
            base_module_ids=["geo.base"],
            source_datasets=["custom_data"],
            link_keys=["iso3"],
        )

        assert metadata["datapack_id"] == "overlay_v1"
        assert metadata["domain_pack_id"] == "geo"
        assert metadata["pack_type"] == "overlay"
        assert metadata["base_module_ids"] == ["geo.base"]
        assert metadata["allow_new_entities"] is False
        assert metadata["link_keys"] == ["iso3"]
        assert "build_timestamp" in metadata
        assert metadata["source_datasets"] == ["custom_data"]

    def test_build_overlay_metadata_writes_file(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)
        builder.build_overlay_metadata(
            datapack_id="overlay_v1",
            domain_pack_id="geo",
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
        assert written["link_keys"] == ["iso3"]

    def test_build_overlay_metadata_rejects_empty_base_id(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)

        with pytest.raises(ValueError, match="base_module_ids must not be empty"):
            builder.build_overlay_metadata(
                datapack_id="overlay_v1",
                domain_pack_id="geo",
                base_module_ids=[],
                source_datasets=["custom_data"],
                link_keys=["iso3"],
            )

    def test_build_overlay_metadata_allow_new_entities(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)
        metadata = builder.build_overlay_metadata(
            datapack_id="overlay_v1",
            domain_pack_id="geo",
            base_module_ids=["geo.base"],
            source_datasets=["custom_data"],
            link_keys=["iso3"],
            allow_new_entities=True,
        )

        assert metadata["allow_new_entities"] is True

    def test_build_overlay_metadata_multiple_link_keys(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)
        metadata = builder.build_overlay_metadata(
            datapack_id="overlay_v1",
            domain_pack_id="geo",
            base_module_ids=["geo.base"],
            source_datasets=["custom_data"],
            link_keys=["iso3", "iso2", "dcid"],
        )

        assert metadata["link_keys"] == ["iso3", "iso2", "dcid"]


class TestLinkAndAdd:
    """Tests for link_and_add method."""

    def _create_base_module(self, base_dir):
        """Create a base pack with test entities for linking."""
        from resolvekit.shared import BaseDataPackBuilder

        base_dir.mkdir(parents=True, exist_ok=True)
        with BaseDataPackBuilder(output_dir=base_dir) as builder:
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
            builder.add_code(
                entity_id="geo/FRA",
                system="iso2",
                value="FR",
                value_norm="fr",
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

    def test_link_and_add_without_base_modules_raises(self, tmp_path):
        from resolvekit.packs.geo.build.builder import GeoDataPackBuilder

        builder = GeoDataPackBuilder(output_dir=tmp_path / "overlay")
        builder.create_database()

        with pytest.raises(RuntimeError, match="Base modules not set"):
            builder.link_and_add(codes={"iso3": "FRA"})

        builder.close()

    def test_link_and_add_resolves_entity(self, tmp_path):
        from resolvekit.packs.geo.build.builder import GeoDataPackBuilder

        base_dir = tmp_path / "base"
        self._create_base_module(base_dir)

        overlay_dir = tmp_path / "overlay"
        with GeoDataPackBuilder(output_dir=overlay_dir) as builder:
            builder.create_database()
            builder.set_base_modules([base_dir])

            result = builder.link_and_add(
                codes={"iso3": "FRA"},
                attrs={"gdp_usd": 2700000000000},
            )
            builder.finalize()

        assert result.is_success
        assert result.entity_id == "geo/FRA"

        # Verify entity was written to overlay database
        import sqlite3

        conn = sqlite3.connect(overlay_dir / "entities.sqlite")
        row = conn.execute(
            "SELECT entity_id, canonical_name, attrs_json FROM entities WHERE entity_id = ?",
            ("geo/FRA",),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "geo/FRA"
        assert row[1] == "France"  # Fetched from base
        assert json.loads(row[2])["gdp_usd"] == 2700000000000

    def test_link_and_add_with_canonical_name_override(self, tmp_path):
        from resolvekit.packs.geo.build.builder import GeoDataPackBuilder

        base_dir = tmp_path / "base"
        self._create_base_module(base_dir)

        overlay_dir = tmp_path / "overlay"
        with GeoDataPackBuilder(output_dir=overlay_dir) as builder:
            builder.create_database()
            builder.set_base_modules([base_dir])

            result = builder.link_and_add(
                codes={"iso3": "FRA"},
                canonical_name="French Republic",
            )
            builder.finalize()

        assert result.is_success

        import sqlite3

        conn = sqlite3.connect(overlay_dir / "entities.sqlite")
        row = conn.execute(
            "SELECT canonical_name, canonical_name_norm FROM entities WHERE entity_id = ?",
            ("geo/FRA",),
        ).fetchone()
        conn.close()

        assert row[0] == "French Republic"
        assert row[1] == "french republic"

    def test_link_and_add_not_found(self, tmp_path):
        from resolvekit.packs.geo.build.builder import GeoDataPackBuilder

        base_dir = tmp_path / "base"
        self._create_base_module(base_dir)

        overlay_dir = tmp_path / "overlay"
        with GeoDataPackBuilder(output_dir=overlay_dir) as builder:
            builder.create_database()
            builder.set_base_modules([base_dir])

            result = builder.link_and_add(
                codes={"iso3": "ZZZ"},
                canonical_name="Nonexistent",
                entity_type="geo.country",
            )
            builder.finalize()

        assert not result.is_success
        assert result.status == "not_found"

        # Verify no entity was written
        import sqlite3

        conn = sqlite3.connect(overlay_dir / "entities.sqlite")
        rows = conn.execute("SELECT COUNT(*) FROM entities").fetchone()
        conn.close()
        assert rows[0] == 0

    def test_link_and_add_with_additional_names(self, tmp_path):
        from resolvekit.packs.geo.build.builder import GeoDataPackBuilder

        base_dir = tmp_path / "base"
        self._create_base_module(base_dir)

        overlay_dir = tmp_path / "overlay"
        with GeoDataPackBuilder(output_dir=overlay_dir) as builder:
            builder.create_database()
            builder.set_base_modules([base_dir])

            result = builder.link_and_add(
                codes={"iso3": "FRA"},
                names=[
                    {
                        "name_kind": "official",
                        "value": "République française",
                        "value_norm": "république française",
                        "lang": "fr",
                    }
                ],
            )
            builder.finalize()

        assert result.is_success

        import sqlite3

        conn = sqlite3.connect(overlay_dir / "entities.sqlite")
        rows = conn.execute(
            "SELECT name_kind, value, lang FROM names WHERE entity_id = ? AND name_kind = 'official'",
            ("geo/FRA",),
        ).fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0][0] == "official"
        assert rows[0][1] == "République française"
        assert rows[0][2] == "fr"

    def test_link_and_add_normalizes_codes(self, tmp_path):
        """ISO codes are casefolded by the normalizer at build time."""
        from resolvekit.packs.geo.build.builder import GeoDataPackBuilder

        base_dir = tmp_path / "base"
        self._create_base_module(base_dir)

        overlay_dir = tmp_path / "overlay"
        with GeoDataPackBuilder(output_dir=overlay_dir) as builder:
            builder.create_database()
            builder.set_base_modules([base_dir])

            # Pass lowercase code - normalizer should uppercase it
            result = builder.link_and_add(
                codes={"iso3": "fra"},
                attrs={"gdp_usd": 2700000000000},
            )
            builder.finalize()

        assert result.is_success
        assert result.entity_id == "geo/FRA"

    def test_link_and_add_writes_codes_to_overlay(self, tmp_path):
        from resolvekit.packs.geo.build.builder import GeoDataPackBuilder

        base_dir = tmp_path / "base"
        self._create_base_module(base_dir)

        overlay_dir = tmp_path / "overlay"
        with GeoDataPackBuilder(output_dir=overlay_dir) as builder:
            builder.create_database()
            builder.set_base_modules([base_dir])

            builder.link_and_add(codes={"iso3": "FRA"})
            builder.finalize()

        import sqlite3

        conn = sqlite3.connect(overlay_dir / "entities.sqlite")
        row = conn.execute(
            "SELECT system, value, value_norm FROM codes WHERE entity_id = ?",
            ("geo/FRA",),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "iso3"
        assert row[1] == "FRA"
        assert row[2] == "fra"  # iso3 casefolded by normalizer at build time

    def test_close_cleans_up_base_store(self, tmp_path):
        from resolvekit.packs.geo.build.builder import GeoDataPackBuilder

        base_dir = tmp_path / "base"
        self._create_base_module(base_dir)

        builder = GeoDataPackBuilder(output_dir=tmp_path / "overlay")
        builder.create_database()
        builder.set_base_modules([base_dir])

        assert builder._base_store is not None
        builder.close()
        assert builder._base_store is None


class TestBatchTransactions:
    """Tests for batch transaction support."""

    def test_context_manager_commits_on_exit(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        db_path = tmp_path / "entities.sqlite"

        with BaseDataPackBuilder(output_dir=tmp_path) as builder:
            builder.create_database()
            builder.add_entity(
                entity_id="org/test",
                entity_type="org.company",
                canonical_name="Test Corp",
                canonical_name_norm="test corp",
            )

        # After exit, data should be committed
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT * FROM entities WHERE entity_id = ?", ("org/test",)
        ).fetchone()
        conn.close()

        assert row is not None

    def test_explicit_commit_persists_data(self, tmp_path):
        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database()

        builder.add_entity(
            entity_id="org/test",
            entity_type="org.company",
            canonical_name="Test Corp",
            canonical_name_norm="test corp",
        )
        builder.commit()

        # Data should be visible from another connection
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT * FROM entities WHERE entity_id = ?", ("org/test",)
        ).fetchone()
        conn.close()

        assert row is not None
        builder.close()

    def test_large_datapack_performance(self, tmp_path):
        """Test that bulk inserts complete quickly without per-operation commits."""
        import time

        from resolvekit.shared import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path)
        builder.create_database()

        start = time.monotonic()
        for i in range(10000):
            builder.add_entity(
                entity_id=f"org/{i}",
                entity_type="org.company",
                canonical_name=f"Organization {i}",
                canonical_name_norm=f"organization {i}",
            )
        builder.finalize()
        builder.close()
        elapsed = time.monotonic() - start

        # Should complete in < 5 seconds (vs minutes with per-op commits)
        assert elapsed < 5.0, f"Bulk insert took {elapsed:.1f}s, expected < 5s"


# ---------------------------------------------------------------------------
# Helpers shared by mint-on-miss tests
# ---------------------------------------------------------------------------


def _make_base_module(base_dir):
    """Build a minimal base pack with one geo entity for linking tests."""
    import json
    import sqlite3

    from resolvekit.shared.build.schema import SCHEMA_SQL

    base_dir.mkdir(parents=True, exist_ok=True)
    db_path = base_dir / "entities.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_SQL)

    conn.execute(
        "INSERT INTO entities (entity_id, entity_type, canonical_name, canonical_name_norm)"
        " VALUES (?, ?, ?, ?)",
        ("geo/FRA", "geo.country", "France", "france"),
    )
    conn.execute(
        "INSERT INTO names (entity_id, name_kind, value, value_norm, lang, script, is_preferred)"
        " VALUES (?, 'canonical', ?, ?, '', '', 1)",
        ("geo/FRA", "France", "france"),
    )
    conn.execute(
        "INSERT INTO codes (entity_id, system, value, value_norm) VALUES (?, ?, ?, ?)",
        ("geo/FRA", "iso3", "FRA", "FRA"),
    )
    conn.execute("INSERT INTO names_fts(names_fts) VALUES('rebuild')")
    conn.commit()
    conn.close()

    # Write metadata.json so _read_store_file works
    metadata = {
        "datapack_id": "geo.base.test",
        "module_id": "geo.base.test",
        "domain_pack_id": "geo",
        "pack_type": "base",
        "store_type": "sqlite",
        "store_file": "entities.sqlite",
        "entity_schema_version": "1.0",
        "feature_schema_version": "geo.features.v1",
        "index_versions": {"fts": "fts5", "symspell": None},
        "build_timestamp": "2026-01-01T00:00:00+00:00",
        "source_datasets": ["test"],
        "module_dependencies": [],
    }
    (base_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


class _MinimalNormalizer:
    """Normaliser stub used by the pure-mint path tests (no domain builder needed)."""

    def normalize_code(self, system: str, value: str) -> str:
        return value.upper() if system in ("iso3", "iso2") else value

    def normalize_name(self, value: str) -> str:
        return value.lower()


class _MinimalLinker:
    """Linker stub that always returns not_found (used in error/skip tests)."""

    def resolve_link(self, overlay_row, link_keys, base_store, *, valid_systems=None):
        from resolvekit.core.linking.linker import LinkResult

        return LinkResult.not_found("stub: no match")


# ---------------------------------------------------------------------------
# Tests: mint-on-miss + pure-mint path
# ---------------------------------------------------------------------------


class TestLinkAndAddMintOnMiss:
    """Mint-on-miss behaviour: on_miss modes, pure-mint without base."""

    def test_pure_mint_no_base_does_not_raise(self, tmp_path):
        """on_miss='mint' + empty link_keys mints without calling set_base_modules."""
        from resolvekit.shared.build.base_builder import BaseDataPackBuilder

        builder = BaseDataPackBuilder(output_dir=tmp_path / "pack")
        builder.create_database()

        # Wire a minimal normaliser directly (subclasses do this in set_base_modules)
        builder._normalizer = _MinimalNormalizer()

        result = builder.link_and_add(
            codes={"sku": "ABC"},
            canonical_name="Widget",
            entity_type="custom.product",
            link_keys=[],  # no link keys → pure mint
            on_miss="mint",
            mint_entity_id="custom/widget-1",
        )

        assert result.is_success
        assert result.entity_id == "custom/widget-1"

    def test_pure_mint_writes_entity_to_db(self, tmp_path):
        """Minted entity should appear in entities + codes tables."""
        import sqlite3

        from resolvekit.shared.build.base_builder import BaseDataPackBuilder

        pack_dir = tmp_path / "pack"
        builder = BaseDataPackBuilder(output_dir=pack_dir)
        builder.create_database()
        builder._normalizer = _MinimalNormalizer()

        builder.link_and_add(
            codes={"sku": "XYZ"},
            canonical_name="Gadget",
            entity_type="custom.product",
            link_keys=[],
            on_miss="mint",
            mint_entity_id="custom/gadget-1",
        )
        builder.finalize()
        builder.close()

        conn = sqlite3.connect(pack_dir / "entities.sqlite")
        row = conn.execute(
            "SELECT canonical_name FROM entities WHERE entity_id = ?",
            ("custom/gadget-1",),
        ).fetchone()
        assert row is not None
        assert row[0] == "Gadget"

        code_row = conn.execute(
            "SELECT value FROM codes WHERE entity_id = ? AND system = ?",
            ("custom/gadget-1", "sku"),
        ).fetchone()
        assert code_row is not None
        assert code_row[0] == "XYZ"
        conn.close()

    def test_pure_mint_with_names_writes_names(self, tmp_path):
        """Minted entity should have additional names written."""
        import sqlite3

        from resolvekit.shared.build.base_builder import BaseDataPackBuilder

        pack_dir = tmp_path / "pack"
        builder = BaseDataPackBuilder(output_dir=pack_dir)
        builder.create_database()
        builder._normalizer = _MinimalNormalizer()

        builder.link_and_add(
            codes={},
            canonical_name="Acme Corp",
            entity_type="org.company",
            names=[{"name_kind": "alias", "value": "Acme", "value_norm": "acme"}],
            link_keys=[],
            on_miss="mint",
            mint_entity_id="org/acme",
        )
        builder.finalize()
        builder.close()

        conn = sqlite3.connect(pack_dir / "entities.sqlite")
        alias = conn.execute(
            "SELECT value FROM names WHERE entity_id = ? AND name_kind = 'alias'",
            ("org/acme",),
        ).fetchone()
        assert alias is not None
        assert alias[0] == "Acme"
        conn.close()

    def test_on_miss_error_raises_value_error(self, tmp_path):
        """on_miss='error' raises ValueError when the linker finds no match."""
        from resolvekit.shared.build.base_builder import BaseDataPackBuilder

        base_dir = tmp_path / "base"
        _make_base_module(base_dir)

        pack_dir = tmp_path / "pack"
        builder = BaseDataPackBuilder(output_dir=pack_dir)
        builder.create_database()
        builder._normalizer = _MinimalNormalizer()
        builder._linker = _MinimalLinker()

        # Open a real base store so the guard passes
        builder._open_base_stores([base_dir])

        with pytest.raises(ValueError, match="linking failed"):
            builder.link_and_add(
                codes={"iso3": "ZZZ"},
                canonical_name="Nowhere",
                entity_type="geo.country",
                link_keys=["iso3"],
                on_miss="error",
            )

        builder.close()

    def test_on_miss_skip_returns_failure_result(self, tmp_path):
        """on_miss='skip' (default) returns the failure LinkResult unchanged."""
        from resolvekit.shared.build.base_builder import BaseDataPackBuilder

        base_dir = tmp_path / "base"
        _make_base_module(base_dir)

        pack_dir = tmp_path / "pack"
        builder = BaseDataPackBuilder(output_dir=pack_dir)
        builder.create_database()
        builder._normalizer = _MinimalNormalizer()
        builder._linker = _MinimalLinker()
        builder._open_base_stores([base_dir])

        result = builder.link_and_add(
            codes={"iso3": "ZZZ"},
            canonical_name="Nowhere",
            entity_type="geo.country",
            link_keys=["iso3"],
            on_miss="skip",
        )

        assert not result.is_success
        assert result.status == "not_found"

        builder.close()

    def test_on_miss_skip_does_not_write_entity(self, tmp_path):
        """Skipped rows leave the overlay database empty."""
        import sqlite3

        from resolvekit.shared.build.base_builder import BaseDataPackBuilder

        base_dir = tmp_path / "base"
        _make_base_module(base_dir)

        pack_dir = tmp_path / "pack"
        builder = BaseDataPackBuilder(output_dir=pack_dir)
        builder.create_database()
        builder._normalizer = _MinimalNormalizer()
        builder._linker = _MinimalLinker()
        builder._open_base_stores([base_dir])

        builder.link_and_add(
            codes={"iso3": "ZZZ"},
            canonical_name="Nowhere",
            entity_type="geo.country",
            link_keys=["iso3"],
            on_miss="skip",
        )
        builder.finalize()
        builder.close()

        conn = sqlite3.connect(pack_dir / "entities.sqlite")
        count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        conn.close()
        assert count == 0

    def test_null_base_with_nonempty_link_keys_raises(self, tmp_path):
        """Non-empty link_keys without a base still raises RuntimeError (misuse guard)."""
        from resolvekit.shared.build.base_builder import BaseDataPackBuilder

        pack_dir = tmp_path / "pack"
        builder = BaseDataPackBuilder(output_dir=pack_dir)
        builder.create_database()
        builder._normalizer = _MinimalNormalizer()
        # _base_store and _linker intentionally left as None

        with pytest.raises(RuntimeError, match="Base modules not set"):
            builder.link_and_add(
                codes={"iso3": "FRA"},
                canonical_name="France",
                entity_type="geo.country",
                link_keys=["iso3"],  # non-empty → guard fires
                on_miss="mint",
                mint_entity_id="custom/fra",
            )

        builder.close()

    def test_on_miss_mint_with_base_creates_minted_entity(self, tmp_path):
        """on_miss='mint' with a real base but no match mints a new entity."""
        import sqlite3

        from resolvekit.shared.build.base_builder import BaseDataPackBuilder

        base_dir = tmp_path / "base"
        _make_base_module(base_dir)

        pack_dir = tmp_path / "pack"
        builder = BaseDataPackBuilder(output_dir=pack_dir)
        builder.create_database()
        builder._normalizer = _MinimalNormalizer()
        builder._linker = _MinimalLinker()
        builder._open_base_stores([base_dir])

        result = builder.link_and_add(
            codes={"iso3": "XYZ"},
            canonical_name="Ruritania",
            entity_type="geo.country",
            link_keys=["iso3"],
            on_miss="mint",
            mint_entity_id="custom/ruritania",
        )

        assert result.is_success
        assert result.entity_id == "custom/ruritania"

        builder.finalize()
        builder.close()

        conn = sqlite3.connect(pack_dir / "entities.sqlite")
        row = conn.execute(
            "SELECT canonical_name FROM entities WHERE entity_id = ?",
            ("custom/ruritania",),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "Ruritania"
