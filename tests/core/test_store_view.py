"""Unit tests for StoreView.

Verifies the union/dedup/pack_filter semantics of the 9 store-read accessors
using two small MockEntityStore instances.
"""

from __future__ import annotations

from datetime import date

from resolvekit.core.model import EntityRecord
from resolvekit.core.store.store_view import StoreView
from tests.conftest import MockEntityStore


def _make_entity(entity_id: str, entity_type: str = "geo.country") -> EntityRecord:
    return EntityRecord(
        entity_id=entity_id,
        entity_type=entity_type,
        canonical_name=entity_id,
        canonical_name_norm=entity_id.lower(),
    )


class _RelationStore(MockEntityStore):
    """MockEntityStore extended with reverse-relation and list-by-type support."""

    def __init__(self, entities=None, codes=None, names=None, relations=None) -> None:
        super().__init__(entities=entities, codes=codes, names=names)
        # relations: dict[tuple[target_id, rel_type], list[str]]
        self._relations: dict[tuple[str, str], list[str]] = relations or {}

    def get_reverse_relations(
        self, target_id: str, relation_type: str, *, as_of: date | None = None
    ) -> list[str]:
        return self._relations.get((target_id, relation_type), [])

    def list_entities_by_type(self, entity_type: str) -> list[EntityRecord]:
        return [e for e in self._entities.values() if e.entity_type == entity_type]


# ---------------------------------------------------------------------------
# Basic construction
# ---------------------------------------------------------------------------


class TestEmptyView:
    """Empty store list returns empty/None for every accessor."""

    def setup_method(self) -> None:
        self.view = StoreView([])

    def test_get_entity_returns_none(self) -> None:
        assert self.view.get_entity("any") is None

    def test_lookup_code_returns_empty(self) -> None:
        assert self.view.lookup_code("iso2", "us") == []

    def test_lookup_code_attributed_returns_empty(self) -> None:
        assert self.view.lookup_code_attributed(system="iso2", value_norm="us") == []

    def test_lookup_name_exact_returns_empty(self) -> None:
        assert self.view.lookup_name_exact(value="anything") == []

    def test_get_reverse_relations_returns_empty(self) -> None:
        assert self.view.get_reverse_relations(entity_id="x", relation_type="r") == []

    def test_get_relations_as_of_returns_empty(self) -> None:
        assert (
            self.view.get_relations_as_of(
                entity_id="x", relation_type="r", as_of=date(2024, 1, 1)
            )
            == frozenset()
        )

    def test_list_entities_by_type_returns_empty(self) -> None:
        assert self.view.list_entities_by_type(entity_type="geo.country") == []

    def test_available_code_systems_returns_empty(self) -> None:
        assert self.view.available_code_systems() == frozenset()

    def test_is_snapshot_entity_returns_false(self) -> None:
        assert self.view.is_snapshot_entity(entity_id="x") is False


# ---------------------------------------------------------------------------
# Single-pair view
# ---------------------------------------------------------------------------


class TestSinglePairView:
    """Single-pair view returns the one store's results unchanged."""

    def setup_method(self) -> None:
        self.usa = _make_entity("country/USA")
        store = _RelationStore(
            entities={"country/USA": self.usa},
            codes={("iso2", "us"): ["country/USA"]},
            names={"united states": ["country/USA"]},
            relations={("geo.group/G7", "member_of"): ["country/USA"]},
        )
        self.view = StoreView([("geo", store)])

    def test_get_entity_found(self) -> None:
        assert self.view.get_entity("country/USA") is self.usa

    def test_get_entity_missing(self) -> None:
        assert self.view.get_entity("no/such") is None

    def test_lookup_code_found(self) -> None:
        assert self.view.lookup_code("iso2", "us") == ["country/USA"]

    def test_lookup_code_attributed_found(self) -> None:
        result = self.view.lookup_code_attributed(system="iso2", value_norm="us")
        assert result == [("geo", "country/USA")]

    def test_lookup_name_exact_found(self) -> None:
        result = self.view.lookup_name_exact(value="united states")
        assert result == [("geo", "country/USA")]

    def test_get_reverse_relations(self) -> None:
        result = self.view.get_reverse_relations(
            entity_id="geo.group/G7", relation_type="member_of"
        )
        assert result == ["country/USA"]


# ---------------------------------------------------------------------------
# Two-pair view — union + dedup
# ---------------------------------------------------------------------------


