"""Tests for GeoLinker."""

from resolvekit.core.linking import Linker
from resolvekit.core.model import EntityRecord
from resolvekit.core.store.interface import EntityStore


class MockGeoStore(EntityStore):
    """Minimal EntityStore stub for testing GeoLinker."""

    def __init__(self):
        self._entities_by_code: dict[str, list[str]] = {}
        self._entities: dict[str, dict] = {}

    def add_entity(
        self,
        entity_id: str,
        codes: dict[str, str] | None = None,
        entity_type: str = "Country",
    ) -> None:
        """Add an entity to the mock store."""
        self._entities[entity_id] = {"entity_type": entity_type}
        if codes:
            for system, value in codes.items():
                key = f"{system}:{value}"
                if key not in self._entities_by_code:
                    self._entities_by_code[key] = []
                self._entities_by_code[key].append(entity_id)

    def lookup_code(self, system: str, value_norm: str) -> list[str]:
        key = f"{system}:{value_norm}"
        return self._entities_by_code.get(key, [])

    def lookup_name_exact(
        self, value_norm: str, name_kinds: set[str] | None = None
    ) -> list[str]:
        return []

    def code_systems(self) -> frozenset[str]:
        return frozenset(key.split(":", 1)[0] for key in self._entities_by_code)

    def get_entity(self, entity_id: str) -> EntityRecord | None:
        return None

    def search_fulltext(
        self, query_norm: str, fields: set[str] | None = None, limit: int = 10
    ) -> list[tuple[str, float, int]]:
        return []

    def bulk_get_entities(self, entity_ids: list[str]) -> dict[str, EntityRecord]:
        return {}


class TestGeoLinker:
    """Tests for GeoLinker protocol compliance and behavior."""

    def test_satisfies_linker_protocol(self):
        """GeoLinker satisfies the Linker protocol."""
        from resolvekit.packs.geo.linker import GeoLinker

        linker = GeoLinker()
        assert isinstance(linker, Linker)

    def test_resolve_by_dcid_single_match(self):
        """Resolves link when dcid matches exactly one entity."""
        from resolvekit.packs.geo.linker import GeoLinker

        store = MockGeoStore()
        store.add_entity("geo/FRA", codes={"dcid": "geo/FRA", "iso3": "FRA"})

        linker = GeoLinker()
        result = linker.resolve_link(
            overlay_row={"dcid": "geo/FRA", "population": 67000000},
            link_keys=["dcid"],
            base_store=store,
        )

        assert result.status == "linked"
        assert result.entity_id == "geo/FRA"

    def test_resolve_by_iso3_single_match(self):
        """Resolves link when iso3 matches exactly one entity."""
        from resolvekit.packs.geo.linker import GeoLinker

        store = MockGeoStore()
        store.add_entity("geo/DEU", codes={"dcid": "geo/DEU", "iso3": "DEU"})

        linker = GeoLinker()
        result = linker.resolve_link(
            overlay_row={"iso3": "DEU", "gdp": 4000000000000},
            link_keys=["iso3"],
            base_store=store,
        )

        assert result.status == "linked"
        assert result.entity_id == "geo/DEU"

    def test_resolve_tries_keys_in_order(self):
        """Tries link keys in order until one succeeds."""
        from resolvekit.packs.geo.linker import GeoLinker

        store = MockGeoStore()
        store.add_entity("geo/GBR", codes={"dcid": "geo/GBR", "iso3": "GBR"})

        linker = GeoLinker()
        # dcid not in row, should fall back to iso3
        result = linker.resolve_link(
            overlay_row={"iso3": "GBR", "population": 67000000},
            link_keys=["dcid", "iso3"],
            base_store=store,
        )

        assert result.status == "linked"
        assert result.entity_id == "geo/GBR"

    def test_not_found_when_no_keys_match(self):
        """Returns not_found when no link keys produce a match."""
        from resolvekit.packs.geo.linker import GeoLinker

        store = MockGeoStore()
        store.add_entity("geo/USA", codes={"dcid": "geo/USA", "iso3": "USA"})

        linker = GeoLinker()
        result = linker.resolve_link(
            overlay_row={"iso3": "XXX"},  # Non-existent code
            link_keys=["dcid", "iso3"],
            base_store=store,
        )

        assert result.status == "not_found"

    def test_ambiguous_when_multiple_matches(self):
        """Returns ambiguous when multiple entities match."""
        from resolvekit.packs.geo.linker import GeoLinker

        store = MockGeoStore()
        # Two entities with same iso3 (historical scenario)
        store.add_entity("geo/USA", codes={"dcid": "geo/USA", "iso3": "USA"})
        store.add_entity(
            "geo/USA-historical", codes={"dcid": "geo/USA-historical", "iso3": "USA"}
        )

        linker = GeoLinker()
        result = linker.resolve_link(
            overlay_row={"iso3": "USA"},
            link_keys=["iso3"],
            base_store=store,
        )

        assert result.status == "ambiguous"
        assert set(result.candidates) == {"geo/USA", "geo/USA-historical"}

    def test_not_found_when_key_missing_from_row(self):
        """Returns not_found when all link keys are missing from row."""
        from resolvekit.packs.geo.linker import GeoLinker

        store = MockGeoStore()
        store.add_entity("geo/USA", codes={"dcid": "geo/USA"})

        linker = GeoLinker()
        result = linker.resolve_link(
            overlay_row={"name": "United States"},  # No dcid or iso3
            link_keys=["dcid", "iso3"],
            base_store=store,
        )

        assert result.status == "not_found"

    def test_invalid_key_for_unknown_system(self):
        """Returns invalid_key for unknown code systems."""
        from resolvekit.packs.geo.linker import GeoLinker

        store = MockGeoStore()

        linker = GeoLinker()
        result = linker.resolve_link(
            overlay_row={"unknown_code": "ABC123"},
            link_keys=["unknown_code"],
            base_store=store,
        )

        assert result.status == "invalid_key"
        assert result.message is not None
        assert "unknown_code" in result.message

    def test_resolve_by_geonameid(self):
        """Resolves link by geonameid."""
        from resolvekit.packs.geo.linker import GeoLinker

        store = MockGeoStore()
        store.add_entity("geo/FRA", codes={"geonameid": "3017382"})

        linker = GeoLinker()
        result = linker.resolve_link(
            overlay_row={"geonameid": "3017382"},
            link_keys=["geonameid"],
            base_store=store,
        )

        assert result.status == "linked"
        assert result.entity_id == "geo/FRA"

    def test_resolve_by_iso2(self):
        """Resolves link by iso2."""
        from resolvekit.packs.geo.linker import GeoLinker

        store = MockGeoStore()
        store.add_entity("geo/FRA", codes={"iso2": "FR"})

        linker = GeoLinker()
        result = linker.resolve_link(
            overlay_row={"iso2": "FR"},
            link_keys=["iso2"],
            base_store=store,
        )

        assert result.status == "linked"
        assert result.entity_id == "geo/FRA"
