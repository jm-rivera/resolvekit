"""Integration tests for org resolution."""

import sqlite3

import pytest


@pytest.fixture
def org_test_db(tmp_path):
    """Create test database with org data."""
    db_path = tmp_path / "org_test.db"
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

        -- Test orgs
        INSERT INTO entities VALUES
            ('org/EU', 'org.igo', 'European Union', 'european union', NULL, NULL),
            ('org/WorldBank', 'org.igo', 'World Bank', 'world bank', NULL, NULL),
            ('org/IDA', 'org.igo', 'International Development Association', 'international development association', NULL, NULL),
            ('org/IBRD', 'org.igo', 'International Bank for Reconstruction and Development', 'international bank for reconstruction and development', NULL, NULL);

        INSERT INTO names VALUES
            ('org/EU', 'canonical', 'European Union', 'european union', 'en', 1),
            ('org/EU', 'acronym', 'EU', 'eu', 'en', 0),
            ('org/WorldBank', 'canonical', 'World Bank', 'world bank', 'en', 1),
            ('org/WorldBank', 'short', 'World Bank', 'world bank', 'en', 0),
            ('org/IDA', 'canonical', 'International Development Association', 'international development association', 'en', 1),
            ('org/IDA', 'acronym', 'IDA', 'ida', 'en', 0),
            ('org/IBRD', 'canonical', 'International Bank for Reconstruction and Development', 'international bank for reconstruction and development', 'en', 1),
            ('org/IBRD', 'acronym', 'IBRD', 'ibrd', 'en', 0);

        INSERT INTO codes VALUES
            ('org/EU', 'wikidata', 'Q458', 'q458');

        INSERT INTO relations VALUES
            ('org/IDA', 'subsidiary_of', 'org/WorldBankGroup'),
            ('org/IBRD', 'subsidiary_of', 'org/WorldBankGroup');

        INSERT INTO names_fts(entity_id, value_norm) VALUES
            ('org/EU', 'european union'),
            ('org/EU', 'eu'),
            ('org/WorldBank', 'world bank'),
            ('org/IDA', 'international development association'),
            ('org/IDA', 'ida'),
            ('org/IBRD', 'international bank for reconstruction and development'),
            ('org/IBRD', 'ibrd');
    """
    )

    conn.commit()
    conn.close()
    return db_path


class TestOrgIntegration:
    """Full pipeline integration tests for orgs."""

    def test_resolve_eu_by_acronym(self, org_test_db):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import SQLiteEntityStore
        from resolvekit.packs.org import OrgPack

        pack = OrgPack()
        store = SQLiteEntityStore(org_test_db)
        trace = NullTraceSink()

        # Test the acronym source directly
        source = pack.get_source("org_acronym")
        assert source is not None
        query = Query(
            raw_text="EU",
            normalized=NormalizedText(original="EU", normalized="eu"),
        )

        ctx = GenerationContext(
            query=query,
            context=ResolutionContext(),
            store=store,
            budget=10,
            trace=trace,
        )
        evidence = source.generate(ctx)

        assert len(evidence) >= 1
        assert evidence[0].entity_id == "org/EU"

    def test_resolve_world_bank_by_name(self, org_test_db):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import SQLiteEntityStore
        from resolvekit.packs.org import OrgPack

        pack = OrgPack()
        store = SQLiteEntityStore(org_test_db)
        trace = NullTraceSink()

        # Test exact name source
        source = pack.get_source("org_exact_name")
        assert source is not None
        query = Query(
            raw_text="World Bank",
            normalized=NormalizedText(original="World Bank", normalized="world bank"),
        )

        ctx = GenerationContext(
            query=query,
            context=ResolutionContext(),
            store=store,
            budget=10,
            trace=trace,
        )
        evidence = source.generate(ctx)

        assert len(evidence) >= 1
        assert evidence[0].entity_id == "org/WorldBank"

    def test_resolve_ibrd_by_acronym(self, org_test_db):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import SQLiteEntityStore
        from resolvekit.packs.org import OrgPack

        pack = OrgPack()
        store = SQLiteEntityStore(org_test_db)
        trace = NullTraceSink()

        # Test acronym source for IBRD
        source = pack.get_source("org_acronym")
        assert source is not None
        query = Query(
            raw_text="IBRD",
            normalized=NormalizedText(original="IBRD", normalized="ibrd"),
        )

        ctx = GenerationContext(
            query=query,
            context=ResolutionContext(),
            store=store,
            budget=10,
            trace=trace,
        )
        evidence = source.generate(ctx)

        assert len(evidence) >= 1
        assert evidence[0].entity_id == "org/IBRD"

    def test_fts_finds_partial_match(self, org_test_db):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import SQLiteEntityStore
        from resolvekit.packs.org import OrgPack

        pack = OrgPack()
        store = SQLiteEntityStore(org_test_db)
        trace = NullTraceSink()

        # Test FTS source
        source = pack.get_source("org_fts")
        assert source is not None
        query = Query(
            raw_text="European",
            normalized=NormalizedText(original="European", normalized="european"),
        )

        ctx = GenerationContext(
            query=query,
            context=ResolutionContext(),
            store=store,
            budget=10,
            trace=trace,
        )
        evidence = source.generate(ctx)

        assert len(evidence) >= 1
        assert evidence[0].entity_id == "org/EU"

    def test_exact_code_by_wikidata(self, org_test_db):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import SQLiteEntityStore
        from resolvekit.packs.org import OrgPack

        pack = OrgPack()
        store = SQLiteEntityStore(org_test_db)
        trace = NullTraceSink()

        # Test exact code source
        source = pack.get_source("org_exact_code")
        assert source is not None
        query = Query(
            raw_text="Q458",
            normalized=NormalizedText(original="Q458", normalized="q458"),
        )

        ctx = GenerationContext(
            query=query,
            context=ResolutionContext(),
            store=store,
            budget=10,
            trace=trace,
        )
        evidence = source.generate(ctx)

        assert len(evidence) >= 1
        assert evidence[0].entity_id == "org/EU"

    def test_pack_imports_correctly(self):
        """Test that OrgPack can be imported and instantiated."""
        from resolvekit.packs.org import OrgPack

        pack = OrgPack()
        assert pack.pack_id == "org"
        assert len(pack.sources) == 6
        assert len(pack.constraints) == 4
        assert pack.decision_policy is not None

    def test_acronym_query_resolves_through_source(self, org_test_db):
        """Characterization: uppercase acronym resolves via OrgAcronymSource; lowercase yields nothing.

        Anchors that the resolution-side source gate (_is_acronym_like on
        original text) accepts fully-uppercase input and rejects fully-lowercase
        input. If the source gate behavior changes to accept lowercase, the
        second assertion flags it as an intentional delta.
        """
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import SQLiteEntityStore
        from resolvekit.packs.org import OrgPack

        pack = OrgPack()
        store = SQLiteEntityStore(org_test_db)
        source = pack.get_source("org_acronym")
        assert source is not None

        # Uppercase "IBRD" — source gate accepts, result found
        query_upper = Query(
            raw_text="IBRD",
            normalized=NormalizedText(original="IBRD", normalized="ibrd"),
        )
        ctx_upper = GenerationContext(
            query=query_upper,
            context=ResolutionContext(),
            store=store,
            budget=10,
            trace=NullTraceSink(),
        )
        evidence_upper = source.generate(ctx_upper)
        assert len(evidence_upper) >= 1
        assert evidence_upper[0].entity_id == "org/IBRD"

        # Lowercase "ibrd" — source gate rejects (upper_ratio 0.0 < 0.5) → no evidence today
        query_lower = Query(
            raw_text="ibrd",
            normalized=NormalizedText(original="ibrd", normalized="ibrd"),
        )
        ctx_lower = GenerationContext(
            query=query_lower,
            context=ResolutionContext(),
            store=store,
            budget=10,
            trace=NullTraceSink(),
        )
        evidence_lower = source.generate(ctx_lower)
        assert len(evidence_lower) == 0  # source gate rejects fully-lowercase on HEAD
