"""Tests for OrgDataPackBuilder."""

import json
import sqlite3

import pytest


class TestOrgDataPackBuilderInit:
    """Tests for OrgDataPackBuilder initialization."""

    def test_init_creates_output_directory(self, tmp_path):
        from resolvekit.packs.org.build.builder import OrgDataPackBuilder

        output_dir = tmp_path / "new_dir"
        _builder = OrgDataPackBuilder(output_dir=output_dir)

        assert output_dir.exists()

    def test_inherits_base_functionality(self, tmp_path):
        from resolvekit.packs.org.build.builder import OrgDataPackBuilder
        from resolvekit.shared import BaseDataPackBuilder

        builder = OrgDataPackBuilder(output_dir=tmp_path)

        assert isinstance(builder, BaseDataPackBuilder)


class TestBuildMetadataOverride:
    """Tests for build_metadata override."""

    def test_build_metadata_uses_org_defaults(self, tmp_path):
        from resolvekit.packs.org.build.builder import OrgDataPackBuilder

        builder = OrgDataPackBuilder(output_dir=tmp_path)
        metadata = builder.build_metadata(
            datapack_id="org_test_v1",
            source_datasets=["test_data"],
        )

        assert metadata["datapack_id"] == "org_test_v1"
        assert metadata["domain_pack_id"] == "org"
        assert metadata["feature_schema_version"] == "org.features.v1"

        # Verify file was written
        metadata_path = tmp_path / "metadata.json"
        assert metadata_path.exists()

        with open(metadata_path) as f:
            written = json.load(f)
        assert written["domain_pack_id"] == "org"


class TestAddOrg:
    """Tests for add_org helper."""

    def test_add_org_enforces_type_prefix(self, tmp_path):
        from resolvekit.packs.org.build.builder import OrgDataPackBuilder

        builder = OrgDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        builder.add_org(
            entity_id="org/test",
            entity_type="company",  # No prefix
            canonical_name="Test Corp",
            canonical_name_norm="test corp",
        )
        builder.close()

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT entity_type FROM entities WHERE entity_id = ?", ("org/test",)
        ).fetchone()
        conn.close()

        assert row[0] == "org.company"

    def test_add_org_preserves_existing_prefix(self, tmp_path):
        from resolvekit.packs.org.build.builder import OrgDataPackBuilder

        builder = OrgDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        builder.add_org(
            entity_id="org/test",
            entity_type="org.subsidiary",  # Already has prefix
            canonical_name="Test Corp",
            canonical_name_norm="test corp",
        )
        builder.close()

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT entity_type FROM entities WHERE entity_id = ?", ("org/test",)
        ).fetchone()
        conn.close()

        assert row[0] == "org.subsidiary"


class TestNameHelpers:
    """Tests for name helpers."""

    def test_add_acronym(self, tmp_path):
        from resolvekit.packs.org.build.builder import OrgDataPackBuilder

        builder = OrgDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        builder.add_org(
            entity_id="org/test",
            entity_type="company",
            canonical_name="International Business Machines",
            canonical_name_norm="international business machines",
        )

        builder.add_acronym(
            entity_id="org/test",
            value="IBM",
            value_norm="ibm",
        )
        builder.close()

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT name_kind FROM names WHERE entity_id = ? AND value = ?",
            ("org/test", "IBM"),
        ).fetchone()
        conn.close()

        assert row[0] == "acronym"

    def test_add_short_name(self, tmp_path):
        from resolvekit.packs.org.build.builder import OrgDataPackBuilder

        builder = OrgDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        builder.add_org(
            entity_id="org/test",
            entity_type="company",
            canonical_name="The Coca-Cola Company",
            canonical_name_norm="the coca cola company",
        )

        builder.add_short_name(
            entity_id="org/test",
            value="Coca-Cola",
            value_norm="coca cola",
        )
        builder.close()

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT name_kind FROM names WHERE entity_id = ? AND value = ?",
            ("org/test", "Coca-Cola"),
        ).fetchone()
        conn.close()

        assert row[0] == "short_name"

    def test_add_legal_name(self, tmp_path):
        from resolvekit.packs.org.build.builder import OrgDataPackBuilder

        builder = OrgDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        builder.add_org(
            entity_id="org/test",
            entity_type="company",
            canonical_name="Apple",
            canonical_name_norm="apple",
        )

        builder.add_legal_name(
            entity_id="org/test",
            value="Apple Inc.",
            value_norm="apple inc",
        )
        builder.close()

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT name_kind FROM names WHERE entity_id = ? AND value = ?",
            ("org/test", "Apple Inc."),
        ).fetchone()
        conn.close()

        assert row[0] == "legal_name"


