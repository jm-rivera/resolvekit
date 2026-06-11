"""Tests for GeoFTSSource."""


class TestGeoFTSSource:
    """Tests for GeoFTSSource."""

    def test_source_properties(self):
        from resolvekit.packs.geo.sources.fts import GeoFTSSource

        source = GeoFTSSource()
        assert source.name == "geo_fts"
        assert source.supports("geo") is True

    def test_generates_ranked_evidence(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.sources.fts import GeoFTSSource

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                if "united" in query_norm:
                    return [
                        ("country/USA", 15.5, 1),
                        ("country/GBR", 10.2, 2),
                    ]
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        source = GeoFTSSource()
        query = Query(
            raw_text="United",
            normalized=NormalizedText(original="United", normalized="united"),
        )

        ctx = GenerationContext(
            query=query,
            context=ResolutionContext(),
            store=MockStore(),
            budget=10,
            trace=NullTraceSink(),
        )
        evidence = source.generate(ctx)

        assert len(evidence) == 2
        assert evidence[0].source_name == "geo_fts"
        assert evidence[0].rank == 1
        assert evidence[0].raw_score > evidence[1].raw_score

    def test_skips_short_queries(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.sources.fts import GeoFTSSource

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                # Should not be called for short queries
                return [("should/not/appear", 10.0, 1)]

            def bulk_get_entities(self, entity_ids):
                return {}

        source = GeoFTSSource()
        query = Query(
            raw_text="A",
            normalized=NormalizedText(original="A", normalized="a"),
        )

        ctx = GenerationContext(
            query=query,
            context=ResolutionContext(),
            store=MockStore(),
            budget=10,
            trace=NullTraceSink(),
        )
        evidence = source.generate(ctx)

        assert len(evidence) == 0

    def test_skips_code_like_queries(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.sources.fts import GeoFTSSource

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                raise AssertionError("code-like query should bypass geo FTS")

            def bulk_get_entities(self, entity_ids):
                return {}

        source = GeoFTSSource()
        query = Query(
            raw_text="wikidata:Q35",
            normalized=NormalizedText(
                original="wikidata:Q35", normalized="wikidata:q35"
            ),
        )

        ctx = GenerationContext(
            query=query,
            context=ResolutionContext(),
            store=MockStore(),
            budget=10,
            trace=NullTraceSink(),
        )
        evidence = source.generate(ctx)

        assert len(evidence) == 0
