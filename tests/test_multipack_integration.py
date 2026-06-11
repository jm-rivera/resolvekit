"""Integration tests for multi-pack resolution."""

import json
import sqlite3
from pathlib import Path

import pytest

from resolvekit.core.datapack import NORMALIZER_VERSION


@pytest.fixture
def multi_test_datapacks(tmp_path: Path) -> list[Path]:
    """Create separate geo and org DataPacks for testing."""
    geo_path = tmp_path / "geo_pack"
    org_path = tmp_path / "org_pack"
    geo_path.mkdir()
    org_path.mkdir()

    # Geo pack DB
    geo_db = geo_path / "entities.sqlite"
    conn = sqlite3.connect(geo_db)
    conn.executescript(
        """
        CREATE TABLE entities (
            entity_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            canonical_name_norm TEXT NOT NULL,
            valid_from TEXT,
            valid_until TEXT
        );
        CREATE TABLE names (
            entity_id TEXT NOT NULL,
            name_kind TEXT NOT NULL,
            value TEXT NOT NULL,
            value_norm TEXT NOT NULL,
            lang TEXT,
            is_preferred INTEGER DEFAULT 0
        );
        CREATE TABLE codes (
            entity_id TEXT NOT NULL,
            system TEXT NOT NULL,
            value TEXT NOT NULL,
            value_norm TEXT NOT NULL,
            PRIMARY KEY (entity_id, system)
        );
        CREATE TABLE relations (
            entity_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            target_id TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE names_fts USING fts5(entity_id, value_norm);
        INSERT INTO entities VALUES
            ('country/USA', 'geo.country', 'United States', 'united states', NULL, NULL),
            ('city/Paris', 'geo.city', 'Paris', 'paris', NULL, NULL);
        INSERT INTO codes VALUES
            ('country/USA', 'iso2', 'US', 'us');
        INSERT INTO names VALUES
            ('country/USA', 'canonical', 'United States', 'united states', 'en', 1),
            ('city/Paris', 'canonical', 'Paris', 'paris', 'en', 1);
        INSERT INTO names_fts(entity_id, value_norm) VALUES
            ('country/USA', 'united states'),
            ('city/Paris', 'paris');
    """
    )
    conn.commit()
    conn.close()
    (geo_path / "metadata.json").write_text(
        json.dumps(
            {
                "datapack_id": "geo_test_v1",
                "module_id": "geo.countries",
                "domain_pack_id": "geo",
                "entity_schema_version": "1.0",
                "feature_schema_version": "geo.features.v1",
                "normalizer_version": NORMALIZER_VERSION,
                "index_versions": {"fts": "fts5", "symspell": None},
                "build_timestamp": "2024-01-15T10:00:00Z",
                "source_datasets": ["test-fixture"],
            }
        )
    )

    # Org pack DB
    org_db = org_path / "entities.sqlite"
    conn = sqlite3.connect(org_db)
    conn.executescript(
        """
        CREATE TABLE entities (
            entity_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            canonical_name_norm TEXT NOT NULL,
            valid_from TEXT,
            valid_until TEXT
        );
        CREATE TABLE names (
            entity_id TEXT NOT NULL,
            name_kind TEXT NOT NULL,
            value TEXT NOT NULL,
            value_norm TEXT NOT NULL,
            lang TEXT,
            is_preferred INTEGER DEFAULT 0
        );
        CREATE TABLE codes (
            entity_id TEXT NOT NULL,
            system TEXT NOT NULL,
            value TEXT NOT NULL,
            value_norm TEXT NOT NULL,
            PRIMARY KEY (entity_id, system)
        );
        CREATE TABLE relations (
            entity_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            target_id TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE names_fts USING fts5(entity_id, value_norm);
        INSERT INTO entities VALUES
            ('org/EU', 'org.igo', 'European Union', 'european union', NULL, NULL),
            ('org/Paris_Climate', 'org.agreement', 'Paris Agreement', 'paris agreement', NULL, NULL);
        INSERT INTO names VALUES
            ('org/EU', 'canonical', 'European Union', 'european union', 'en', 1),
            ('org/EU', 'acronym', 'EU', 'eu', 'en', 0),
            ('org/Paris_Climate', 'canonical', 'Paris Agreement', 'paris agreement', 'en', 1);
        INSERT INTO names_fts(entity_id, value_norm) VALUES
            ('org/EU', 'european union'),
            ('org/EU', 'eu'),
            ('org/Paris_Climate', 'paris agreement');
    """
    )
    conn.commit()
    conn.close()
    (org_path / "metadata.json").write_text(
        json.dumps(
            {
                "datapack_id": "org_test_v1",
                "module_id": "org.entities",
                "domain_pack_id": "org",
                "entity_schema_version": "1.0",
                "feature_schema_version": "org.features.v1",
                "normalizer_version": NORMALIZER_VERSION,
                "index_versions": {"fts": "fts5", "symspell": None},
                "build_timestamp": "2024-01-15T10:00:00Z",
                "source_datasets": ["test-fixture"],
            }
        )
    )

    return [geo_path, org_path]


