"""Tests for TypeConstraint compatibility-map expansion."""

from resolvekit.core.explain import NullTraceSink
from resolvekit.core.model import (
    Candidate,
    CandidateEvidence,
    EntityRecord,
    NormalizedText,
    Query,
    ResolutionContext,
    RetrievalSummary,
    ScoreSummary,
)
from resolvekit.core.store import EntityStore
from resolvekit.shared.constraints.type_constraint import TypeConstraint

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(entity_id: str, entity_type: str) -> EntityStore:
    """Return a minimal EntityStore stub that yields one entity."""

    record = EntityRecord(
        entity_id=entity_id,
        entity_type=entity_type,
        canonical_name=entity_id,
        canonical_name_norm=entity_id.lower(),
    )

    class _Stub(EntityStore):
        def get_entity(self, eid):
            return record if eid == entity_id else None

        def lookup_code(self, system, value_norm):
            return []

        def lookup_name_exact(self, value_norm, name_kinds=None):
            return []

        def search_fulltext(self, query_norm, fields=None, limit=10):
            return []

        def bulk_get_entities(self, entity_ids):
            return {eid: record for eid in entity_ids if eid == entity_id}

    return _Stub()


def _make_candidate(entity_id: str) -> Candidate:
    return Candidate(
        entity_id=entity_id,
        sources=[
            CandidateEvidence(entity_id=entity_id, source_name="test", raw_score=1.0)
        ],
        retrieval=RetrievalSummary(best_source="test"),
        scores=ScoreSummary(raw_score=0.9, calibrated_score=0.9),
    )


def _make_query(text: str = "test") -> Query:
    return Query(
        raw_text=text,
        normalized=NormalizedText(original=text, normalized=text.lower()),
    )


# ---------------------------------------------------------------------------
# Strict (no compatibility) behaviour - regression guard
# ---------------------------------------------------------------------------


class TestTypeConstraintStrict:
    """Verify that the default (no compatibility) mode is unchanged."""

    def test_no_entity_types_passes_all(self):
        constraint = TypeConstraint("tc")
        candidate = _make_candidate("x/1")
        store = _make_store("x/1", "geo.admin1")
        result = constraint.apply(
            _make_query(), ResolutionContext(), [candidate], store, NullTraceSink()
        )
        assert len(result) == 1

    def test_matching_type_passes(self):
        constraint = TypeConstraint("tc")
        candidate = _make_candidate("x/1")
        store = _make_store("x/1", "geo.country")
        result = constraint.apply(
            _make_query(),
            ResolutionContext(entity_types={"geo.country"}),
            [candidate],
            store,
            NullTraceSink(),
        )
        assert len(result) == 1
        assert result[0].constraint_outcomes[0].passed is True

    def test_non_matching_type_filtered(self):
        constraint = TypeConstraint("tc")
        candidate = _make_candidate("x/1")
        store = _make_store("x/1", "geo.admin1")
        result = constraint.apply(
            _make_query(),
            ResolutionContext(entity_types={"geo.country"}),
            [candidate],
            store,
            NullTraceSink(),
        )
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Compatibility-map expansion
# ---------------------------------------------------------------------------

_GEO_COMPAT: dict[str, frozenset[str]] = {
    "geo.city": frozenset(
        {
            "geo.city",
            "geo.admin1",
            "geo.admin2",
            "geo.admin3",
            "geo.admin4",
            "geo.admin5",
        }
    ),
    "geo.continental_union": frozenset({"geo.continental_union", "geo.organization"}),
}


