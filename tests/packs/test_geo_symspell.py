"""Tests for GeoSymSpellSource."""

import tempfile
from pathlib import Path


class TestGeoSymSpellSource:
    def test_source_properties(self):
        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        source = GeoSymSpellSource()
        assert source.name == "geo_symspell"
        assert source.supports("geo") is True
        assert source.supports("org") is False

    def test_finds_with_prefix_search_fallback(self):
        """When no dictionary is provided, falls back to prefix search."""
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

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

            def search_prefix(self, query_norm, field, limit=10):
                # Simulate prefix search finding "united states" from "unti"
                if query_norm.startswith("unti"):
                    return [("country/USA", 1.0, 1)]
                return []

        source = GeoSymSpellSource()  # No dictionary path
        query = Query(
            raw_text="Untied States",  # Typo - but prefix "unti" matches
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

        # Should find candidates via prefix search fallback
        assert len(evidence) == 1
        assert evidence[0].entity_id == "country/USA"
        assert evidence[0].source_name == "geo_symspell"

    def test_skips_short_queries(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

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

            def search_prefix(self, query_norm, field, limit=10):
                # Should NOT be called for short queries
                return [("should/not/reach", 1.0, 1)]

        source = GeoSymSpellSource()
        query = Query(
            raw_text="US",  # Too short - should skip
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

        # Should skip and return empty
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
        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

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

            def search_prefix(self, query_norm, field, limit=10):
                raise AssertionError("code-like query should bypass symspell fallback")

        source = GeoSymSpellSource()
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

    def test_respects_budget_limit(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

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

            def search_prefix(self, query_norm, field, limit=10):
                # Return only up to limit results
                all_results = [
                    ("country/USA", 1.0, 1),
                    ("country/GBR", 0.9, 2),
                    ("country/CAN", 0.8, 3),
                ]
                return all_results[:limit]

        source = GeoSymSpellSource()
        query = Query(
            raw_text="United",
            normalized=NormalizedText(original="United", normalized="united"),
        )

        # Budget of 2 should limit results (budget is passed to store)
        ctx = GenerationContext(
            query=query,
            context=ResolutionContext(),
            store=MockStore(),
            budget=2,
            trace=NullTraceSink(),
        )
        evidence = source.generate(ctx)

        assert len(evidence) == 2

    def test_applies_discount_to_prefix_scores(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

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

            def search_prefix(self, query_norm, field, limit=10):
                return [("country/USA", 1.0, 1)]  # Base score 1.0

        source = GeoSymSpellSource()
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

        # Score should be discounted (less than 1.0)
        assert len(evidence) == 1
        assert evidence[0].raw_score < 1.0


class TestGeoSymSpellSourceWithDictionary:
    def test_loads_dictionary_from_file(self):
        """Test dictionary loading from a file (lazy — built on first use)."""
        pytest = __import__("pytest")
        try:
            import symspellpy  # noqa: F401
        except ImportError:
            pytest.skip("symspellpy not installed")

        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        # Create a temporary dictionary file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as dict_file:
            dict_file.write("united states\t1000000\n")
            dict_file.write("united kingdom\t500000\n")
            dict_file.write("canada\t400000\n")
            dict_path = dict_file.name

        try:
            source = GeoSymSpellSource(dictionary_path=dict_path)
            # Index is lazy — not built at construction time.
            assert source._sym_spell is None
            source._ensure_built()
            assert source._sym_spell is not None
        finally:
            Path(dict_path).unlink()

    def test_typo_correction_with_edit_distance_scoring(self):
        """Test typo correction returns results with edit-distance-based scores."""
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
        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        # Create a temporary dictionary file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as dict_file:
            dict_file.write("united states\t1000000\n")
            dict_file.write("united kingdom\t500000\n")
            dict_path = dict_file.name

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                if value_norm == "united states":
                    return ["country/USA"]
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

            def search_prefix(self, query_norm, field, limit=10):
                return []

        try:
            source = GeoSymSpellSource(dictionary_path=dict_path)
            # Query with typo: "untied" instead of "united"
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

            # Should find "united states" via typo correction. Distance-1
            # corrections to indexed exact-name terms emit two evidence records:
            # the standard symspell hit plus a promoted exact_name hit.
            assert len(evidence) == 2
            assert all(ev.entity_id == "country/USA" for ev in evidence)
            assert all(ev.matched_value == "united states" for ev in evidence)
            # Score should be based on edit distance (distance 1 -> 0.9 - 0.15 = 0.75)
            assert all(0.7 <= ev.raw_score <= 0.8 for ev in evidence)
            source_names = {ev.source_name for ev in evidence}
            assert "geo_symspell" in source_names
            assert any(name.endswith("exact_name") for name in source_names)
        finally:
            Path(dict_path).unlink()

    def test_respects_edit_distance_limit(self):
        """Test that max edit distance is respected."""
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
        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        # Create a temporary dictionary file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as dict_file:
            dict_file.write("united states\t1000000\n")
            dict_path = dict_file.name

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                if value_norm == "united states":
                    return ["country/USA"]
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

            def search_prefix(self, query_norm, field, limit=10):
                return []

        try:
            # Max edit distance of 1
            source = GeoSymSpellSource(dictionary_path=dict_path, max_edit_distance=1)

            # Query with 1 edit distance: "untied" (swap t and i)
            query_close = Query(
                raw_text="Untied States",
                normalized=NormalizedText(
                    original="Untied States", normalized="untied states"
                ),
            )
            ctx_close = GenerationContext(
                query=query_close,
                context=ResolutionContext(),
                store=MockStore(),
                budget=10,
                trace=NullTraceSink(),
            )
            evidence_close = source.generate(ctx_close)
            # Should find it (1 edit) — emits both a symspell and a promoted
            # exact_name evidence record because the corrected term is an
            # indexed exact-name match.
            assert len(evidence_close) == 2
            assert all(ev.entity_id == "country/USA" for ev in evidence_close)

            # Query with 3+ edit distance: very different
            query_far = Query(
                raw_text="Xyzabc States",
                normalized=NormalizedText(
                    original="Xyzabc States", normalized="xyzabc states"
                ),
            )
            ctx_far = GenerationContext(
                query=query_far,
                context=ResolutionContext(),
                store=MockStore(),
                budget=10,
                trace=NullTraceSink(),
            )
            evidence_far = source.generate(ctx_far)
            # Should NOT find it (too many edits)
            assert len(evidence_far) == 0
        finally:
            Path(dict_path).unlink()

    def test_skips_when_correction_equals_original(self):
        """Test that exact matches (no typo) are skipped."""
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
        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        # Create a temporary dictionary file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as dict_file:
            dict_file.write("united states\t1000000\n")
            dict_path = dict_file.name

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                if value_norm == "united states":
                    return ["country/USA"]
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

            def search_prefix(self, query_norm, field, limit=10):
                return []

        try:
            source = GeoSymSpellSource(dictionary_path=dict_path)
            # Query with exact match (no typo)
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

            # Should return empty - exact match should be handled by exact sources
            assert len(evidence) == 0
        finally:
            Path(dict_path).unlink()

    def test_graceful_fallback_when_symspellpy_not_available(self):
        """Fallback to prefix search when the index can't be built (no dict/symspellpy)."""
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

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

            def search_prefix(self, query_norm, field, limit=10):
                return [("country/USA", 0.9, 1)]

        # No dictionary path → lazy build produces no SymSpell instance →
        # generate() uses the prefix-search fallback.
        source = GeoSymSpellSource(dictionary_path=None)

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

        # Should fall back to prefix search
        assert len(evidence) == 1
        assert evidence[0].entity_id == "country/USA"

    def test_load_dictionary_method(self):
        """load_dictionary() queues a path; index is built on first _ensure_built()."""
        pytest = __import__("pytest")
        try:
            import symspellpy  # noqa: F401
        except ImportError:
            pytest.skip("symspellpy not installed")

        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        # Create a temporary dictionary file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as dict_file:
            dict_file.write("test term\t100\n")
            dict_path = dict_file.name

        try:
            # Start without dictionary
            source = GeoSymSpellSource()
            assert source._sym_spell is None

            # Register a dictionary path (lazy — not built yet)
            source.load_dictionary(dict_path)
            assert source._sym_spell is None  # still lazy

            # Trigger the build
            source._ensure_built()
            assert source._sym_spell is not None
        finally:
            Path(dict_path).unlink()

    def test_tab_separated_dictionary(self):
        """Test loading tab-separated dictionary file (lazy build)."""
        pytest = __import__("pytest")
        try:
            import symspellpy  # noqa: F401
        except ImportError:
            pytest.skip("symspellpy not installed")

        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        # Create a tab-separated dictionary file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as dict_file:
            dict_file.write("united states\t1000000\n")
            dict_file.write("canada\t500000\n")
            dict_path = dict_file.name

        try:
            source = GeoSymSpellSource(dictionary_path=dict_path)
            source._ensure_built()
            assert source._sym_spell is not None
            # Verify lookup works
            from symspellpy import Verbosity

            suggestions = source._sym_spell.lookup(
                "united states", Verbosity.CLOSEST, max_edit_distance=2
            )
            assert len(suggestions) > 0
            assert suggestions[0].term == "united states"
        finally:
            Path(dict_path).unlink()

    def test_compound_lookup_fallback_for_multiword_typos(self):
        """Test that lookup_compound is used as fallback for multi-word queries."""
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
        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        # Dictionary contains individual words so lookup_compound can correct
        # each word independently. "untied" -> "united", "staets" -> "states".
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as dict_file:
            dict_file.write("united\t1000000\n")
            dict_file.write("states\t1000000\n")
            dict_path = dict_file.name

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                if value_norm == "united states":
                    return ["country/USA"]
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

            def search_prefix(self, query_norm, field, limit=10):
                return []

        try:
            source = GeoSymSpellSource(dictionary_path=dict_path)

            # "untied staets" has per-word typos that together exceed
            # max_edit_distance=2 for lookup(), so only lookup_compound() can fix it.
            query = Query(
                raw_text="Untied Staets",
                normalized=NormalizedText(
                    original="Untied Staets", normalized="untied staets"
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

            # Should find "united states" via lookup_compound fallback
            assert len(evidence) == 1
            assert evidence[0].entity_id == "country/USA"
            assert evidence[0].matched_value == "united states"
            assert evidence[0].source_name == "geo_symspell"
        finally:
            Path(dict_path).unlink()

    def test_space_separated_dictionary(self):
        """Test loading space-separated dictionary file with multi-word terms (lazy)."""
        pytest = __import__("pytest")
        try:
            import symspellpy  # noqa: F401
        except ImportError:
            pytest.skip("symspellpy not installed")

        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        # Create a space-separated dictionary file with multi-word terms
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as dict_file:
            dict_file.write("world bank 500000\n")  # Multi-word term
            dict_file.write("european union 400000\n")  # Multi-word term
            dict_file.write("canada 300000\n")  # Single-word term
            dict_path = dict_file.name

        try:
            source = GeoSymSpellSource(dictionary_path=dict_path)
            source._ensure_built()
            assert source._sym_spell is not None
            from symspellpy import Verbosity

            # Verify multi-word lookup works
            suggestions = source._sym_spell.lookup(
                "world bank", Verbosity.CLOSEST, max_edit_distance=2
            )
            assert len(suggestions) > 0
            assert suggestions[0].term == "world bank"

            # Verify another multi-word term
            suggestions = source._sym_spell.lookup(
                "european union", Verbosity.CLOSEST, max_edit_distance=2
            )
            assert len(suggestions) > 0
            assert suggestions[0].term == "european union"

            # Verify single-word term still works
            suggestions = source._sym_spell.lookup(
                "canada", Verbosity.CLOSEST, max_edit_distance=2
            )
            assert len(suggestions) > 0
            assert suggestions[0].term == "canada"
        finally:
            Path(dict_path).unlink()
