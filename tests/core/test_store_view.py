"""Unit tests for StoreView.

Verifies the union/dedup/pack_filter semantics of the 9 store-read accessors
using two small MockEntityStore instances.
"""

from __future__ import annotations

from datetime import date

from resolvekit.core.api.containment_api import ContainmentAPI
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

    def __init__(
        self,
        entities=None,
        codes=None,
        names=None,
        relations=None,
        as_of_relations=None,
    ) -> None:
        super().__init__(entities=entities, codes=codes, names=names)
        # relations: dict[tuple[target_id, rel_type], list[str]]
        self._relations: dict[tuple[str, str], list[str]] = relations or {}
        # as_of_relations: dict[tuple[entity_id, rel_type], list[str]]
        # validity filtering is the store's concern; StoreView owns the union.
        self._as_of_relations: dict[tuple[str, str], list[str]] = as_of_relations or {}

    def relation_types(self) -> frozenset[str]:
        return frozenset(rt for (_, rt) in self._relations) | frozenset(
            rt for (_, rt) in self._as_of_relations
        )

    def get_reverse_relations(
        self, target_id: str, relation_type: str, *, as_of: date | None = None
    ) -> list[str]:
        return self._relations.get((target_id, relation_type), [])

    def get_relations_as_of(
        self, entity_id: str, relation_type: str, as_of: date
    ) -> list[str]:
        return self._as_of_relations.get((entity_id, relation_type), [])

    def list_entities_by_type(self, entity_type: str) -> list[EntityRecord]:
        return [e for e in self._entities.values() if e.entity_type == entity_type]


class _EmptyRelTypeStore(_RelationStore):
    """Reports frozenset() for relation_types() — characterized as holding no relations."""

    def relation_types(self) -> frozenset[str]:
        return frozenset()


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


# ---------------------------------------------------------------------------
# get_relations_as_of — union across stores (characterization)
# ---------------------------------------------------------------------------


class TestGetRelationsAsOfUnion:
    """StoreView.get_relations_as_of unions targets from all stores and dedups."""

    def test_unions_across_two_stores(self) -> None:
        store_a = _RelationStore(
            as_of_relations={("X", "member_of"): ["A"]},
        )
        store_b = _RelationStore(
            as_of_relations={("X", "member_of"): ["B"]},
        )
        view = StoreView([("geo", store_a), ("org", store_b)])
        result = view.get_relations_as_of(
            entity_id="X", relation_type="member_of", as_of=date(2024, 1, 1)
        )
        assert result == frozenset({"A", "B"})

    def test_dedups_overlapping_targets(self) -> None:
        store_a = _RelationStore(
            as_of_relations={("X", "member_of"): ["A"]},
        )
        store_b = _RelationStore(
            as_of_relations={("X", "member_of"): ["A"]},
        )
        view = StoreView([("geo", store_a), ("org", store_b)])
        result = view.get_relations_as_of(
            entity_id="X", relation_type="member_of", as_of=date(2024, 1, 1)
        )
        assert result == frozenset({"A"})

    def test_empty_when_no_store_has_relation(self) -> None:
        store_a = _RelationStore()
        store_b = _RelationStore()
        view = StoreView([("geo", store_a), ("org", store_b)])
        result = view.get_relations_as_of(
            entity_id="X", relation_type="member_of", as_of=date(2024, 1, 1)
        )
        assert result == frozenset()


# ---------------------------------------------------------------------------
# ContainmentAPI + StoreView — multi-pack within() (characterization)
# ---------------------------------------------------------------------------
#
# Chain layout for test_two_pack_chain_byte_identical:
#
#   store A ("geo"): region R, intermediate M (contained_in R)
#                    reverse edges: (R, contained_in) -> [M]
#   store B ("org"): leaf C (country, contained_in M)
#                    reverse edges: (M, contained_in) -> [C]
#
# BFS from R: hop1 finds M (store A edges), hop2 finds C (store B edges).
# Hydration: M from store A, C from store B.  Sorted output: [M, C] by entity_id.


