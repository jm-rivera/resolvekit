"""Tests for OrgExactNameSource."""


class TestOrgExactNameSource:
    """Tests for OrgExactNameSource."""

    def test_source_properties(self):
        from resolvekit.packs.org.sources.exact_name import OrgExactNameSource

        source = OrgExactNameSource()
        assert source.name == "org_exact_name"
        assert source.supports("org") is True
        assert source.supports("geo") is False

    def test_finds_by_canonical_name(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.org.sources.exact_name import OrgExactNameSource

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                if (
                    value_norm == "world bank"
                    and name_kinds
                    and "canonical" in name_kinds
                ):
                    return ["org/WorldBank"]
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        source = OrgExactNameSource()
        query = Query(
            raw_text="World Bank",
            normalized=NormalizedText(original="World Bank", normalized="world bank"),
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
        assert evidence[0].source_name == "org_exact_name"
        assert evidence[0].matched_field == "name.canonical"
        assert evidence[0].raw_score == 1.0

    def test_finds_by_legal_name(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.org.sources.exact_name import OrgExactNameSource

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                if value_norm == "international bank":
                    if name_kinds and "canonical" in name_kinds:
                        return []
                    if name_kinds and "legal" in name_kinds:
                        return ["org/IBRD"]
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        source = OrgExactNameSource()
        query = Query(
            raw_text="International Bank",
            normalized=NormalizedText(
                original="International Bank", normalized="international bank"
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

        assert len(evidence) >= 1
        assert evidence[0].matched_field == "name.legal"
        assert evidence[0].raw_score == 0.98

    def test_finds_by_short_name(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.org.sources.exact_name import OrgExactNameSource

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                if value_norm == "un":
                    if name_kinds and "canonical" in name_kinds:
                        return []
                    if name_kinds and "legal" in name_kinds:
                        return []
                    if name_kinds and "short" in name_kinds:
                        return ["org/UN"]
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        source = OrgExactNameSource()
        query = Query(
            raw_text="UN",
            normalized=NormalizedText(original="UN", normalized="un"),
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
        assert evidence[0].matched_field == "name.short"
        assert evidence[0].raw_score == 0.95
