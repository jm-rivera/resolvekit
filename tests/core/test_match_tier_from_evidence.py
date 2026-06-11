"""Tests: emitted CandidateEvidence carries expected match_tier.

Each test exercises a source's generate() with a minimal mock store and asserts
that every returned evidence record's match_tier matches the expected tier
for that source.
"""

from resolvekit.core.engine.tier_utils import REASON_TO_MATCH_TIER
from resolvekit.core.model import (
    GenerationContext,
    MatchTier,
    NormalizedText,
    Query,
    ReasonCode,
    ResolutionContext,
)
from tests.conftest import MockEntityStore


def _ctx(
    query: Query,
    store: MockEntityStore,
    context: ResolutionContext | None = None,
    *,
    null_trace,
) -> GenerationContext:

    return GenerationContext(
        query=query,
        context=context or ResolutionContext(),
        store=store,
        budget=10,
        trace=null_trace,
    )


def _make_query(text: str, normalized: str | None = None) -> Query:
    norm = normalized if normalized is not None else text.lower()
    return Query(
        raw_text=text,
        normalized=NormalizedText(original=text, normalized=norm),
    )


class TestGeoExactCodeTier:
    """geo_exact_code stamps MatchTier.EXACT_CODE on every evidence record."""

    def test_evidence_has_exact_code_tier(self, null_trace):
        from resolvekit.packs.geo.sources.exact_code import GeoExactCodeSource

        store = MockEntityStore(codes={("iso2", "us"): ["country/USA"]})
        source = GeoExactCodeSource()
        query = _make_query("US")

        evidence = source.generate(_ctx(query, store, null_trace=null_trace))

        assert len(evidence) >= 1
        for ev in evidence:
            assert ev.match_tier == MatchTier.EXACT_CODE, (
                f"Expected EXACT_CODE on {ev.source_name}, got {ev.match_tier}"
            )


class TestGeoFTSTier:
    """geo_fts stamps MatchTier.FTS on every evidence record."""

    def test_evidence_has_fts_tier(self, null_trace):
        from resolvekit.core.model import EntityRecord
        from resolvekit.packs.geo.sources.fts import GeoFTSSource

        class FTSMockStore(MockEntityStore):
            def search_fulltext(self, query_norm, fields=None, limit=10):
                return [("country/USA", -1.5, 1)]

            def get_entity(self, entity_id):
                return EntityRecord(
                    entity_id="country/USA",
                    entity_type="geo.country",
                    canonical_name="United States",
                    canonical_name_norm="united states",
                )

        source = GeoFTSSource()
        query = _make_query("United States", "united states")

        evidence = source.generate(_ctx(query, FTSMockStore(), null_trace=null_trace))

        assert len(evidence) >= 1
        expected_tier = REASON_TO_MATCH_TIER.get(ReasonCode.FTS_MATCH)
        for ev in evidence:
            assert ev.match_tier == expected_tier, (
                f"Expected {expected_tier} on {ev.source_name}, got {ev.match_tier}"
            )


class TestGeoFuzzyTier:
    """geo_fuzzy stamps MatchTier.FUZZY on every evidence record."""

    def test_evidence_has_fuzzy_tier(self, null_trace):
        from resolvekit.core.model import (
            Candidate,
            CandidateEvidence,
            EntityRecord,
            RetrievalSummary,
            ScoreSummary,
        )
        from resolvekit.packs.geo.sources.fuzzy import GeoFuzzySource

        class FuzzyMockStore(MockEntityStore):
            def get_entity(self, entity_id):
                return EntityRecord(
                    entity_id="country/USA",
                    entity_type="geo.country",
                    canonical_name="United States",
                    canonical_name_norm="united states",
                )

            def bulk_get_entities(self, entity_ids):
                return {eid: self.get_entity(eid) for eid in entity_ids}

        existing = [
            Candidate(
                entity_id="country/USA",
                sources=[
                    CandidateEvidence(
                        entity_id="country/USA",
                        source_name="geo_fts",
                        raw_score=0.7,
                    )
                ],
                retrieval=RetrievalSummary(best_source="geo_fts"),
                scores=ScoreSummary(raw_score=0.7, calibrated_score=0.7),
            )
        ]

        source = GeoFuzzySource()
        query = _make_query("United Sates", "united sates")

        ctx = GenerationContext(
            query=query,
            context=ResolutionContext(),
            store=FuzzyMockStore(),
            budget=10,
            trace=null_trace,
            existing_candidates=existing,
        )
        evidence = source.generate(ctx)

        assert len(evidence) >= 1
        expected_tier = REASON_TO_MATCH_TIER.get(ReasonCode.FUZZY_MATCH)
        for ev in evidence:
            assert ev.match_tier == expected_tier, (
                f"Expected {expected_tier} on {ev.source_name}, got {ev.match_tier}"
            )


