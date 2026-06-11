"""Tests for MergingCompositeStore."""

from resolvekit.core.model.entity import (
    CodeRecord,
    EntityRecord,
    NameRecord,
)


class MockNormalizer:
    """Mock normalizer for testing."""

    def normalize_name(self, value: str) -> str:
        return value.lower().strip()

    def normalize_code(self, system: str, value: str) -> str:
        return value.upper().strip()


class MockStore:
    """Mock EntityStore for testing."""

    def __init__(self, entities: dict[str, EntityRecord] | None = None):
        self._entities = entities or {}
        self._codes: dict[str, list[str]] = {}
        self._relations: dict[tuple[str, str | None], list[str]] = {}

    def add_entity(self, entity: EntityRecord) -> None:
        self._entities[entity.entity_id] = entity
        for code in entity.codes:
            key = f"{code.system}:{code.value_norm}"
            if key not in self._codes:
                self._codes[key] = []
            self._codes[key].append(entity.entity_id)

    def add_relations(
        self,
        entity_id: str,
        targets: list[str],
        *,
        relation_type: str = "contained_in",
    ) -> None:
        self._relations[(entity_id, relation_type)] = list(targets)

    def get_entity(self, entity_id: str) -> EntityRecord | None:
        return self._entities.get(entity_id)

    def lookup_code(self, system: str, value_norm: str) -> list[str]:
        key = f"{system}:{value_norm}"
        return self._codes.get(key, [])

    def lookup_name_exact(
        self, value_norm: str, name_kinds: set[str] | None = None
    ) -> list[str]:
        return []

    def search_fulltext(
        self, query_norm: str, fields: set[str] | None = None, limit: int = 10
    ) -> list[tuple[str, float, int]]:
        return []

    def bulk_get_entities(self, entity_ids: list[str]) -> dict[str, EntityRecord]:
        return {eid: e for eid, e in self._entities.items() if eid in entity_ids}

    def get_relations(
        self, entity_id: str, relation_type: str | None = None
    ) -> list[str]:
        return self._relations.get((entity_id, relation_type), [])


