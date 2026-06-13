"""Tests that the LARGE-tier geo SymSpell/fuzzy-retrieval indexes stay lazy under warm().

The LARGE tier covers admin2-5 / cities (~764k terms, ~800 MB heap).  Warming it
eagerly defeats the lazy-by-design contract and hurts country-only workloads that
never need it.  These tests guard that warm() on a large_tier=True source is a
no-op, while the index is still built on demand when generate() reaches it.
"""

import tempfile
from pathlib import Path


def _make_dict_file(terms: list[str]) -> str:
    """Write a tiny tab-separated SymSpell dictionary to a temp file."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        for term in terms:
            f.write(f"{term}\t1000\n")
        return f.name


class MockStore:
    """Minimal EntityStore stand-in for isolation tests."""

    def get_entity(self, entity_id):
        return None

    def lookup_code(self, system, value_norm):
        return []

    def lookup_name_exact(self, value_norm, name_kinds=None):
        # Return a dummy entity so generate() actually produces evidence
        return ["geo/test_entity"]

    def search_fulltext(self, query_norm, fields=None, limit=10):
        return []

    def bulk_get_entities(self, entity_ids):
        return {}

    def search_prefix(self, query_norm, field, limit=10):
        return []


class TestGeoSymSpellLargeTierLazyWarm:
    def test_large_tier_warm_does_not_build_index(self):
        """warm() on large_tier=True must NOT build the SymSpell index."""
        pytest = __import__("pytest")
        try:
            import symspellpy  # noqa: F401
        except ImportError:
            pytest.skip("symspellpy not installed")

        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        dict_path = _make_dict_file(["united states", "canada"])
        try:
            source = GeoSymSpellSource(dictionary_path=dict_path, large_tier=True)
            # Precondition: nothing built yet
            assert source._built is False
            assert source._sym_spell is None

            source.warm()

            # warm() must be a no-op for LARGE tier
            assert source._built is False
            assert source._sym_spell is None
        finally:
            Path(dict_path).unlink()

    def test_small_tier_warm_does_build_index(self):
        """warm() on large_tier=False (SMALL tier) MUST build the index (regression guard)."""
        pytest = __import__("pytest")
        try:
            import symspellpy  # noqa: F401
        except ImportError:
            pytest.skip("symspellpy not installed")

        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        dict_path = _make_dict_file(["france", "germany"])
        try:
            source = GeoSymSpellSource(dictionary_path=dict_path, large_tier=False)
            assert source._built is False

            source.warm()

            # SMALL tier warms normally
            assert source._built is True
            assert source._sym_spell is not None
        finally:
            Path(dict_path).unlink()

    def test_large_tier_index_built_lazily_on_generate(self):
        """The LARGE index must still be built on the first generate() that needs it."""
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
        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        dict_path = _make_dict_file(["untied states", "united states"])
        try:
            source = GeoSymSpellSource(dictionary_path=dict_path, large_tier=True)
            source.warm()
            # Still unbuilt after warm
            assert source._built is False

            # A query with entity_types=None passes the LARGE-tier guard
            query = Query(
                raw_text="Untied States",
                normalized=NormalizedText(
                    original="Untied States", normalized="untied states"
                ),
            )
            ctx = GenerationContext(
                query=query,
                context=ResolutionContext(entity_types=None),
                store=MockStore(),
                budget=10,
                trace=NullTraceSink(),
            )
            source.generate(ctx)

            # Index must have been built during generate()
            assert source._built is True
            assert source._sym_spell is not None
        finally:
            Path(dict_path).unlink()


class TestGeoFuzzyRetrievalLargeTierLazyWarm:
    def test_large_tier_warm_does_not_build_shared_index(self):
        """warm() on a LARGE-tier GeoFuzzyRetrievalSource sharing a SymSpell instance
        must NOT trigger the index build."""
        pytest = __import__("pytest")
        try:
            import symspellpy  # noqa: F401
        except ImportError:
            pytest.skip("symspellpy not installed")

        from resolvekit.packs.geo.sources.fuzzy_retrieval import GeoFuzzyRetrievalSource
        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        dict_path = _make_dict_file(["united states", "canada"])
        try:
            symspell_source = GeoSymSpellSource(
                dictionary_path=dict_path, large_tier=True
            )
            fuzzy_source = GeoFuzzyRetrievalSource(large_tier=True)
            fuzzy_source.share_symspell_from(symspell_source)

            assert symspell_source._built is False
            assert symspell_source._sym_spell is None

            fuzzy_source.warm()

            # Neither the fuzzy source nor the shared symspell source should be built
            assert symspell_source._built is False
            assert symspell_source._sym_spell is None
        finally:
            Path(dict_path).unlink()

    def test_small_tier_fuzzy_warm_builds_index(self):
        """warm() on a SMALL-tier GeoFuzzyRetrievalSource must build the index."""
        pytest = __import__("pytest")
        try:
            import symspellpy  # noqa: F401
        except ImportError:
            pytest.skip("symspellpy not installed")

        from resolvekit.packs.geo.sources.fuzzy_retrieval import GeoFuzzyRetrievalSource

        dict_path = _make_dict_file(["france", "germany"])
        try:
            source = GeoFuzzyRetrievalSource(
                dictionary_path=dict_path, large_tier=False
            )
            assert source._built is False

            source.warm()

            assert source._built is True
            assert source._sym_spell is not None
        finally:
            Path(dict_path).unlink()

    def test_large_tier_fuzzy_index_built_lazily_on_generate(self):
        """The shared LARGE index must still be built on generate() for non-small queries."""
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
        from resolvekit.packs.geo.sources.fuzzy_retrieval import GeoFuzzyRetrievalSource
        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        dict_path = _make_dict_file(["united", "states"])
        try:
            symspell_source = GeoSymSpellSource(
                dictionary_path=dict_path, large_tier=True
            )
            fuzzy_source = GeoFuzzyRetrievalSource(large_tier=True)
            fuzzy_source.share_symspell_from(symspell_source)

            fuzzy_source.warm()
            # Still unbuilt after warm
            assert symspell_source._built is False

            # generate() with entity_types=None passes the LARGE-tier guard
            query = Query(
                raw_text="Untied States",
                normalized=NormalizedText(
                    original="Untied States", normalized="untied states"
                ),
            )
            ctx = GenerationContext(
                query=query,
                context=ResolutionContext(entity_types=None),
                store=MockStore(),
                budget=10,
                trace=NullTraceSink(),
            )
            fuzzy_source.generate(ctx)

            # Shared index built on first real query
            assert symspell_source._built is True
            assert symspell_source._sym_spell is not None
        finally:
            Path(dict_path).unlink()