class TestTypeConstraintCompatibility:
    """Compatibility map correctly widens selected types and leaves others strict."""

    def test_city_hint_accepts_admin1(self):
        """Tokyo/Seoul/Bangkok are stored as geo.admin1 — geo.city hint must pass them."""
        constraint = TypeConstraint("tc", compatibility=_GEO_COMPAT)
        candidate = _make_candidate("admin/Tokyo")
        store = _make_store("admin/Tokyo", "geo.admin1")
        result = constraint.apply(
            _make_query("Tokyo"),
            ResolutionContext(entity_types={"geo.city"}),
            [candidate],
            store,
            NullTraceSink(),
        )
        assert len(result) == 1, "admin1 entity should pass under geo.city hint"
        assert result[0].constraint_outcomes[0].passed is True

    def test_city_hint_accepts_admin2(self):
        """Paris is stored as geo.admin2."""
        constraint = TypeConstraint("tc", compatibility=_GEO_COMPAT)
        candidate = _make_candidate("admin/Paris")
        store = _make_store("admin/Paris", "geo.admin2")
        result = constraint.apply(
            _make_query("Paris"),
            ResolutionContext(entity_types={"geo.city"}),
            [candidate],
            store,
            NullTraceSink(),
        )
        assert len(result) == 1

    def test_city_hint_accepts_admin3(self):
        constraint = TypeConstraint("tc", compatibility=_GEO_COMPAT)
        candidate = _make_candidate("admin/Rome")
        store = _make_store("admin/Rome", "geo.admin3")
        result = constraint.apply(
            _make_query("Rome"),
            ResolutionContext(entity_types={"geo.city"}),
            [candidate],
            store,
            NullTraceSink(),
        )
        assert len(result) == 1

    def test_city_hint_accepts_admin4(self):
        constraint = TypeConstraint("tc", compatibility=_GEO_COMPAT)
        candidate = _make_candidate("admin/Lyon")
        store = _make_store("admin/Lyon", "geo.admin4")
        result = constraint.apply(
            _make_query("Lyon"),
            ResolutionContext(entity_types={"geo.city"}),
            [candidate],
            store,
            NullTraceSink(),
        )
        assert len(result) == 1

    def test_city_hint_accepts_admin5(self):
        constraint = TypeConstraint("tc", compatibility=_GEO_COMPAT)
        candidate = _make_candidate("admin/Small")
        store = _make_store("admin/Small", "geo.admin5")
        result = constraint.apply(
            _make_query("Small"),
            ResolutionContext(entity_types={"geo.city"}),
            [candidate],
            store,
            NullTraceSink(),
        )
        assert len(result) == 1

    def test_country_hint_does_not_accept_admin1(self):
        """Georgia-disambiguation: geo.country must NOT match geo.admin1 (US state)."""
        constraint = TypeConstraint("tc", compatibility=_GEO_COMPAT)
        candidate = _make_candidate("wikidataId/Q1428")  # Georgia (US state)
        store = _make_store("wikidataId/Q1428", "geo.admin1")
        result = constraint.apply(
            _make_query("Georgia"),
            ResolutionContext(entity_types={"geo.country"}),
            [candidate],
            store,
            NullTraceSink(),
        )
        assert len(result) == 0, (
            "geo.admin1 must be filtered when caller asked for geo.country "
            "(preserves Georgia country vs. US-state disambiguation)"
        )

    def test_country_hint_accepts_country(self):
        """Georgia (country) must pass when caller asks for geo.country."""
        constraint = TypeConstraint("tc", compatibility=_GEO_COMPAT)
        candidate = _make_candidate("country/GEO")
        store = _make_store("country/GEO", "geo.country")
        result = constraint.apply(
            _make_query("Georgia"),
            ResolutionContext(entity_types={"geo.country"}),
            [candidate],
            store,
            NullTraceSink(),
        )
        assert len(result) == 1

    def test_continental_union_hint_accepts_organization(self):
        """G20, AU, ASEAN stored as geo.organization must pass geo.continental_union hint."""
        constraint = TypeConstraint("tc", compatibility=_GEO_COMPAT)
        candidate = _make_candidate("org/G20")
        store = _make_store("org/G20", "geo.organization")
        result = constraint.apply(
            _make_query("G20"),
            ResolutionContext(entity_types={"geo.continental_union"}),
            [candidate],
            store,
            NullTraceSink(),
        )
        assert len(result) == 1

    def test_continental_union_hint_accepts_continental_union(self):
        """Entities stored as geo.continental_union also pass the same hint."""
        constraint = TypeConstraint("tc", compatibility=_GEO_COMPAT)
        candidate = _make_candidate("org/EU")
        store = _make_store("org/EU", "geo.continental_union")
        result = constraint.apply(
            _make_query("EU"),
            ResolutionContext(entity_types={"geo.continental_union"}),
            [candidate],
            store,
            NullTraceSink(),
        )
        assert len(result) == 1

    def test_unmapped_type_stays_strict(self):
        """A type not in the compat map (e.g. geo.region) is still filtered strictly."""
        constraint = TypeConstraint("tc", compatibility=_GEO_COMPAT)
        candidate = _make_candidate("region/X")
        store = _make_store("region/X", "geo.region")
        result = constraint.apply(
            _make_query("X"),
            ResolutionContext(entity_types={"geo.city"}),
            [candidate],
            store,
            NullTraceSink(),
        )
        assert len(result) == 0, "geo.region is not in the city compat set"

    def test_none_compatibility_is_strictly_equivalent(self):
        """TypeConstraint(compat=None) and TypeConstraint() both yield strict behaviour."""
        strict = TypeConstraint("tc")
        with_none = TypeConstraint("tc", compatibility=None)
        candidate_a = _make_candidate("admin/Tokyo")
        candidate_b = _make_candidate("admin/Tokyo")
        store = _make_store("admin/Tokyo", "geo.admin1")
        ctx = ResolutionContext(entity_types={"geo.city"})
        result_strict = strict.apply(
            _make_query(), ctx, [candidate_a], store, NullTraceSink()
        )
        result_none = with_none.apply(
            _make_query(), ctx, [candidate_b], store, NullTraceSink()
        )
        assert len(result_strict) == 0
        assert len(result_none) == 0


