"""Tests for OrgSymSpellSource."""

import pytest


class TestOrgSymSpellSource:
    """Tests for OrgSymSpellSource typo tolerance."""

    def test_source_properties(self):
        from resolvekit.packs.org.sources.symspell import OrgSymSpellSource

        source = OrgSymSpellSource(dictionary_path=None)
        assert source.name == "org_symspell"
        assert source.supports("org") is True
        assert source.supports("geo") is False

    def test_corrects_typo_in_org_name(self, tmp_path):
        pytest.importorskip("symspellpy")
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.org.sources.symspell import OrgSymSpellSource

        # Create a simple dictionary
        dict_path = tmp_path / "org_dict.txt"
        dict_path.write_text("world bank\neuropean union\n")

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                if value_norm == "world bank":
                    return ["org/WorldBank"]
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        source = OrgSymSpellSource(dictionary_path=str(dict_path), max_edit_distance=2)
        query = Query(
            raw_text="Wrold Bank",  # Typo
            normalized=NormalizedText(original="Wrold Bank", normalized="wrold bank"),
        )

        ctx = GenerationContext(
            query=query,
            context=ResolutionContext(),
            store=MockStore(),
            budget=10,
            trace=NullTraceSink(),
        )
        evidence = source.generate(ctx)

        assert len(evidence) >= 1
        assert evidence[0].source_name == "org_symspell"
        assert evidence[0].matched_field == "symspell_correction"

    def test_respects_edit_distance_limit(self, tmp_path):
        pytest.importorskip("symspellpy")
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.org.sources.symspell import OrgSymSpellSource

        dict_path = tmp_path / "org_dict.txt"
        dict_path.write_text("world bank\n")

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

        source = OrgSymSpellSource(dictionary_path=str(dict_path), max_edit_distance=1)
        query = Query(
            raw_text="Wrld Bnk",  # Too many errors for edit distance 1
            normalized=NormalizedText(original="Wrld Bnk", normalized="wrld bnk"),
        )

        ctx = GenerationContext(
            query=query,
            context=ResolutionContext(),
            store=MockStore(),
            budget=10,
            trace=NullTraceSink(),
        )
        evidence = source.generate(ctx)

        # Should not match - too many edits needed
        assert len(evidence) == 0

    def test_no_symspell_returns_empty(self):
        """Test graceful degradation when symspellpy is not installed."""
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.org.sources.symspell import OrgSymSpellSource

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

        # No dictionary path = no symspell
        source = OrgSymSpellSource(dictionary_path=None)
        query = Query(
            raw_text="Test",
            normalized=NormalizedText(original="Test", normalized="test"),
        )

        ctx = GenerationContext(
            query=query,
            context=ResolutionContext(),
            store=MockStore(),
            budget=10,
            trace=NullTraceSink(),
        )
        evidence = source.generate(ctx)

        # Should return empty (graceful degradation)
        assert len(evidence) == 0
