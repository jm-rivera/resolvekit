"""Tests for CompositeStore overlay behavior."""


def test_composite_store_precedence():
    from resolvekit.core.model import EntityRecord
    from resolvekit.core.store import EntityStore
    from resolvekit.core.store.composite import CompositeStore

    class BaseStore(EntityStore):
        def get_entity(self, entity_id: str):
            if entity_id == "country/USA":
                return EntityRecord(
                    entity_id="country/USA",
                    entity_type="geo.country",
                    canonical_name="United States",
                    canonical_name_norm="united states",
                )
            return None

        def lookup_code(self, system, value_norm):
            return ["country/USA"] if value_norm == "us" else []

        def lookup_name_exact(self, value_norm, name_kinds=None):
            return []

        def search_fulltext(self, query_norm, fields=None, limit=10):
            return []

        def bulk_get_entities(self, entity_ids):
            return {
                eid: self.get_entity(eid) for eid in entity_ids if self.get_entity(eid)
            }

    class OverlayStore(BaseStore):
        def get_entity(self, entity_id: str):
            if entity_id == "country/USA":
                return EntityRecord(
                    entity_id="country/USA",
                    entity_type="geo.country",
                    canonical_name="USA (Override)",
                    canonical_name_norm="usa override",
                )
            return None

    store = CompositeStore([OverlayStore(), BaseStore()])
    entity = store.get_entity("country/USA")
    assert entity is not None
    assert entity.canonical_name == "USA (Override)"


def test_composite_store_merges_lookups():
    from resolvekit.core.store import EntityStore
    from resolvekit.core.store.composite import CompositeStore

    class StoreA(EntityStore):
        def get_entity(self, entity_id):
            return None

        def lookup_code(self, system, value_norm):
            return ["id/A"] if value_norm == "x" else []

        def lookup_name_exact(self, value_norm, name_kinds=None):
            return []

        def search_fulltext(self, query_norm, fields=None, limit=10):
            return []

        def bulk_get_entities(self, entity_ids):
            return {}

    class StoreB(StoreA):
        def lookup_code(self, system, value_norm):
            return ["id/B"] if value_norm == "x" else []

    store = CompositeStore([StoreA(), StoreB()])
    ids = store.lookup_code("iso2", "x")
    assert ids == ["id/A", "id/B"]


def test_composite_store_merges_relations():
    from resolvekit.core.store import EntityStore
    from resolvekit.core.store.composite import CompositeStore

    class StoreA(EntityStore):
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

        def get_relations(self, entity_id, relation_type=None):
            if entity_id == "city/PAR" and relation_type == "contained_in":
                return ["admin1/FR-IDF"]
            return []

    class StoreB(StoreA):
        def get_relations(self, entity_id, relation_type=None):
            if entity_id == "city/PAR" and relation_type == "contained_in":
                return ["country/FRA"]
            return []

    store = CompositeStore([StoreA(), StoreB()])

    assert store.get_relations("city/PAR", "contained_in") == [
        "admin1/FR-IDF",
        "country/FRA",
    ]