class TestOrgAcronymTier:
    """org_acronym stamps MatchTier.ACRONYM on every evidence record."""

    def test_evidence_has_acronym_tier(self, null_trace):
        from resolvekit.packs.org.sources.acronym import OrgAcronymSource

        store = MockEntityStore(names={"eu": ["org/EU"]})
        source = OrgAcronymSource()
        query = _make_query("EU")

        evidence = source.generate(_ctx(query, store, null_trace=null_trace))

        assert len(evidence) >= 1
        expected_tier = REASON_TO_MATCH_TIER.get(ReasonCode.ACRONYM_MATCH)
        for ev in evidence:
            assert ev.match_tier == expected_tier, (
                f"Expected {expected_tier} on {ev.source_name}, got {ev.match_tier}"
            )


class TestOrgFTSTier:
    """org_fts stamps MatchTier.FTS on every evidence record."""

    def test_evidence_has_fts_tier(self, null_trace):
        from resolvekit.core.model import EntityRecord
        from resolvekit.packs.org.sources.fts import OrgFTSSource

        class OrgFTSMockStore(MockEntityStore):
            def search_fulltext(self, query_norm, fields=None, limit=10):
                return [("org/WorldBank", -1.5, 1)]

            def get_entity(self, entity_id):
                return EntityRecord(
                    entity_id="org/WorldBank",
                    entity_type="org.igo",
                    canonical_name="World Bank",
                    canonical_name_norm="world bank",
                )

        source = OrgFTSSource()
        query = _make_query("World Bank", "world bank")

        evidence = source.generate(
            _ctx(query, OrgFTSMockStore(), null_trace=null_trace)
        )

        assert len(evidence) >= 1
        expected_tier = REASON_TO_MATCH_TIER.get(ReasonCode.FTS_MATCH)
        for ev in evidence:
            assert ev.match_tier == expected_tier, (
                f"Expected {expected_tier} on {ev.source_name}, got {ev.match_tier}"
            )


class TestGeoSymSpellSyntheticExactNameTier:
    """geo_symspell_exact_name synthetic evidence stamps MatchTier.EXACT_NAME."""

    def test_synthetic_evidence_has_exact_name_tier(self, null_trace):
        """When SymSpell correction matches exact name, synthetic evidence is EXACT_NAME."""
        import pytest

        pytest.importorskip("symspellpy")

        import os
        import tempfile

        from resolvekit.core.model import EntityRecord
        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("france\t100\n")
            dict_path = f.name

        try:

            class SymSpellMockStore(MockEntityStore):
                def lookup_name_exact(self, value_norm, name_kinds=None):
                    if value_norm == "france":
                        return ["country/FRA"]
                    return []

                def get_entity(self, entity_id):
                    return EntityRecord(
                        entity_id="country/FRA",
                        entity_type="geo.country",
                        canonical_name="France",
                        canonical_name_norm="france",
                    )

            source = GeoSymSpellSource(dictionary_path=dict_path)
            query = _make_query("Frannce", "frannce")
            ctx = _ctx(query, SymSpellMockStore(), null_trace=null_trace)

            evidence = source.generate(ctx)

            # Find the synthetic exact-name evidence
            exact_name_ev = [
                ev for ev in evidence if ev.source_name == "geo_symspell_exact_name"
            ]
            assert len(exact_name_ev) >= 1, (
                "Expected geo_symspell_exact_name synthetic evidence"
            )
            for ev in exact_name_ev:
                assert ev.match_tier == MatchTier.EXACT_NAME, (
                    f"Expected EXACT_NAME on synthetic evidence, got {ev.match_tier}"
                )
        finally:
            os.unlink(dict_path)
