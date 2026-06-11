"""Tests for GeoExactNameSource."""

from resolvekit.core.explain import NullTraceSink
from resolvekit.core.model import (
    EntityRecord,
    GenerationContext,
    NormalizedText,
    Query,
    ResolutionContext,
)
from resolvekit.core.store import EntityStore
from resolvekit.packs.geo.sources.exact_name import GeoExactNameSource

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(
    entity_id: str,
    entity_type: str,
    *,
    prominence: float | None = None,
) -> EntityRecord:
    attrs: dict[str, str | int | float | bool] = {}
    if prominence is not None:
        attrs["prominence"] = prominence
    return EntityRecord(
        entity_id=entity_id,
        entity_type=entity_type,
        canonical_name=entity_id,
        canonical_name_norm=entity_id.lower(),
        attributes=attrs,
    )


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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGeoExactNameSource:
    def test_source_properties(self):
        source = GeoExactNameSource()
        assert source.name == "geo_exact_name"
        assert source.supports("geo") is True
        assert source.supports("org") is False

    def test_finds_by_canonical_name(self):
        usa = _make_entity("country/USA", "geo.country", prominence=0.99)

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return usa if entity_id == "country/USA" else None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                if value_norm == "united states of america" and (
                    name_kinds is None or "canonical" in name_kinds
                ):
                    return ["country/USA"]
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        source = GeoExactNameSource()
        ctx = _make_ctx(
            "United States of America",
            "united states of america",
            MockStore(),
        )
        evidence = source.generate(ctx)

        assert len(evidence) == 1
        assert evidence[0].source_name == "geo_exact_name"
        assert evidence[0].matched_field == "name.canonical"
        assert evidence[0].raw_score == 1.0

    def test_finds_by_alias_name(self):
        """An entity matched only via alias still surfaces in the merged result set."""
        usa = _make_entity("country/USA", "geo.country", prominence=0.99)

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return usa if entity_id == "country/USA" else None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                # "america" is not a canonical name, but is an alias
                if value_norm == "america" and name_kinds and "canonical" in name_kinds:
                    return []
                if value_norm == "america":
                    return ["country/USA"]
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        source = GeoExactNameSource()
        ctx = _make_ctx("America", "america", MockStore())
        evidence = source.generate(ctx)

        assert len(evidence) == 1
        assert evidence[0].matched_field == "name.alias"
        assert evidence[0].raw_score == 0.95

    def test_returns_empty_for_no_match(self):
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

        source = GeoExactNameSource()
        ctx = _make_ctx("Nonexistent Place", "nonexistent place", MockStore())
        evidence = source.generate(ctx)
        assert len(evidence) == 0

    def test_canonical_wins_on_collision(self):
        """Same entity_id returned by both lookups — one evidence, canonical wins."""
        usa = _make_entity("country/USA", "geo.country", prominence=0.99)

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return usa if entity_id == "country/USA" else None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                # Both canonical and alias lookups return the same id
                return ["country/USA"]

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        source = GeoExactNameSource()
        ctx = _make_ctx("USA", "usa", MockStore())
        evidence = source.generate(ctx)

        assert len(evidence) == 1
        assert evidence[0].entity_id == "country/USA"
        assert evidence[0].raw_score == 1.0
        assert evidence[0].matched_field == "name.canonical"

    def test_prominent_entity_survives_budget(self):
        """High-prominence country survives budget cap via type-specificity-first ordering.

        Even when placed last alphabetically by entity_id, type-specificity-first
        ordering ensures a high-prominence country ranks above filler cities.
        """
        budget = 5
        # N+1 ids where N == budget; country is the last one alphabetically
        country_id = "country/ZZZ"
        filler_ids = [f"geoId/{i:04d}" for i in range(budget)]  # 5 fillers

        country = _make_entity(country_id, "geo.country", prominence=0.9)
        fillers = {eid: _make_entity(eid, "geo.city") for eid in filler_ids}

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                if entity_id == country_id:
                    return country
                return fillers.get(entity_id)

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                # All returned via canonical; country sorts last by entity_id
                if name_kinds and "canonical" in name_kinds:
                    return [*filler_ids, country_id]
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        source = GeoExactNameSource()
        ctx = _make_ctx("Springfield", "springfield", MockStore(), budget=budget)
        evidence = source.generate(ctx)

        assert len(evidence) == budget
        entity_ids_out = {e.entity_id for e in evidence}
        assert country_id in entity_ids_out, "country must survive the budget cap"
        # At least one filler is dropped (N+1 candidates → N kept)
        dropped = set(filler_ids) - entity_ids_out
        assert len(dropped) >= 1, "a low-prominence filler must be dropped"

    def test_country_survives_many_junk_canonical_collisions(self):
        """geo.country alias survives when N==budget canonical junk admin2 owners collide.

        Type-specificity-first ordering (country=0 < admin=99) ensures the country
        alias sorts ahead of budget canonical admins with the same name.
        """
        budget = 10
        country_id = "country/CPV"
        # N==budget junk canonical admin2 owners
        junk_ids = [f"wikidataId/Q{i:05d}" for i in range(budget)]

        country = _make_entity(country_id, "geo.country", prominence=0.85)
        junks = {eid: _make_entity(eid, "geo.admin2") for eid in junk_ids}

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                if entity_id == country_id:
                    return country
                return junks.get(entity_id)

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                if name_kinds and "canonical" in name_kinds:
                    return list(junk_ids)  # N==budget junk canonical owners
                # alias path returns the country
                return [country_id]

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        source = GeoExactNameSource()
        ctx = _make_ctx("Cabo Verde", "cabo verde", MockStore(), budget=budget)
        evidence = source.generate(ctx)

        assert len(evidence) == budget
        entity_ids_out = {e.entity_id for e in evidence}
        assert country_id in entity_ids_out, (
            "geo.country must survive the cap ahead of rank-99 junk canonical owners"
        )
        # Country is first (type_rank=0 beats all rank-99 junks)
        assert evidence[0].entity_id == country_id

    def test_alias_country_does_not_displace_canonical_owner(self):
        """Both canonical admin2 and alias country surface; country sorts AHEAD.

        Type-specificity-first ordering: country (rank 0) sorts before admin2
        (rank 99) regardless of name_kind. Both reach the scorer. The country
        carries alias scores (0.95/name.alias), admin carries canonical scores
        (1.0/name.canonical).
        """
        admin_id = "wikidataId/Q22062741"  # junk admin2
        country_id = "country/ISL"

        admin = _make_entity(admin_id, "geo.admin2", prominence=0.3)
        country = _make_entity(country_id, "geo.country", prominence=0.8)

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                if entity_id == admin_id:
                    return admin
                if entity_id == country_id:
                    return country
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                if name_kinds and "canonical" in name_kinds:
                    return [admin_id]
                # alias path
                return [country_id]

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        source = GeoExactNameSource()
        ctx = _make_ctx("Islandia", "islandia", MockStore())
        evidence = source.generate(ctx)

        assert len(evidence) == 2, (
            "both admin2 and country must surface (guard removed)"
        )

        ids_out = [e.entity_id for e in evidence]
        assert country_id in ids_out
        assert admin_id in ids_out

        country_ev = next(e for e in evidence if e.entity_id == country_id)
        admin_ev = next(e for e in evidence if e.entity_id == admin_id)

        # Scores preserved through merge
        assert admin_ev.raw_score == 1.0
        assert admin_ev.matched_field == "name.canonical"
        assert country_ev.raw_score == 0.95
        assert country_ev.matched_field == "name.alias"

        # type-specificity-first: country (rank 0) sorts AHEAD of admin (rank 99)
        assert evidence[0].entity_id == country_id, (
            "country must sort ahead of junk canonical admin2 (type-specificity-first)"
        )
