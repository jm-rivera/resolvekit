"""Tests for OrgExactCodeSource."""

from resolvekit.core.model import GenerationContext
from resolvekit.packs.org.sources.exact_code import OrgExactCodeSource
from tests.conftest import MockEntityStore, make_query


class TestOrgExactCodeSource:
    """Tests for OrgExactCodeSource."""

    def test_source_properties(self):
        source = OrgExactCodeSource()
        assert source.name == "org_exact_code"
        assert source.supports("org") is True
        assert source.supports("geo") is False

    def test_finds_by_wikidata_id(self, null_trace, empty_context):
        store = MockEntityStore(codes={("wikidata", "q458"): ["org/EU"]})
        source = OrgExactCodeSource()
        query = make_query("Q458", normalized="q458")

        ctx = GenerationContext(
            query=query,
            context=empty_context,
            store=store,
            budget=10,
            trace=null_trace,
        )
        evidence = source.generate(ctx)

        assert len(evidence) == 1
        assert evidence[0].matched_field == "code.wikidata"
        assert evidence[0].entity_id == "org/EU"
        assert evidence[0].raw_score == 1.0

    def test_falls_back_to_any_code_system(self, null_trace, empty_context):
        store = MockEntityStore(codes={("lei", "lei123"): ["org/ACME"]})
        source = OrgExactCodeSource()
        query = make_query("LEI123", normalized="lei123")

        ctx = GenerationContext(
            query=query,
            context=empty_context,
            store=store,
            budget=10,
            trace=null_trace,
        )
        evidence = source.generate(ctx)

        assert len(evidence) == 1
        assert evidence[0].entity_id == "org/ACME"
        assert evidence[0].matched_field == "code.lei"
        assert evidence[0].raw_score == 1.0