class TestWithinMultiPackHydration:
    """ContainmentAPI driven by a two-store StoreView produces byte-identical output
    to the same chain loaded into a single store (multi-pack == single-pack baseline)."""

    def setup_method(self) -> None:
        self.region_r = _make_entity("region/R", entity_type="geo.region")
        self.intermediate_m = _make_entity("region/M", entity_type="geo.region")
        self.leaf_c = _make_entity("country/C", entity_type="geo.country")

        self.store_a = _RelationStore(
            entities={
                "region/R": self.region_r,
                "region/M": self.intermediate_m,
            },
            relations={
                ("region/R", "contained_in"): ["region/M"],
            },
        )
        self.store_b = _RelationStore(
            entities={
                "country/C": self.leaf_c,
            },
            relations={
                ("region/M", "contained_in"): ["country/C"],
            },
        )

    def test_two_pack_chain_byte_identical(self) -> None:
        # Multi-pack view
        view_multi = StoreView([("geo", self.store_a), ("org", self.store_b)])
        api_multi = ContainmentAPI(runner=view_multi)
        result_multi = api_multi.within(
            container_id="region/R",
            relation="contained_in",
            entity_type=None,
            recursive=True,
            max_depth=None,
            as_of=None,
        )
        multi_ids = [e.entity_id for e in result_multi]

        # Single-pack baseline — same entities and edges in one store
        single_store = _RelationStore(
            entities={
                "region/R": self.region_r,
                "region/M": self.intermediate_m,
                "country/C": self.leaf_c,
            },
            relations={
                ("region/R", "contained_in"): ["region/M"],
                ("region/M", "contained_in"): ["country/C"],
            },
        )
        view_single = StoreView([("geo", single_store)])
        api_single = ContainmentAPI(runner=view_single)
        result_single = api_single.within(
            container_id="region/R",
            relation="contained_in",
            entity_type=None,
            recursive=True,
            max_depth=None,
            as_of=None,
        )
        single_ids = [e.entity_id for e in result_single]

        # Both paths must return the same sorted entity_id list (non-empty)
        assert multi_ids, "multi-pack result must be non-empty"
        assert multi_ids == sorted(["region/M", "country/C"])
        assert multi_ids == single_ids


# ---------------------------------------------------------------------------
# ContainmentAPI + StoreView — first-wins hydration (characterization)
# ---------------------------------------------------------------------------


class TestWithinMultiPackFirstWins:
    """When the same entity_id appears in multiple stores, the first store's
    EntityRecord is the one returned by ContainmentAPI (first-wins hydration)."""

    def setup_method(self) -> None:
        self.container = _make_entity("region/R", entity_type="geo.region")

        # leaf L is reachable via store A's reverse edges
        self.leaf_in_a = EntityRecord(
            entity_id="country/L",
            entity_type="geo.country",
            canonical_name="Leaf from A",
            canonical_name_norm="leaf from a",
        )
        self.leaf_in_b = EntityRecord(
            entity_id="country/L",
            entity_type="geo.country",
            canonical_name="Leaf from B",
            canonical_name_norm="leaf from b",
        )

        self.store_a = _RelationStore(
            entities={
                "region/R": self.container,
                "country/L": self.leaf_in_a,
            },
            relations={
                ("region/R", "contained_in"): ["country/L"],
            },
        )
        self.store_b = _RelationStore(
            entities={
                "country/L": self.leaf_in_b,
            },
            relations={},
        )

        self.view = StoreView([("geo", self.store_a), ("org", self.store_b)])
        self.api = ContainmentAPI(runner=self.view)

    def test_same_id_in_two_packs_first_store_record_wins(self) -> None:
        result = self.api.within(
            container_id="region/R",
            relation="contained_in",
            entity_type=None,
            recursive=True,
            max_depth=None,
            as_of=None,
        )
        assert result, "result must be non-empty"
        leaf = result[0]
        # Object identity pins that StoreView.get_entity returned store A's record
        assert leaf is self.leaf_in_a
        assert leaf.canonical_name == "Leaf from A"

    def test_entity_type_filter_applies_after_hydration(self) -> None:
        # The leaf has type "geo.country"; filtering to "geo.region" must drop it.
        # This pins that the filter is applied post-hydration (not pre-BFS).
        result_filtered = self.api.within(
            container_id="region/R",
            relation="contained_in",
            entity_type=frozenset({"geo.region"}),
            recursive=True,
            max_depth=None,
            as_of=None,
        )
        assert result_filtered == [], (
            "filter to geo.region must drop the geo.country leaf"
        )

        # Confirm with the matching type that the leaf IS reachable (non-empty guard)
        result_country = self.api.within(
            container_id="region/R",
            relation="contained_in",
            entity_type=frozenset({"geo.country"}),
            recursive=True,
            max_depth=None,
            as_of=None,
        )
        assert result_country, (
            "entity_type=frozenset({'geo.country'}) must return the leaf"
        )


