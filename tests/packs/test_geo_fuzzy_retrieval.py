"""Tests for GeoFuzzyRetrievalSource."""

import tempfile
from pathlib import Path


class TestGeoFuzzyRetrievalSource:
    """Tests for the fuzzy retrieval (independent candidate generation) source."""

    def test_source_properties(self):
        from resolvekit.packs.geo.sources.fuzzy_retrieval import GeoFuzzyRetrievalSource

        source = GeoFuzzyRetrievalSource()
        assert source.name == "geo_fuzzy_retrieval"
        assert source.supports("geo") is True
        assert source.supports("org") is False

    def test_requires_existing_candidates_is_false(self):
        """Source must be a true retrieval source, not a reranker."""
        from resolvekit.packs.geo.sources.fuzzy_retrieval import GeoFuzzyRetrievalSource

        source = GeoFuzzyRetrievalSource()
        assert source.requires_existing_candidates is False

    def test_no_dict_returns_empty(self):
        """When no SymSpell dictionary is provided, generate returns empty list."""
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.sources.fuzzy_retrieval import GeoFuzzyRetrievalSource

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

        source = GeoFuzzyRetrievalSource()  # No dictionary path
        assert source._sym_spell is None

        query = Query(
            raw_text="Untied States",
            normalized=NormalizedText(
                original="Untied States", normalized="untied states"
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
        assert evidence == []

    def test_short_query_returns_empty(self):
        """Queries shorter than min_query_length are skipped."""
        pytest = __import__("pytest")
        try:
            import symspellpy  # noqa: F401
        except ImportError:
            pytest.skip("symspellpy not installed")

        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.sources.fuzzy_retrieval import GeoFuzzyRetrievalSource

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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("us\t100\n")
            dict_path = f.name

        try:
            source = GeoFuzzyRetrievalSource(dictionary_path=dict_path)
            query = Query(
                raw_text="US",
                normalized=NormalizedText(original="US", normalized="us"),
            )
            ctx = GenerationContext(
                query=query,
                context=ResolutionContext(),
                store=MockStore(),
                budget=10,
                trace=NullTraceSink(),
            )
            evidence = source.generate(ctx)
            assert evidence == []
        finally:
            Path(dict_path).unlink()

    def test_exact_query_returns_empty(self):
        """When all words correct correctly to themselves, no candidates are returned
        (the corrected phrase equals the original — other sources handle this case)."""
        pytest = __import__("pytest")
        try:
            import symspellpy  # noqa: F401
        except ImportError:
            pytest.skip("symspellpy not installed")

        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.sources.fuzzy_retrieval import GeoFuzzyRetrievalSource

        class MockStore(EntityStore):
            called = False

            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                MockStore.called = True
                return ["country/USA"]

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("united\t1000000\n")
            f.write("states\t1000000\n")
            dict_path = f.name

        try:
            source = GeoFuzzyRetrievalSource(dictionary_path=dict_path)
            query = Query(
                raw_text="United States",
                normalized=NormalizedText(
                    original="United States", normalized="united states"
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
            # Corrected phrase == original phrase => return []
            assert evidence == []
            # Store should NOT have been called since no correction was made
            assert MockStore.called is False
        finally:
            Path(dict_path).unlink()

    def test_typo_query_finds_corrected_entity_via_exact_lookup(self):
        """A typo query corrects words and finds the entity via exact name lookup."""
        pytest = __import__("pytest")
        try:
            import symspellpy  # noqa: F401
        except ImportError:
            pytest.skip("symspellpy not installed")

        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.sources.fuzzy_retrieval import GeoFuzzyRetrievalSource

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                # Only return a match for the corrected phrase
                if value_norm == "united states":
                    return ["country/USA"]
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        # Dictionary contains individual words for per-word correction
        # "untied" -> "united", "states" -> "states"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("united\t1000000\n")
            f.write("states\t1000000\n")
            dict_path = f.name

        try:
            source = GeoFuzzyRetrievalSource(dictionary_path=dict_path)

            query = Query(
                raw_text="Untied States",
                normalized=NormalizedText(
                    original="Untied States", normalized="untied states"
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

            assert len(evidence) == 1
            ev = evidence[0]
            assert ev.entity_id == "country/USA"
            assert ev.source_name == "geo_fuzzy_retrieval"
            assert ev.matched_field == "fuzzy_retrieval"
            assert ev.matched_value == "united states"
            assert ev.raw_score is not None
            assert 0.0 < ev.raw_score <= 1.0
        finally:
            Path(dict_path).unlink()

    def test_typo_query_falls_back_to_fts_when_no_exact_match(self):
        """When exact lookup finds nothing, FTS is tried for the corrected phrase."""
        pytest = __import__("pytest")
        try:
            import symspellpy  # noqa: F401
        except ImportError:
            pytest.skip("symspellpy not installed")

        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.sources.fuzzy_retrieval import GeoFuzzyRetrievalSource

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []  # No exact match

            def search_fulltext(self, query_norm, fields=None, limit=10):
                if "united" in query_norm:
                    return [("country/USA", 0.85, 1)]
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("united\t1000000\n")
            f.write("states\t1000000\n")
            dict_path = f.name

        try:
            source = GeoFuzzyRetrievalSource(dictionary_path=dict_path)

            query = Query(
                raw_text="Untied States",
                normalized=NormalizedText(
                    original="Untied States", normalized="untied states"
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

            assert len(evidence) == 1
            ev = evidence[0]
            assert ev.entity_id == "country/USA"
            assert ev.source_name == "geo_fuzzy_retrieval"
            assert ev.matched_field == "fuzzy_retrieval"
            assert ev.matched_value == "united states"
        finally:
            Path(dict_path).unlink()

    def test_respects_budget(self):
        """Source should not return more candidates than the budget allows."""
        pytest = __import__("pytest")
        try:
            import symspellpy  # noqa: F401
        except ImportError:
            pytest.skip("symspellpy not installed")

        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.sources.fuzzy_retrieval import GeoFuzzyRetrievalSource

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                # Return many matches
                return [f"geo/{i}" for i in range(20)]

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("united\t1000000\n")
            f.write("states\t1000000\n")
            dict_path = f.name

        try:
            source = GeoFuzzyRetrievalSource(dictionary_path=dict_path)

            query = Query(
                raw_text="Untied States",
                normalized=NormalizedText(
                    original="Untied States", normalized="untied states"
                ),
            )
            budget = 5
            ctx = GenerationContext(
                query=query,
                context=ResolutionContext(),
                store=MockStore(),
                budget=budget,
                trace=NullTraceSink(),
            )
            evidence = source.generate(ctx)
            assert len(evidence) <= budget
        finally:
            Path(dict_path).unlink()

    def test_geo_pack_includes_source(self):
        """GeoPack.sources should include GeoFuzzyRetrievalSource."""
        from resolvekit.packs.geo import GeoPack
        from resolvekit.packs.geo.sources.fuzzy_retrieval import GeoFuzzyRetrievalSource

        pack = GeoPack()
        source_types = [type(s) for s in pack.sources]
        assert GeoFuzzyRetrievalSource in source_types

    def test_geo_pack_fuzzy_retrieval_before_fuzzy_reranker(self):
        """GeoFuzzyRetrievalSource must appear before GeoFuzzySource in the pipeline."""
        from resolvekit.packs.geo import GeoPack
        from resolvekit.packs.geo.sources.fuzzy import GeoFuzzySource
        from resolvekit.packs.geo.sources.fuzzy_retrieval import GeoFuzzyRetrievalSource

        pack = GeoPack()
        names = [s.name for s in pack.sources]
        assert "geo_fuzzy_retrieval" in names
        assert "geo_fuzzy" in names
        assert names.index("geo_fuzzy_retrieval") < names.index("geo_fuzzy")

        source_types = [type(s) for s in pack.sources]
        retrieval_idx = source_types.index(GeoFuzzyRetrievalSource)
        reranker_idx = source_types.index(GeoFuzzySource)
        assert retrieval_idx < reranker_idx