class TestMergingCompositeStore:
    """Tests for MergingCompositeStore."""

    def test_get_entity_merges_base_and_overlay(self):
        """get_entity merges entity from all stores."""
        from resolvekit.core.store.merging import MergingCompositeStore

        base_entity = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            attributes={"population": 65000000},
        )

        overlay_entity = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="French Republic",
            canonical_name_norm="french republic",
            attributes={"gdp_usd": 2700000000000},
        )

        base_store = MockStore()
        base_store.add_entity(base_entity)

        overlay_store = MockStore()
        overlay_store.add_entity(overlay_entity)

        # Base first, overlays after (in precedence order)
        store = MergingCompositeStore(
            stores=[base_store, overlay_store],
            normalizer=MockNormalizer(),
        )

        merged = store.get_entity("geo/FRA")

        assert merged is not None
        assert merged.canonical_name == "French Republic"  # Overlay wins
        assert merged.attributes["population"] == 65000000  # From base
        assert merged.attributes["gdp_usd"] == 2700000000000  # From overlay

    def test_get_entity_returns_none_if_not_found(self):
        """get_entity returns None if entity not in any store."""
        from resolvekit.core.store.merging import MergingCompositeStore

        store = MergingCompositeStore(
            stores=[MockStore()],
            normalizer=MockNormalizer(),
        )

        assert store.get_entity("nonexistent") is None

    def test_get_entity_single_store_no_merge(self):
        """get_entity with single store returns entity unchanged."""
        from resolvekit.core.store.merging import MergingCompositeStore

        entity = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
        )

        base_store = MockStore()
        base_store.add_entity(entity)

        store = MergingCompositeStore(
            stores=[base_store],
            normalizer=MockNormalizer(),
        )

        result = store.get_entity("geo/FRA")
        assert result is not None
        assert result.entity_id == "geo/FRA"

    def test_get_entity_merges_names_from_all_stores(self):
        """get_entity merges names from all stores with dedup."""
        from resolvekit.core.store.merging import MergingCompositeStore

        base_entity = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            names=[
                NameRecord(
                    value="France", value_norm="france", kind="canonical", lang="en"
                ),
            ],
        )

        overlay_entity = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            names=[
                NameRecord(
                    value="République française",
                    value_norm="république française",
                    kind="official",
                    lang="fr",
                ),
            ],
        )

        base_store = MockStore()
        base_store.add_entity(base_entity)

        overlay_store = MockStore()
        overlay_store.add_entity(overlay_entity)

        store = MergingCompositeStore(
            stores=[base_store, overlay_store],
            normalizer=MockNormalizer(),
        )

        merged = store.get_entity("geo/FRA")
        assert merged is not None
        assert len(merged.names) == 2

    def test_get_entity_merges_codes_from_all_stores(self):
        """get_entity merges codes from all stores with dedup."""
        from resolvekit.core.store.merging import MergingCompositeStore

        base_entity = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            codes=[
                CodeRecord(system="iso3", value="FRA", value_norm="FRA"),
            ],
        )

        overlay_entity = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            codes=[
                CodeRecord(system="geonameid", value="3017382", value_norm="3017382"),
            ],
        )

        base_store = MockStore()
        base_store.add_entity(base_entity)

        overlay_store = MockStore()
        overlay_store.add_entity(overlay_entity)

        store = MergingCompositeStore(
            stores=[base_store, overlay_store],
            normalizer=MockNormalizer(),
        )

        merged = store.get_entity("geo/FRA")
        assert merged is not None
        assert len(merged.codes) == 2

    def test_bulk_get_entities_merges_all(self):
        """bulk_get_entities merges entities from all stores."""
        from resolvekit.core.store.merging import MergingCompositeStore

        base_entity = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            attributes={"population": 65000000},
        )

        overlay_entity = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="French Republic",
            canonical_name_norm="french republic",
            attributes={"gdp_usd": 2700000000000},
        )

        base_store = MockStore()
        base_store.add_entity(base_entity)

        overlay_store = MockStore()
        overlay_store.add_entity(overlay_entity)

        store = MergingCompositeStore(
            stores=[base_store, overlay_store],
            normalizer=MockNormalizer(),
        )

        results = store.bulk_get_entities(["geo/FRA"])
        assert "geo/FRA" in results
        assert results["geo/FRA"].canonical_name == "French Republic"

    def test_lookup_code_merges_results(self):
        """lookup_code merges IDs from all stores."""
        from resolvekit.core.store.merging import MergingCompositeStore

        base_entity = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            codes=[CodeRecord(system="iso3", value="FRA", value_norm="FRA")],
        )

        base_store = MockStore()
        base_store.add_entity(base_entity)

        overlay_store = MockStore()  # Empty

        store = MergingCompositeStore(
            stores=[base_store, overlay_store],
            normalizer=MockNormalizer(),
        )

        ids = store.lookup_code("iso3", "FRA")
        assert ids == ["geo/FRA"]

    def test_multiple_overlays_merge_in_order(self):
        """Multiple overlays merge in precedence order."""
        from resolvekit.core.store.merging import MergingCompositeStore

        base = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            attributes={"population": 60000000},
        )

        overlay1 = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            attributes={"population": 65000000, "area_km2": 643801},
        )

        overlay2 = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="French Republic",
            canonical_name_norm="french republic",
            attributes={"population": 68000000},
        )

        base_store = MockStore()
        base_store.add_entity(base)

        overlay1_store = MockStore()
        overlay1_store.add_entity(overlay1)

        overlay2_store = MockStore()
        overlay2_store.add_entity(overlay2)

        # Order: base, overlay1, overlay2 (later has higher precedence)
        store = MergingCompositeStore(
            stores=[base_store, overlay1_store, overlay2_store],
            normalizer=MockNormalizer(),
        )

        merged = store.get_entity("geo/FRA")
        assert merged is not None
        assert merged.canonical_name == "French Republic"  # From overlay2
        assert merged.attributes["population"] == 68000000  # From overlay2
        assert merged.attributes["area_km2"] == 643801  # From overlay1

    def test_entity_only_in_overlay_returned(self):
        """Entity only in overlay store is returned."""
        from resolvekit.core.store.merging import MergingCompositeStore

        overlay_entity = EntityRecord(
            entity_id="geo/NEW",
            entity_type="geo.country",
            canonical_name="New Country",
            canonical_name_norm="new country",
        )

        base_store = MockStore()  # Empty
        overlay_store = MockStore()
        overlay_store.add_entity(overlay_entity)

        store = MergingCompositeStore(
            stores=[base_store, overlay_store],
            normalizer=MockNormalizer(),
        )

        result = store.get_entity("geo/NEW")
        assert result is not None
        assert result.canonical_name == "New Country"

    def test_get_relations_merges_base_and_overlay(self):
        """get_relations merges relation targets across stores."""
        from resolvekit.core.store.merging import MergingCompositeStore

        base_store = MockStore()
        base_store.add_entity(
            EntityRecord(
                entity_id="city/PAR",
                entity_type="geo.city",
                canonical_name="Paris",
                canonical_name_norm="paris",
            )
        )
        base_store.add_relations("city/PAR", ["admin1/FR-IDF"])

        overlay_store = MockStore()
        overlay_store.add_entity(
            EntityRecord(
                entity_id="city/PAR",
                entity_type="geo.city",
                canonical_name="Paris",
                canonical_name_norm="paris",
            )
        )
        overlay_store.add_relations("city/PAR", ["country/FRA"])

        store = MergingCompositeStore(
            stores=[base_store, overlay_store],
            normalizer=MockNormalizer(),
        )

        assert store.get_relations("city/PAR", "contained_in") == [
            "admin1/FR-IDF",
            "country/FRA",
        ]