class TestTwoPairView:
    """Two-pair view unions results and dedups by entity_id, preserving first-seen attribution."""

    def setup_method(self) -> None:
        usa = _make_entity("country/USA")
        deu = _make_entity("country/DEU")
        self.geo_store = _RelationStore(
            entities={"country/USA": usa},
            codes={("iso2", "us"): ["country/USA"]},
            names={"united states": ["country/USA"]},
            relations={("geo.group/G7", "member_of"): ["country/USA", "country/DEU"]},
        )
        self.org_store = _RelationStore(
            entities={"country/DEU": deu, "country/USA": usa},  # USA in both
            codes={("iso2", "de"): ["country/DEU"]},
            names={"germany": ["country/DEU"]},
            relations={("geo.group/G7", "member_of"): ["country/USA"]},
        )
        self.view = StoreView([("geo", self.geo_store), ("org", self.org_store)])

    def test_get_entity_first_store_wins(self) -> None:
        # USA is in geo first; result should be non-None
        assert self.view.get_entity("country/USA") is not None

    def test_lookup_code_unions_across_stores(self) -> None:
        # geo has US, org has DE
        us_ids = self.view.lookup_code("iso2", "us")
        de_ids = self.view.lookup_code("iso2", "de")
        assert "country/USA" in us_ids
        assert "country/DEU" in de_ids

    def test_lookup_code_deduplicates(self) -> None:
        # Both stores have ("iso2", "us") → ["country/USA"] (add to org_store)
        self.org_store._codes[("iso2", "us")] = ["country/USA"]
        result = self.view.lookup_code("iso2", "us")
        assert result.count("country/USA") == 1

    def test_lookup_code_attributed_first_store_wins_attribution(self) -> None:
        result = self.view.lookup_code_attributed(system="iso2", value_norm="us")
        assert len(result) == 1
        pack_id, entity_id = result[0]
        assert pack_id == "geo"
        assert entity_id == "country/USA"

    def test_lookup_name_exact_deduplicates(self) -> None:
        # Add "united states" to org store too
        self.org_store._names["united states"] = ["country/USA"]
        result = self.view.lookup_name_exact(value="united states")
        entity_ids = [eid for _, eid in result]
        assert entity_ids.count("country/USA") == 1

    def test_get_reverse_relations_deduplicates(self) -> None:
        # Both stores return USA; view should dedup
        result = self.view.get_reverse_relations(
            entity_id="geo.group/G7", relation_type="member_of"
        )
        assert result.count("country/USA") == 1
        assert "country/DEU" in result

    def test_list_entities_by_type_unions(self) -> None:
        result = self.view.list_entities_by_type(entity_type="geo.country")
        entity_ids = [e.entity_id for e in result]
        assert "country/USA" in entity_ids
        assert "country/DEU" in entity_ids

    def test_list_entities_by_type_no_duplicates(self) -> None:
        result = self.view.list_entities_by_type(entity_type="geo.country")
        entity_ids = [e.entity_id for e in result]
        assert len(entity_ids) == len(set(entity_ids))

    def test_available_code_systems_unions(self) -> None:
        systems = self.view.available_code_systems()
        assert isinstance(systems, frozenset)
        # Each store returns frozenset() by default from base MockEntityStore;
        # subclass overrides would add more — no assertion on content needed here


# ---------------------------------------------------------------------------
# pack_filter
# ---------------------------------------------------------------------------


class TestPackFilter:
    """pack_filter excludes non-matching pairs."""

    def setup_method(self) -> None:
        geo_store = _RelationStore(
            entities={"country/USA": _make_entity("country/USA")},
            codes={("iso2", "us"): ["country/USA"]},
            names={"united states": ["country/USA"]},
        )
        org_store = _RelationStore(
            entities={"org/WHO": _make_entity("org/WHO", "org.igo")},
            codes={("lei", "who"): ["org/WHO"]},
            names={"world health organization": ["org/WHO"]},
        )
        self.view = StoreView([("geo", geo_store), ("org", org_store)])

    def test_lookup_code_filter_includes_matching(self) -> None:
        result = self.view.lookup_code("iso2", "us", pack_filter=frozenset({"geo"}))
        assert result == ["country/USA"]

    def test_lookup_code_filter_excludes_non_matching(self) -> None:
        result = self.view.lookup_code("lei", "who", pack_filter=frozenset({"geo"}))
        assert result == []

    def test_lookup_code_none_filter_aggregates_all(self) -> None:
        usa = self.view.lookup_code("iso2", "us", pack_filter=None)
        who = self.view.lookup_code("lei", "who", pack_filter=None)
        assert "country/USA" in usa
        assert "org/WHO" in who

    def test_lookup_name_exact_filter_excludes(self) -> None:
        result = self.view.lookup_name_exact(
            value="world health organization", pack_filter=frozenset({"geo"})
        )
        assert result == []

    def test_lookup_name_exact_filter_includes(self) -> None:
        result = self.view.lookup_name_exact(
            value="united states", pack_filter=frozenset({"geo"})
        )
        assert len(result) == 1
        assert result[0] == ("geo", "country/USA")


# ---------------------------------------------------------------------------
# is_snapshot_entity — True when any store reports the flag
# ---------------------------------------------------------------------------


class TestIsSnapshotEntity:
    """is_snapshot_entity returns True when any store has attributes['snapshot']=True."""

    def test_true_when_any_store_reports_snapshot(self) -> None:
        snap = EntityRecord(
            entity_id="group/SNAP",
            entity_type="org.group",
            canonical_name="Snap",
            canonical_name_norm="snap",
            attributes={"snapshot": True},
        )
        store_a = MockEntityStore()  # no snapshot
        store_b = MockEntityStore(entities={"group/SNAP": snap})
        view = StoreView([("a", store_a), ("b", store_b)])
        assert view.is_snapshot_entity(entity_id="group/SNAP") is True

    def test_false_when_no_store_reports_snapshot(self) -> None:
        normal = _make_entity("country/USA")
        store = MockEntityStore(entities={"country/USA": normal})
        view = StoreView([("geo", store)])
        assert view.is_snapshot_entity(entity_id="country/USA") is False

    def test_false_for_unknown_entity(self) -> None:
        view = StoreView([("geo", MockEntityStore())])
        assert view.is_snapshot_entity(entity_id="no/such") is False
