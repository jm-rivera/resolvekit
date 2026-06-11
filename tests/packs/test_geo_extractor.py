"""Tests for GeoFeatureExtractor."""

from resolvekit.core.explain import NullTraceSink
from resolvekit.core.model import (
    Candidate,
    CandidateEvidence,
    NormalizedText,
    Query,
    ResolutionContext,
    RetrievalSummary,
    ScoreSummary,
)
from resolvekit.core.model.entity import EntityRecord
from resolvekit.core.store import EntityStore
from resolvekit.packs.geo.extractor import GeoFeatureExtractor


def _make_store(entity: EntityRecord | None) -> EntityStore:
    class MockStore(EntityStore):
        def get_entity(self, entity_id):
            return entity

        def lookup_code(self, system, value_norm):
            return []

        def lookup_name_exact(self, value_norm, name_kinds=None):
            return []

        def search_fulltext(self, query_norm, fields=None, limit=10):
            return []

        def bulk_get_entities(self, entity_ids):
            return {}

    return MockStore()


def _make_candidate(entity_id: str = "country/USA") -> Candidate:
    return Candidate(
        entity_id=entity_id,
        sources=[
            CandidateEvidence(
                entity_id=entity_id, source_name="geo_exact_name", raw_score=1.0
            )
        ],
        retrieval=RetrievalSummary(best_source="geo_exact_name"),
        scores=ScoreSummary(raw_score=0.90, calibrated_score=0.90),
    )


def _make_query(text: str = "USA") -> Query:
    return Query(
        raw_text=text,
        normalized=NormalizedText(original=text, normalized=text.lower()),
    )


class TestGeoFeatureExtractor:
    def test_schema_version(self):
        from resolvekit.packs.geo.extractor import GeoFeatureExtractor

        extractor = GeoFeatureExtractor()
        assert extractor.schema_version == "geo.features.v1"

    def test_extracts_exact_code_feature(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            Candidate,
            CandidateEvidence,
            NormalizedText,
            Query,
            ResolutionContext,
            RetrievalSummary,
            ScoreSummary,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.extractor import GeoFeatureExtractor

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        extractor = GeoFeatureExtractor()
        query = Query(
            raw_text="US",
            normalized=NormalizedText(original="US", normalized="us"),
        )
        candidate = Candidate(
            entity_id="country/USA",
            sources=[
                CandidateEvidence(
                    entity_id="country/USA", source_name="geo_exact_code", raw_score=1.0
                )
            ],
            retrieval=RetrievalSummary(best_source="geo_exact_code"),
            scores=ScoreSummary(raw_score=0.95, calibrated_score=0.95),
        )

        features = extractor.extract(
            query, ResolutionContext(), candidate, MockStore(), NullTraceSink()
        )

        assert features.exact_code_hit is True
        assert features.query_len == 2
        assert features.query_is_upper is True

    def test_extracts_fts_features(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            Candidate,
            CandidateEvidence,
            NormalizedText,
            Query,
            ResolutionContext,
            RetrievalSummary,
            ScoreSummary,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.extractor import GeoFeatureExtractor

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        extractor = GeoFeatureExtractor()
        query = Query(
            raw_text="United States",
            normalized=NormalizedText(
                original="United States", normalized="united states"
            ),
        )
        candidate = Candidate(
            entity_id="country/USA",
            sources=[
                CandidateEvidence(
                    entity_id="country/USA",
                    source_name="geo_fts",
                    raw_score=0.85,
                    rank=1,
                )
            ],
            retrieval=RetrievalSummary(best_source="geo_fts", best_rank=1),
            scores=ScoreSummary(raw_score=0.85, calibrated_score=0.85),
        )

        features = extractor.extract(
            query, ResolutionContext(), candidate, MockStore(), NullTraceSink()
        )

        assert features.exact_code_hit is False
        assert features.fts_bm25_norm == 0.85
        assert features.retrieval_rank_inv == 1.0


class TestGeoFeatureExtractorProminence:
    """Tests that the extractor reads entity.attributes["prominence"] correctly."""

    def test_prominence_float_passthrough(self):
        entity = EntityRecord(
            entity_id="country/USA",
            entity_type="geo.country",
            canonical_name="United States",
            canonical_name_norm="united states",
            attributes={"prominence": 0.8},
        )
        extractor = GeoFeatureExtractor()
        features = extractor.extract(
            _make_query(),
            ResolutionContext(),
            _make_candidate(),
            _make_store(entity),
            NullTraceSink(),
        )
        assert features.candidate_prominence == 0.8

    def test_prominence_int_coerced_to_float(self):
        entity = EntityRecord(
            entity_id="country/USA",
            entity_type="geo.country",
            canonical_name="United States",
            canonical_name_norm="united states",
            attributes={"prominence": 1},
        )
        extractor = GeoFeatureExtractor()
        features = extractor.extract(
            _make_query(),
            ResolutionContext(),
            _make_candidate(),
            _make_store(entity),
            NullTraceSink(),
        )
        assert features.candidate_prominence == 1.0

    def test_prominence_missing_key_is_none(self):
        entity = EntityRecord(
            entity_id="country/USA",
            entity_type="geo.country",
            canonical_name="United States",
            canonical_name_norm="united states",
            attributes={},
        )
        extractor = GeoFeatureExtractor()
        features = extractor.extract(
            _make_query(),
            ResolutionContext(),
            _make_candidate(),
            _make_store(entity),
            NullTraceSink(),
        )
        assert features.candidate_prominence is None

    def test_prominence_no_entity_is_none(self):
        extractor = GeoFeatureExtractor()
        features = extractor.extract(
            _make_query(),
            ResolutionContext(),
            _make_candidate(),
            _make_store(None),
            NullTraceSink(),
        )
        assert features.candidate_prominence is None