class TestAddParentOrg:
    """Tests for add_parent_org helper."""

    def test_add_parent_org_default_relation(self, tmp_path):
        from resolvekit.packs.org.build.builder import OrgDataPackBuilder

        builder = OrgDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        builder.add_org(
            entity_id="org/parent",
            entity_type="company",
            canonical_name="Parent Corp",
            canonical_name_norm="parent corp",
        )

        builder.add_org(
            entity_id="org/child",
            entity_type="company",
            canonical_name="Child Corp",
            canonical_name_norm="child corp",
        )

        builder.add_parent_org(
            entity_id="org/child",
            parent_id="org/parent",
        )
        builder.close()

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT relation_type, target_id FROM relations WHERE entity_id = ?",
            ("org/child",),
        ).fetchone()
        conn.close()

        assert row[0] == "subsidiary_of"
        assert row[1] == "org/parent"

    def test_add_parent_org_custom_relation(self, tmp_path):
        from resolvekit.packs.org.build.builder import OrgDataPackBuilder

        builder = OrgDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        builder.add_org(
            entity_id="org/parent",
            entity_type="company",
            canonical_name="Parent Corp",
            canonical_name_norm="parent corp",
        )

        builder.add_org(
            entity_id="org/child",
            entity_type="company",
            canonical_name="Child Corp",
            canonical_name_norm="child corp",
        )

        builder.add_parent_org(
            entity_id="org/child",
            parent_id="org/parent",
            relation_type="owned_by",
        )
        builder.close()

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT relation_type, target_id FROM relations WHERE entity_id = ?",
            ("org/child",),
        ).fetchone()
        conn.close()

        assert row[0] == "owned_by"
        assert row[1] == "org/parent"


class TestAddCountryCode:
    """Tests for add_country_code helper."""

    def test_add_country_code_normalizes_to_uppercase(self, tmp_path):
        from resolvekit.packs.org.build.builder import OrgDataPackBuilder

        builder = OrgDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        builder.add_org(
            entity_id="org/test",
            entity_type="company",
            canonical_name="Test Corp",
            canonical_name_norm="test corp",
        )

        builder.add_country_code(entity_id="org/test", country_code="us")
        builder.close()

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT attrs_json FROM entities WHERE entity_id = ?", ("org/test",)
        ).fetchone()
        conn.close()

        attrs = json.loads(row[0])
        assert attrs["country_code"] == "US"

    def test_add_country_code_rejects_invalid_length(self, tmp_path):
        from resolvekit.packs.org.build.builder import OrgDataPackBuilder

        builder = OrgDataPackBuilder(output_dir=tmp_path)
        builder.create_database("test.db")

        builder.add_org(
            entity_id="org/test",
            entity_type="company",
            canonical_name="Test Corp",
            canonical_name_norm="test corp",
        )

        with pytest.raises(ValueError, match="must be 2 characters"):
            builder.add_country_code(entity_id="org/test", country_code="USA")

    def test_add_country_code_merges_with_existing_attrs(self, tmp_path):
        from resolvekit.packs.org.build.builder import OrgDataPackBuilder

        builder = OrgDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        builder.add_org(
            entity_id="org/test",
            entity_type="company",
            canonical_name="Test Corp",
            canonical_name_norm="test corp",
            attrs={"industry": "tech"},
        )

        builder.add_country_code(entity_id="org/test", country_code="DE")
        builder.close()

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT attrs_json FROM entities WHERE entity_id = ?", ("org/test",)
        ).fetchone()
        conn.close()

        attrs = json.loads(row[0])
        assert attrs["country_code"] == "DE"
        assert attrs["industry"] == "tech"


class TestAddExternalCode:
    """Tests for add_external_code helper."""

    def test_add_external_code(self, tmp_path):
        from resolvekit.packs.org.build.builder import OrgDataPackBuilder

        builder = OrgDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        builder.add_org(
            entity_id="org/test",
            entity_type="company",
            canonical_name="Test Corp",
            canonical_name_norm="test corp",
        )

        builder.add_external_code(
            entity_id="org/test",
            system="lei",
            value="549300ABC123DEF456GH",
            value_norm="549300abc123def456gh",
        )
        builder.close()

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT system, value, value_norm FROM codes WHERE entity_id = ?",
            ("org/test",),
        ).fetchone()
        conn.close()

        assert row[0] == "lei"
        assert row[1] == "549300ABC123DEF456GH"
        assert row[2] == "549300abc123def456gh"

    def test_add_external_code_multiple_systems(self, tmp_path):
        from resolvekit.packs.org.build.builder import OrgDataPackBuilder

        builder = OrgDataPackBuilder(output_dir=tmp_path)
        db_path = builder.create_database("test.db")

        builder.add_org(
            entity_id="org/test",
            entity_type="company",
            canonical_name="Test Corp",
            canonical_name_norm="test corp",
        )

        builder.add_external_code(
            entity_id="org/test",
            system="lei",
            value="549300ABC123DEF456GH",
            value_norm="549300abc123def456gh",
        )

        builder.add_external_code(
            entity_id="org/test",
            system="duns",
            value="123456789",
            value_norm="123456789",
        )
        builder.close()

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT system, value FROM codes WHERE entity_id = ? ORDER BY system",
            ("org/test",),
        ).fetchall()
        conn.close()

        assert len(rows) == 2
        assert rows[0] == ("duns", "123456789")
        assert rows[1] == ("lei", "549300ABC123DEF456GH")