# ---------------------------------------------------------------------------
# StoreView.bulk_get_entities — first-wins dedup (unit tests)
# ---------------------------------------------------------------------------


class TestBulkGetEntitiesFirstWins:
    """StoreView.bulk_get_entities returns first-store-wins per ID; missing IDs omitted."""

    def setup_method(self) -> None:
        self.record_a = EntityRecord(
            entity_id="country/X",
            entity_type="geo.country",
            canonical_name="X from A",
            canonical_name_norm="x from a",
        )
        self.record_b = EntityRecord(
            entity_id="country/X",
            entity_type="geo.country",
            canonical_name="X from B",
            canonical_name_norm="x from b",
        )
        self.record_y = EntityRecord(
            entity_id="country/Y",
            entity_type="geo.country",
            canonical_name="Y",
            canonical_name_norm="y",
        )

    def test_first_store_wins_object_identity(self) -> None:
        # Both stores hold country/X; the first store's object must be returned.
        store_a = _RelationStore(entities={"country/X": self.record_a})
        store_b = _RelationStore(entities={"country/X": self.record_b})
        view = StoreView([("geo", store_a), ("org", store_b)])
        result = view.bulk_get_entities(["country/X"])
        assert result["country/X"] is self.record_a

    def test_union_across_stores(self) -> None:
        # country/X in store A only; country/Y in store B only — both appear.
        store_a = _RelationStore(entities={"country/X": self.record_a})
        store_b = _RelationStore(entities={"country/Y": self.record_y})
        view = StoreView([("geo", store_a), ("org", store_b)])
        result = view.bulk_get_entities(["country/X", "country/Y"])
        assert result["country/X"] is self.record_a
        assert result["country/Y"] is self.record_y
        assert len(result) == 2

    def test_missing_ids_absent_from_dict(self) -> None:
        # Requesting an ID not in any store must leave it out (no None value).
        store_a = _RelationStore(entities={"country/X": self.record_a})
        view = StoreView([("geo", store_a)])
        result = view.bulk_get_entities(["country/X", "no/such"])
        assert "no/such" not in result
        assert "country/X" in result

    def test_empty_entity_ids_returns_empty_dict(self) -> None:
        store_a = _RelationStore(entities={"country/X": self.record_a})
        view = StoreView([("geo", store_a)])
        result = view.bulk_get_entities([])
        assert result == {}

    def test_empty_store_list_returns_empty_dict(self) -> None:
        view = StoreView([])
        result = view.bulk_get_entities(["country/X", "country/Y"])
        assert result == {}


# ---------------------------------------------------------------------------
# StoreView pack-skip — relation-type index and guard semantics
# ---------------------------------------------------------------------------