# ---------------------------------------------------------------------------
# GeoTypeConstraint integration: verify it uses the right compat map
# ---------------------------------------------------------------------------


class TestGeoTypeConstraint:
    """GeoTypeConstraint wires the geo compatibility map correctly."""

    def test_geo_city_passes_admin1(self):
        from resolvekit.packs.geo.constraints.type_constraint import GeoTypeConstraint

        constraint = GeoTypeConstraint()
        candidate = _make_candidate("admin/Tokyo")
        store = _make_store("admin/Tokyo", "geo.admin1")
        result = constraint.apply(
            _make_query("Tokyo"),
            ResolutionContext(entity_types={"geo.city"}),
            [candidate],
            store,
            NullTraceSink(),
        )
        assert len(result) == 1

    def test_geo_country_does_not_pass_admin1(self):
        """Georgia disambiguation preserved via GeoTypeConstraint."""
        from resolvekit.packs.geo.constraints.type_constraint import GeoTypeConstraint

        constraint = GeoTypeConstraint()
        candidate = _make_candidate("admin/GeorgiaUS")
        store = _make_store("admin/GeorgiaUS", "geo.admin1")
        result = constraint.apply(
            _make_query("Georgia"),
            ResolutionContext(entity_types={"geo.country"}),
            [candidate],
            store,
            NullTraceSink(),
        )
        assert len(result) == 0

    def test_geo_continental_union_passes_organization(self):
        from resolvekit.packs.geo.constraints.type_constraint import GeoTypeConstraint

        constraint = GeoTypeConstraint()
        candidate = _make_candidate("org/AfricanUnion")
        store = _make_store("org/AfricanUnion", "geo.organization")
        result = constraint.apply(
            _make_query("African Union"),
            ResolutionContext(entity_types={"geo.continental_union"}),
            [candidate],
            store,
            NullTraceSink(),
        )
        assert len(result) == 1

    def test_name_is_unchanged(self):
        from resolvekit.packs.geo.constraints.type_constraint import GeoTypeConstraint

        assert GeoTypeConstraint().name == "geo_type_constraint"
