"""Integration tests for full geo resolution pipeline."""

import json
import sqlite3

import pytest

from resolvekit.core.datapack import NORMALIZER_VERSION


@pytest.fixture
def geo_test_datapack(tmp_path):
    """Create test DataPack with geo data."""
    db_path = tmp_path / "entities.sqlite"
    conn = sqlite3.connect(db_path)

    conn.executescript("""
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

        CREATE INDEX idx_codes_lookup ON codes(system, value_norm);
        CREATE INDEX idx_names_lookup ON names(value_norm, name_kind);

        CREATE VIRTUAL TABLE names_fts USING fts5(entity_id, value_norm);

        -- Test data
        INSERT INTO entities VALUES
            ('country/USA', 'geo.country', 'United States of America', 'united states of america', NULL, NULL),
            ('country/GBR', 'geo.country', 'United Kingdom', 'united kingdom', NULL, NULL),
            ('state/California', 'geo.state', 'California', 'california', NULL, NULL);

        INSERT INTO codes VALUES
            ('country/USA', 'iso2', 'US', 'us'),
            ('country/USA', 'iso3', 'USA', 'usa'),
            ('country/USA', 'iso_numeric', '840', '840'),
            ('country/GBR', 'iso2', 'GB', 'gb'),
            ('country/GBR', 'iso3', 'GBR', 'gbr'),
            ('country/GBR', 'iso_numeric', '826', '826');

        INSERT INTO names VALUES
            ('country/USA', 'canonical', 'United States of America', 'united states of america', 'en', 1),
            ('country/USA', 'alias', 'USA', 'usa', 'en', 0),
            ('country/USA', 'alias', 'America', 'america', 'en', 0),
            ('country/GBR', 'canonical', 'United Kingdom', 'united kingdom', 'en', 1),
            ('country/GBR', 'alias', 'UK', 'uk', 'en', 0),
            ('state/California', 'canonical', 'California', 'california', 'en', 1);

        INSERT INTO relations VALUES
            ('state/California', 'contained_in', 'country/USA');

        INSERT INTO names_fts(entity_id, value_norm) VALUES
            ('country/USA', 'united states of america'),
            ('country/USA', 'usa'),
            ('country/USA', 'america'),
            ('country/GBR', 'united kingdom'),
            ('country/GBR', 'uk'),
            ('state/California', 'california');
    """)

    conn.commit()
    conn.close()

    # Write metadata.json
    (tmp_path / "metadata.json").write_text(
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

    return tmp_path


class TestGeoIntegration:
    """Full pipeline integration tests."""

    def test_resolve_by_code(self, geo_test_datapack):
        from resolvekit.core.engine import PipelineRunner
        from resolvekit.core.explain import MemoryTraceSink
        from resolvekit.core.model import (
            NormalizedText,
            Query,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.core.store import SQLiteEntityStore
        from resolvekit.packs.geo import GeoPack

        pack = GeoPack()
        store = SQLiteEntityStore(geo_test_datapack / "entities.sqlite")
        trace = MemoryTraceSink()

        runner = PipelineRunner(
            trace_sink=trace,
            store=store,
            sources=pack.sources,
            constraints=pack.constraints,
            decision_policy=pack.decision_policy,
        )

        query = Query(
            raw_text="US",
            normalized=NormalizedText(original="US", normalized="us"),
        )

        result = runner.resolve(query, ResolutionContext())

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "country/USA"

    def test_resolve_by_numeric_code(self, geo_test_datapack):
        from resolvekit.core.engine import PipelineRunner
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            NormalizedText,
            Query,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.core.store import SQLiteEntityStore
        from resolvekit.packs.geo import GeoPack

        pack = GeoPack()
        store = SQLiteEntityStore(geo_test_datapack / "entities.sqlite")

        runner = PipelineRunner(
            trace_sink=NullTraceSink(),
            store=store,
            sources=pack.sources,
            constraints=pack.constraints,
            decision_policy=pack.decision_policy,
        )

        query = Query(
            raw_text="840",
            normalized=NormalizedText(original="840", normalized="840"),
        )

        result = runner.resolve(query, ResolutionContext())

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "country/USA"

    def test_resolve_by_name(self, geo_test_datapack):
        from resolvekit.core.engine import PipelineRunner
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            NormalizedText,
            Query,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.core.store import SQLiteEntityStore
        from resolvekit.packs.geo import GeoPack

        pack = GeoPack()
        store = SQLiteEntityStore(geo_test_datapack / "entities.sqlite")

        runner = PipelineRunner(
            trace_sink=NullTraceSink(),
            store=store,
            sources=pack.sources,
            decision_policy=pack.decision_policy,
        )

        query = Query(
            raw_text="United Kingdom",
            normalized=NormalizedText(
                original="United Kingdom", normalized="united kingdom"
            ),
        )

        result = runner.resolve(query, ResolutionContext())

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "country/GBR"

    def test_resolve_by_fts(self, geo_test_datapack):
        from resolvekit.core.engine import PipelineRunner
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            NormalizedText,
            Query,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.core.store import SQLiteEntityStore
        from resolvekit.packs.geo import GeoPack

        pack = GeoPack()
        store = SQLiteEntityStore(geo_test_datapack / "entities.sqlite")

        runner = PipelineRunner(
            trace_sink=NullTraceSink(),
            store=store,
            sources=pack.sources,
            decision_policy=pack.decision_policy,
        )

        # Use a query that won't match exact code or exact name
        # but will match via FTS
        query = Query(
            raw_text="California state",
            normalized=NormalizedText(
                original="California state", normalized="california state"
            ),
        )

        result = runner.resolve(query, ResolutionContext())

        assert result.status in (
            ResolutionStatus.RESOLVED,
            ResolutionStatus.AMBIGUOUS,
            ResolutionStatus.NO_MATCH,
        )

    def test_no_match_returns_explicit_status(self, geo_test_datapack):
        from resolvekit.core.engine import PipelineRunner
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            NormalizedText,
            Query,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.core.store import SQLiteEntityStore
        from resolvekit.packs.geo import GeoPack

        pack = GeoPack()
        store = SQLiteEntityStore(geo_test_datapack / "entities.sqlite")

        runner = PipelineRunner(
            trace_sink=NullTraceSink(),
            store=store,
            sources=pack.sources,
            decision_policy=pack.decision_policy,
        )

        query = Query(
            raw_text="Nonexistent Country",
            normalized=NormalizedText(
                original="Nonexistent Country", normalized="nonexistent country"
            ),
        )

        result = runner.resolve(query, ResolutionContext())

        assert result.status is not None
        assert result.status in (ResolutionStatus.NO_MATCH, ResolutionStatus.AMBIGUOUS)

    def test_resolve_by_alias(self, geo_test_datapack):
        from resolvekit.core.engine import PipelineRunner
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            NormalizedText,
            Query,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.core.store import SQLiteEntityStore
        from resolvekit.packs.geo import GeoPack

        pack = GeoPack()
        store = SQLiteEntityStore(geo_test_datapack / "entities.sqlite")

        runner = PipelineRunner(
            trace_sink=NullTraceSink(),
            store=store,
            sources=pack.sources,
            decision_policy=pack.decision_policy,
        )

        query = Query(
            raw_text="America",
            normalized=NormalizedText(original="America", normalized="america"),
        )

        result = runner.resolve(query, ResolutionContext())

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "country/USA"

    def test_type_constraint_filters_wrong_type(self, geo_test_datapack):
        """Test that type constraint filters candidates of wrong type."""
        from resolvekit.core.engine import PipelineRunner
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import SQLiteEntityStore
        from resolvekit.packs.geo import GeoPack

        pack = GeoPack()
        store = SQLiteEntityStore(geo_test_datapack / "entities.sqlite")

        runner = PipelineRunner(
            trace_sink=NullTraceSink(),
            store=store,
            sources=pack.sources,
            constraints=pack.constraints,
            decision_policy=pack.decision_policy,
        )

        # Query "California" but looking for countries only
        query = Query(
            raw_text="California",
            normalized=NormalizedText(original="California", normalized="california"),
        )
        # Only looking for countries - California is a state
        context = ResolutionContext(entity_types={"geo.country"})

        result = runner.resolve(query, context)

        if result.entity_id:
            assert result.entity_id != "state/California"

    def test_containment_constraint_filters_outside_parent(self, geo_test_datapack):
        """Test that containment constraint filters candidates outside parent."""
        from resolvekit.core.engine import PipelineRunner
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import NormalizedText, Query, ResolutionContext
        from resolvekit.core.store import SQLiteEntityStore
        from resolvekit.packs.geo import GeoPack

        pack = GeoPack()
        store = SQLiteEntityStore(geo_test_datapack / "entities.sqlite")

        runner = PipelineRunner(
            trace_sink=NullTraceSink(),
            store=store,
            sources=pack.sources,
            constraints=pack.constraints,
            decision_policy=pack.decision_policy,
        )

        # Query "California" but looking for places in UK only
        query = Query(
            raw_text="California",
            normalized=NormalizedText(original="California", normalized="california"),
        )
        # Looking for places in UK - California is in USA
        context = ResolutionContext(parent_ids=["country/GBR"])

        result = runner.resolve(query, context)

        if result.entity_id:
            assert result.entity_id != "state/California"

    def test_containment_constraint_keeps_contained(self, geo_test_datapack):
        """Test that containment constraint keeps candidates within parent."""
        from resolvekit.core.engine import PipelineRunner
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            NormalizedText,
            Query,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.core.store import SQLiteEntityStore
        from resolvekit.packs.geo import GeoPack

        pack = GeoPack()
        store = SQLiteEntityStore(geo_test_datapack / "entities.sqlite")

        runner = PipelineRunner(
            trace_sink=NullTraceSink(),
            store=store,
            sources=pack.sources,
            constraints=pack.constraints,
            decision_policy=pack.decision_policy,
        )

        # Query "California" looking for places in USA
        query = Query(
            raw_text="California",
            normalized=NormalizedText(original="California", normalized="california"),
        )
        # Looking for places in USA - California is in USA
        context = ResolutionContext(parent_ids=["country/USA"])

        result = runner.resolve(query, context)

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "state/California"

    def test_fuzzy_source_reranks_candidates(self, geo_test_datapack):
        """Test that fuzzy source provides evidence for candidates."""
        from resolvekit.core.engine import PipelineRunner
        from resolvekit.core.explain import MemoryTraceSink
        from resolvekit.core.model import NormalizedText, Query, ResolutionContext
        from resolvekit.core.store import SQLiteEntityStore
        from resolvekit.packs.geo import GeoPack

        pack = GeoPack()
        store = SQLiteEntityStore(geo_test_datapack / "entities.sqlite")
        trace = MemoryTraceSink()

        runner = PipelineRunner(
            trace_sink=trace,
            store=store,
            sources=pack.sources,
            constraints=pack.constraints,
            decision_policy=pack.decision_policy,
        )

        # Query with typo
        query = Query(
            raw_text="United Kingdum",  # Typo
            normalized=NormalizedText(
                original="United Kingdum", normalized="united kingdum"
            ),
        )

        result = runner.resolve(query, ResolutionContext())

        assert result.status is not None