class TestOrgOverlayMetadata:
    """Tests for org build_overlay_metadata."""

    def test_builds_overlay_metadata_with_org_defaults(self, tmp_path):
        from resolvekit.packs.org.build.builder import OrgDataPackBuilder

        builder = OrgDataPackBuilder(output_dir=tmp_path)
        metadata = builder.build_overlay_metadata(
            datapack_id="org_overlay_v1",
            base_module_ids=["org.companies"],
            source_datasets=["custom_data"],
            link_keys=["lei"],
        )

        assert metadata["datapack_id"] == "org_overlay_v1"
        assert metadata["domain_pack_id"] == "org"
        assert metadata["feature_schema_version"] == "org.features.v1"
        assert metadata["pack_type"] == "overlay"
        assert metadata["base_module_ids"] == ["org.companies"]
        assert metadata["link_keys"] == ["lei"]
        assert metadata["allow_new_entities"] is False

    def test_overlay_metadata_rejects_empty_base_id(self, tmp_path):
        from resolvekit.packs.org.build.builder import OrgDataPackBuilder

        builder = OrgDataPackBuilder(output_dir=tmp_path)

        with pytest.raises(ValueError, match="base_module_ids must not be empty"):
            builder.build_overlay_metadata(
                datapack_id="org_overlay_v1",
                base_module_ids=[],
                source_datasets=["custom_data"],
                link_keys=["lei"],
            )


class TestOrgSetBaseModules:
    """Tests for org set_base_modules and link_and_add."""

    def _create_base_module(self, base_dir):
        """Create an org base pack with test entities."""
        from resolvekit.packs.org.build.builder import OrgDataPackBuilder

        base_dir.mkdir(parents=True, exist_ok=True)
        with OrgDataPackBuilder(output_dir=base_dir) as builder:
            builder.create_database()
            builder.add_org(
                entity_id="org/apple",
                entity_type="company",
                canonical_name="Apple Inc.",
                canonical_name_norm="apple",
            )
            builder.add_code(
                entity_id="org/apple",
                system="lei",
                value="HWUPKR0MPOU8FGXBT394",
                value_norm="hwupkr0mpou8fgxbt394",
            )
            builder.add_org(
                entity_id="org/msft",
                entity_type="company",
                canonical_name="Microsoft Corporation",
                canonical_name_norm="microsoft",
            )
            builder.add_code(
                entity_id="org/msft",
                system="lei",
                value="INR2EJN1ERAN0W5ZP974",
                value_norm="inr2ejn1eran0w5zp974",
            )
            builder.finalize()

    def test_link_and_add_end_to_end(self, tmp_path):
        """Full workflow: create base, link overlay, build metadata."""
        from resolvekit.packs.org.build.builder import OrgDataPackBuilder

        base_dir = tmp_path / "base"
        self._create_base_module(base_dir)

        overlay_dir = tmp_path / "overlay"
        with OrgDataPackBuilder(output_dir=overlay_dir) as builder:
            builder.create_database()
            builder.set_base_modules([base_dir])

            result = builder.link_and_add(
                codes={"lei": "HWUPKR0MPOU8FGXBT394"},
                attrs={"revenue_usd": 394000000000},
            )

            builder.finalize()
            builder.build_overlay_metadata(
                datapack_id="org_enrichment_v1",
                base_module_ids=["org.companies"],
                source_datasets=["financials"],
                link_keys=["lei"],
            )

        assert result.is_success
        assert result.entity_id == "org/apple"

        # Verify overlay database
        conn = sqlite3.connect(overlay_dir / "entities.sqlite")
        row = conn.execute(
            "SELECT canonical_name, attrs_json FROM entities WHERE entity_id = ?",
            ("org/apple",),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "Apple Inc."  # Fetched from base
        assert json.loads(row[1])["revenue_usd"] == 394000000000

    def test_link_and_add_not_found(self, tmp_path):
        from resolvekit.packs.org.build.builder import OrgDataPackBuilder

        base_dir = tmp_path / "base"
        self._create_base_module(base_dir)

        overlay_dir = tmp_path / "overlay"
        with OrgDataPackBuilder(output_dir=overlay_dir) as builder:
            builder.create_database()
            builder.set_base_modules([base_dir])

            result = builder.link_and_add(
                codes={"lei": "NONEXISTENT0000000000"},
                canonical_name="Unknown Corp",
                entity_type="org.company",
            )

        assert not result.is_success
        assert result.status == "not_found"