class TestMultiPackIntegration:
    """Cross-domain resolution tests."""

    def test_routes_eu_to_org(self, multi_test_datapacks):
        from resolvekit.core.api import Resolver
        from resolvekit.core.model import ResolutionStatus

        resolver = Resolver.from_datapacks(datapack_paths=multi_test_datapacks)

        result = resolver.resolve("EU")

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "org/EU"

    def test_routes_paris_to_geo_by_default(self, multi_test_datapacks):
        from resolvekit.core.api import Resolver
        from resolvekit.core.model import ResolutionStatus

        resolver = Resolver.from_datapacks(datapack_paths=multi_test_datapacks)

        result = resolver.resolve("Paris")

        # Paris appears in both geo (city) and org (Paris Agreement) packs.
        # When both are close in score, result may be AMBIGUOUS.
        # The geo city should be in the top candidates either way.
        if result.status == ResolutionStatus.RESOLVED:
            assert "Paris" in result.entity_id or "paris" in result.entity_id.lower()
        else:
            assert result.status == ResolutionStatus.AMBIGUOUS
            # City/Paris should be first in candidates (exact name match scores higher)
            assert len(result.candidates) > 0
            assert result.candidates[0].entity_id == "city/Paris"

    def test_explicit_routing_to_org(self, multi_test_datapacks):
        from resolvekit.core.api import Resolver, RoutingMode
        from resolvekit.core.model import ResolutionStatus

        resolver = Resolver.from_datapacks(
            datapack_paths=multi_test_datapacks, routing_mode=RoutingMode.EXPLICIT
        )

        result = resolver.resolve("Paris Agreement", domain="org")

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "org/Paris_Climate"

    def test_us_code_routes_to_geo(self, multi_test_datapacks):
        from resolvekit.core.api import Resolver
        from resolvekit.core.model import ResolutionStatus

        resolver = Resolver.from_datapacks(datapack_paths=multi_test_datapacks)

        result = resolver.resolve("US")

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "country/USA"

    def test_filter_to_single_pack(self, multi_test_datapacks):
        from resolvekit.core.api import Resolver
        from resolvekit.core.model import ResolutionStatus

        # Only load geo pack
        resolver = Resolver.from_datapacks(
            datapack_paths=multi_test_datapacks, domains=["geo"]
        )

        # EU should not resolve in geo-only mode
        result = resolver.resolve("EU")
        assert (
            result.status != ResolutionStatus.RESOLVED or result.entity_id != "org/EU"
        )

        # US should still resolve
        result = resolver.resolve("US")
        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "country/USA"

    def test_hybrid_routing_mode(self, multi_test_datapacks):
        from resolvekit.core.api import Resolver, RoutingMode
        from resolvekit.core.model import ResolutionStatus

        resolver = Resolver.from_datapacks(
            datapack_paths=multi_test_datapacks,
            routing_mode=RoutingMode.HYBRID,
        )

        # Should still resolve correctly with hybrid routing
        result = resolver.resolve("US")
        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "country/USA"

    def test_resolve_many_mixed_domains(self, multi_test_datapacks):
        from resolvekit.core.api import Resolver
        from resolvekit.core.model import ResolutionStatus

        resolver = Resolver.from_datapacks(datapack_paths=multi_test_datapacks)

        results = list(resolver._resolve_many_internal(["US", "EU", "Paris"]))

        assert len(results) == 3
        # US should resolve to geo
        assert results[0].status == ResolutionStatus.RESOLVED
        assert results[0].entity_id == "country/USA"
        # EU should resolve to org
        assert results[1].status == ResolutionStatus.RESOLVED
        assert results[1].entity_id == "org/EU"
        # Paris may be ambiguous (matches geo city and org Paris Agreement)
        assert results[2].status in (
            ResolutionStatus.RESOLVED,
            ResolutionStatus.AMBIGUOUS,
        )


