"""Tests for EntityStore interface."""

import pytest


class TestEntityStoreInterface:
    """Tests for EntityStore protocol/interface."""

    def test_interface_is_abstract(self):
        from resolvekit.core.store import EntityStore

        # Should not be instantiable directly
        with pytest.raises(TypeError):
            EntityStore()  # type: ignore

    def test_interface_defines_required_methods(self):
        from resolvekit.core.store import EntityStore

        # Check required methods exist
        methods = [
            "get_entity",
            "lookup_code",
            "lookup_name_exact",
            "search_fulltext",
            "bulk_get_entities",
        ]
        for method in methods:
            assert hasattr(EntityStore, method)
            assert callable(getattr(EntityStore, method))


class TestMockStore:
    """Test that a mock implementation works."""

    def test_mock_store_implements_interface(self):
        from resolvekit.core.model import EntityRecord
        from resolvekit.core.store import EntityStore

        class MockStore(EntityStore):
            def get_entity(self, entity_id: str) -> EntityRecord | None:
                if entity_id == "country/USA":
                    return EntityRecord(
                        entity_id="country/USA",
                        entity_type="geo.country",
                        canonical_name="United States",
                        canonical_name_norm="united states",
                    )
                return None

            def lookup_code(self, system: str, value_norm: str) -> list[str]:
                if system == "iso2" and value_norm == "us":
                    return ["country/USA"]
                return []

            def lookup_name_exact(
                self, value_norm: str, name_kinds: set[str] | None = None
            ) -> list[str]:
                return []

            def search_fulltext(
                self, query_norm: str, fields: set[str] | None = None, limit: int = 10
            ) -> list[tuple[str, float, int]]:
                return []

            def bulk_get_entities(
                self, entity_ids: list[str]
            ) -> dict[str, EntityRecord]:
                return {eid: e for eid in entity_ids if (e := self.get_entity(eid))}

        store = MockStore()
        assert isinstance(store, EntityStore)

        entity = store.get_entity("country/USA")
        assert entity is not None
        assert entity.entity_id == "country/USA"

        ids = store.lookup_code("iso2", "us")
        assert ids == ["country/USA"]