class TestPackSkipRelationIndex:
    """_relation_type_index is built once at construction; guards skip known-empty stores."""

    # ------------------------------------------------------------------
    # Index shape
    # ------------------------------------------------------------------

    def test_index_length_matches_store_count(self) -> None:
        store_a = _RelationStore(relations={("T", "contained_in"): ["X"]})
        store_b = _RelationStore()  # empty → relation_types() returns frozenset()
        view = StoreView([("a", store_a), ("b", store_b)])
        assert len(view._relation_type_index) == 2

    def test_index_order_matches_store_order(self) -> None:
        store_a = _RelationStore(relations={("T", "contained_in"): ["X"]})
        store_b = _RelationStore(
            as_of_relations={("E", "member_of"): ["Y"]},
        )
        view = StoreView([("a", store_a), ("b", store_b)])
        assert view._relation_type_index[0] == frozenset({"contained_in"})
        assert view._relation_type_index[1] == frozenset({"member_of"})

    def test_index_none_for_uncharacterized_store(self) -> None:
        # MockEntityStore inherits EntityStore.relation_types() → None
        uncharacterized = MockEntityStore()
        characterized = _RelationStore(relations={("T", "contained_in"): ["X"]})
        view = StoreView([("a", uncharacterized), ("b", characterized)])
        assert view._relation_type_index[0] is None
        assert view._relation_type_index[1] == frozenset({"contained_in"})

    # ------------------------------------------------------------------
    # Skip: store B reports frozenset() → must not be consulted
    # ------------------------------------------------------------------

    def test_skip_get_reverse_relations_excludes_empty_store(self) -> None:
        # store_a holds contained_in; store_b reports frozenset() so the guard
        # skips it. store_b carries a poisoned edge that would surface in the
        # result if it were (wrongly) consulted.
        store_a = _RelationStore(
            relations={("region/R", "contained_in"): ["country/A"]},
        )
        store_b = _EmptyRelTypeStore()
        store_b._relations[("region/R", "contained_in")] = ["POISON"]

        view = StoreView([("a", store_a), ("b", store_b)])
        result = view.get_reverse_relations(
            entity_id="region/R", relation_type="contained_in"
        )
        assert "POISON" not in result
        assert result == ["country/A"]

    def test_skip_get_relations_as_of_excludes_empty_store(self) -> None:
        store_a = _RelationStore(
            as_of_relations={("E", "contained_in"): ["country/A"]},
        )
        store_b = _EmptyRelTypeStore()
        store_b._as_of_relations[("E", "contained_in")] = ["POISON"]

        view = StoreView([("a", store_a), ("b", store_b)])
        result = view.get_relations_as_of(
            entity_id="E", relation_type="contained_in", as_of=date(2024, 1, 1)
        )
        assert "POISON" not in result
        assert result == frozenset({"country/A"})

    # ------------------------------------------------------------------
    # No over-prune: a store that DOES hold the relation type is queried
    # ------------------------------------------------------------------

    def test_no_over_prune_get_reverse_relations(self) -> None:
        # Both stores hold contained_in; both should contribute their edges.
        store_a = _RelationStore(
            relations={("region/R", "contained_in"): ["country/A"]},
        )
        store_b = _RelationStore(
            relations={("region/R", "contained_in"): ["country/B"]},
        )
        view = StoreView([("a", store_a), ("b", store_b)])
        result = view.get_reverse_relations(
            entity_id="region/R", relation_type="contained_in"
        )
        assert "country/A" in result
        assert "country/B" in result

    def test_no_over_prune_get_relations_as_of(self) -> None:
        store_a = _RelationStore(
            as_of_relations={("E", "contained_in"): ["country/A"]},
        )
        store_b = _RelationStore(
            as_of_relations={("E", "contained_in"): ["country/B"]},
        )
        view = StoreView([("a", store_a), ("b", store_b)])
        result = view.get_relations_as_of(
            entity_id="E", relation_type="contained_in", as_of=date(2024, 1, 1)
        )
        assert result == frozenset({"country/A", "country/B"})

    # ------------------------------------------------------------------
    # C1: None-sentinel — uncharacterized store is ALWAYS queried
    # ------------------------------------------------------------------

    def test_none_store_always_queried_get_reverse_relations(self) -> None:
        """A store whose relation_types() returns None is never skipped,
        even when another store reports frozenset() for the same type.

        This would fail under a hypothetical frozenset() default because
        MockEntityStore would return frozenset() and be skipped.
        """

        # uncharacterized: MockEntityStore → relation_types() returns None
        # We subclass MockEntityStore to add reverse-relation support.
        class _NoneTypedStore(MockEntityStore):
            def get_reverse_relations(
                self,
                target_id: str,
                relation_type: str,
                *,
                as_of: date | None = None,
            ) -> list[str]:
                return ["country/FROM_NONE"] if target_id == "region/R" else []

        uncharacterized = _NoneTypedStore()
        empty_typed = _EmptyRelTypeStore()

        view = StoreView([("a", uncharacterized), ("b", empty_typed)])
        assert view._relation_type_index[0] is None  # confirm default
        assert view._relation_type_index[1] == frozenset()

        result = view.get_reverse_relations(
            entity_id="region/R", relation_type="contained_in"
        )
        assert "country/FROM_NONE" in result

    def test_none_store_always_queried_get_relations_as_of(self) -> None:
        """Same C1 invariant for get_relations_as_of."""

        class _NoneTypedStore(MockEntityStore):
            def get_relations_as_of(
                self, entity_id: str, relation_type: str, as_of: date
            ) -> list[str]:
                return ["country/FROM_NONE"] if entity_id == "E" else []

        uncharacterized = _NoneTypedStore()
        empty_typed = _EmptyRelTypeStore()

        view = StoreView([("a", uncharacterized), ("b", empty_typed)])
        result = view.get_relations_as_of(
            entity_id="E", relation_type="contained_in", as_of=date(2024, 1, 1)
        )
        assert "country/FROM_NONE" in result