class TestCustomPackFactory:
    """Tests for custom pack factory registration."""

    def test_custom_factory_without_symspell_param(self, tmp_path):
        """Custom pack factories without symspell_dict_path should work."""
        import json
        import sqlite3

        from resolvekit.core import register_pack_factory
        from resolvekit.core.api import Resolver
        from resolvekit.core.engine import ThresholdDecisionPolicy
        from resolvekit.core.registry import _pack_factories

        # Create a minimal custom pack that doesn't accept symspell_dict_path
        class CustomPack:
            def __init__(self):  # No symspell_dict_path parameter
                pass

            @property
            def pack_id(self) -> str:
                return "custom"

            @property
            def sources(self):
                return []

            @property
            def constraints(self):
                return []

            @property
            def feature_extractor(self):
                return None

            @property
            def scorer(self):
                return None

            @property
            def decision_policy(self):
                # decision_policy is required by PipelineRunner (F3 contract)
                return ThresholdDecisionPolicy(
                    confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
                )

            @property
            def routing_hints(self):
                return None

            @property
            def normalization_profile(self):
                return None

            @property
            def merge_normalizer(self):
                return None

            @property
            def config(self):
                return None

        # Register custom pack factory
        register_pack_factory("custom", CustomPack)

        try:
            # Create datapack for custom pack
            custom_path = tmp_path / "custom_pack"
            custom_path.mkdir()

            (custom_path / "metadata.json").write_text(
                json.dumps(
                    {
                        "datapack_id": "custom_test_v1",
                        "module_id": "custom.entities",
                        "domain_pack_id": "custom",
                        "entity_schema_version": "1.0",
                        "feature_schema_version": "custom.features.v1",
                        "normalizer_version": NORMALIZER_VERSION,
                        "build_timestamp": "2024-01-15T10:00:00Z",
                    }
                )
            )

            db_path = custom_path / "entities.sqlite"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE entities (
                    entity_id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    canonical_name TEXT NOT NULL,
                    canonical_name_norm TEXT NOT NULL,
                    valid_from TEXT,
                    valid_until TEXT
                );
                CREATE TABLE names (entity_id TEXT, name_kind TEXT, value TEXT,
                    value_norm TEXT, lang TEXT, is_preferred INTEGER);
                CREATE TABLE codes (entity_id TEXT, system TEXT, value TEXT,
                    value_norm TEXT);
                CREATE TABLE relations (entity_id TEXT, relation_type TEXT,
                    target_id TEXT);
            """
            )
            conn.close()

            # This should not raise TypeError
            resolver = Resolver.from_datapacks(
                datapack_paths=[custom_path], domains=["custom"]
            )
            assert resolver is not None

        finally:
            # Clean up: remove custom factory
            _pack_factories.pop("custom", None)
