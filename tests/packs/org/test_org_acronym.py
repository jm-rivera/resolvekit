"""Tests for OrgAcronymSource."""

from __future__ import annotations

from typing import ClassVar


class TestOrgAcronymSource:
    """Tests for OrgAcronymSource."""

    def test_source_properties(self):
        from resolvekit.packs.org.sources.acronym import OrgAcronymSource

        source = OrgAcronymSource()
        assert source.name == "org_acronym"
        assert source.supports("org") is True

    def test_finds_eu_acronym(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.org.sources.acronym import OrgAcronymSource

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                if value_norm == "eu" and name_kinds and "acronym" in name_kinds:
                    return ["org/EU"]
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        source = OrgAcronymSource()
        query = Query(
            raw_text="EU",
            normalized=NormalizedText(original="EU", normalized="eu"),
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
        assert evidence[0].source_name == "org_acronym"
        assert evidence[0].matched_field == "name.acronym"

    def test_detects_acronym_like_query(self):
        from resolvekit.packs.org.sources.acronym import OrgAcronymSource

        source = OrgAcronymSource()

        assert source._is_acronym_like("EU") is True
        assert source._is_acronym_like("NATO") is True
        assert source._is_acronym_like("IMF") is True
        assert source._is_acronym_like("European Union") is False
        assert source._is_acronym_like("World Bank") is False

    def test_all_uppercase_boosts_score(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.org.sources.acronym import OrgAcronymSource

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                if value_norm == "eu":
                    return ["org/EU"]
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        source = OrgAcronymSource()

        # All uppercase should get 1.0
        query_upper = Query(
            raw_text="EU",
            normalized=NormalizedText(original="EU", normalized="eu"),
        )
        ctx_upper = GenerationContext(
            query=query_upper,
            context=ResolutionContext(),
            store=MockStore(),
            budget=10,
            trace=NullTraceSink(),
        )
        evidence_upper = source.generate(ctx_upper)
        assert evidence_upper[0].raw_score == 1.0

        # Mixed case should get 0.95
        query_mixed = Query(
            raw_text="Eu",
            normalized=NormalizedText(original="Eu", normalized="eu"),
        )
        ctx_mixed = GenerationContext(
            query=query_mixed,
            context=ResolutionContext(),
            store=MockStore(),
            budget=10,
            trace=NullTraceSink(),
        )
        evidence_mixed = source.generate(ctx_mixed)
        assert evidence_mixed[0].raw_score == 0.95


def _resolution_side_predicates():
    from resolvekit.packs.org.decision import OrgDecisionPolicy
    from resolvekit.packs.org.feature_extractor import OrgFeatureExtractor
    from resolvekit.packs.org.sources.acronym import OrgAcronymSource

    return [
        OrgDecisionPolicy()._is_acronym_like,
        OrgFeatureExtractor()._is_acronym_like,
        OrgAcronymSource()._is_acronym_like,
    ]


class TestAcronymPredicateTruthTable:
    """Pin the canonical loose _is_acronym_like truth table.

    All three resolution-side copies (decision.py, feature_extractor.py,
    sources/acronym.py) share identical semantics and must agree on every row.
    """

    # (input, expected, reason)
    _TABLE: ClassVar[list[tuple[str, bool, str]]] = [
        ("IMF", True, "upper 1.0, vowel 0.33"),
        ("imf", False, "upper 0.0 < 0.5"),
        ("NATO", True, "len 4 <= 5"),
        ("UN", True, "upper 1.0, len 2 <= 5"),
        ("un", False, "upper 0.0 < 0.5"),
        ("EU", True, "upper 1.0"),
        ("hello", False, "upper 0.0"),
        ("a", False, "len 1 < 2"),
        ("ABCDEFGHIJK", False, "len 11 > 10"),
        ("European Union", False, "upper ratio low + len > 10"),
    ]

    def test_loose_truth_table_resolution_side(self) -> None:
        """Parametrized inline so a single failure names both the predicate index
        and the failing input without requiring pytest.mark.parametrize imports.
        """
        predicates = _resolution_side_predicates()
        failures: list[str] = []
        for text, expected, reason in self._TABLE:
            for i, pred in enumerate(predicates):
                got = pred(text)
                if got is not expected:
                    failures.append(
                        f"predicate[{i}]({text!r}): expected {expected}, got {got} ({reason})"
                    )
        assert not failures, "\n".join(failures)

    def test_routing_divergence_is_documented_delta(self) -> None:
        """Routing is_acronym_like (routing.py) agrees with the canonical resolution-side copies."""
        from resolvekit.packs.org._acronym import (
            is_acronym_like as routing_is_acronym_like,
        )

        # routing has no first-char gate, allowing iMAC to pass
        assert routing_is_acronym_like("iMAC") is True

        # resolution-side: no first-char gate (unchanged)
        for pred in _resolution_side_predicates():
            assert pred("iMAC") is True
