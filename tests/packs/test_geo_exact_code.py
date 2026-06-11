"""Tests for GeoExactCodeSource — catch-all code-system allowlist."""

from resolvekit.core.explain import NullTraceSink
from resolvekit.core.model import (
    GenerationContext,
    NormalizedText,
    Query,
    ResolutionContext,
)
from resolvekit.core.store import EntityStore
from resolvekit.packs.geo.sources.exact_code import GeoExactCodeSource


def _make_ctx(
    raw_text: str,
    normalized: str,
    store: EntityStore,
    *,
    budget: int = 10,
) -> GenerationContext:
    return GenerationContext(
        query=Query(
            raw_text=raw_text,
            normalized=NormalizedText(original=raw_text, normalized=normalized),
        ),
        context=ResolutionContext(),
        store=store,
        budget=budget,
        trace=NullTraceSink(),
    )


class _CodeOnlyStore(EntityStore):
    """Store whose only signal is a configurable lookup_code_any result."""

    def __init__(self, any_hits: list[tuple[str, str]]):
        self._any_hits = any_hits

    def get_entity(self, entity_id):
        return None

    def lookup_code(self, system, value_norm):
        return []

    def lookup_code_any(self, value_norm):
        return list(self._any_hits)

    def lookup_name_exact(self, value_norm, name_kinds=None):
        return []

    def search_fulltext(self, query_norm, fields=None, limit=10):
        return []

    def bulk_get_entities(self, entity_ids):
        return {}


class TestGeoExactCodeCatchAll:
    def test_catalog_cross_reference_system_is_not_matchable(self):
        """A word-like value in a catalog identifier system must not match.

        Regression: the US state geoId/13 carries
        swedishNationalEncyclopediaId="georgia"; matching it at the exact-code
        tier short-circuited the pipeline and shadowed country/GEO.
        """
        store = _CodeOnlyStore([("geoId/13", "swedishnationalencyclopediaid")])
        evidence = GeoExactCodeSource().generate(_make_ctx("Georgia", "georgia", store))
        assert evidence == []

    def test_structured_code_system_still_matches(self):
        """An allowlisted structured system (UN M49) still resolves via catch-all."""
        store = _CodeOnlyStore([("country/GEO", "undata")])
        evidence = GeoExactCodeSource().generate(_make_ctx("268", "268", store))
        assert [e.entity_id for e in evidence] == ["country/GEO"]

    def test_mixed_hits_keep_only_matchable_systems(self):
        store = _CodeOnlyStore(
            [
                ("geoId/13", "swedishnationalencyclopediaid"),
                ("geoId/99", "quoratopicid"),
                ("country/GEO", "ioccountrycode"),
            ]
        )
        evidence = GeoExactCodeSource().generate(_make_ctx("GEO", "geo", store))
        assert [e.entity_id for e in evidence] == ["country/GEO"]
