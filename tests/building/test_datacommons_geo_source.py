"""Tests for Data Commons geo source adapter normalization behavior."""

from __future__ import annotations

from types import MethodType, SimpleNamespace

from resolvekit.builder.sources.datacommons.geo import DataCommonsGeoSourceAdapter
from resolvekit.builder.sources.datacommons.geo.mappings import to_geo_entity_type


def test_get_aliases_keeps_short_valid_tokens() -> None:
    adapter = DataCommonsGeoSourceAdapter(languages=[])

    def fake_get_property_values(
        self, entity_ids, properties, chunk_size=1000, **kwargs
    ):
        _ = (entity_ids, properties, chunk_size, kwargs)
        return {
            "country/USA": {
                "alternateName": [
                    SimpleNamespace(value="USA", provenanceId="source/a"),
                    SimpleNamespace(value="US", provenanceId="source/b"),
                ]
            }
        }

    def fake_get_entity_names(self, entity_ids, *, lang):
        _ = (entity_ids, lang)
        return {}

    def fake_get_entity_name_rows(self, entity_ids, *, lang, fallback_lang=None):
        _ = (entity_ids, lang, fallback_lang)
        return {}

    def fake_get_parents(self, entity_ids):
        _ = entity_ids
        return {}

    adapter._dc_api._get_property_values = MethodType(
        fake_get_property_values, adapter._dc_api
    )
    adapter._dc_api.get_entity_names = MethodType(
        fake_get_entity_names, adapter._dc_api
    )
    adapter._dc_api.get_entity_name_rows = MethodType(
        fake_get_entity_name_rows, adapter._dc_api
    )
    adapter._dc_api.get_parents = MethodType(fake_get_parents, adapter._dc_api)

    raw_chunk = adapter.fetch_raw_chunk("geo", ["country/USA"])
    aliases = raw_chunk.aliases["country/USA"]

    assert aliases
    assert {row.alias_text for row in aliases} == {"USA", "US"}


def test_filter_discovered_entities_by_canonical_type() -> None:
    adapter = DataCommonsGeoSourceAdapter(languages=[])

    def fake_get_entity_types(self, entity_ids):
        _ = entity_ids
        return {
            "country/USA": "Country",
            "region/NAM": "GeoRegion",
            "state/CA": "AdministrativeArea",
        }

    adapter._dc_api.get_entity_types = MethodType(
        fake_get_entity_types, adapter._dc_api
    )

    filtered = adapter.filter_discovered_entities(
        "geo",
        ["country/USA", "region/NAM", "state/CA"],
        ["geo.country"],
    )

    assert filtered == ["country/USA"]


def test_filter_discovered_entities_by_admin_level() -> None:
    adapter = DataCommonsGeoSourceAdapter(languages=[])

    def fake_get_entity_types(self, entity_ids):
        _ = entity_ids
        return {
            "admin/CA": "AdministrativeArea",
            "admin/SF": "AdministrativeArea",
        }

    def fake_get_admin_levels(
        self, entity_ids, *, entity_types=None, parents_by_entity=None
    ):
        _ = (entity_ids, entity_types, parents_by_entity)
        return {
            "admin/CA": 1,
            "admin/SF": 2,
        }

    adapter._dc_api.get_entity_types = MethodType(
        fake_get_entity_types, adapter._dc_api
    )
    adapter._dc_api.get_admin_levels = MethodType(
        fake_get_admin_levels, adapter._dc_api
    )

    filtered = adapter.filter_discovered_entities(
        "geo",
        ["admin/CA", "admin/SF"],
        ["geo.admin2"],
    )

    assert filtered == ["admin/SF"]


def test_geo_entity_type_mapping_supports_multiple_admin_levels() -> None:
    assert to_geo_entity_type("AdministrativeArea", {"admin_level": 1}) == "geo.admin1"
    assert to_geo_entity_type("AdministrativeArea", {"admin_level": 3}) == "geo.admin3"
    assert to_geo_entity_type("AdministrativeArea1", {}) == "geo.admin1"
    assert to_geo_entity_type("AdministrativeArea3", {}) == "geo.admin3"
    assert to_geo_entity_type("GeoRegion", {}) == "geo.region"
    assert to_geo_entity_type("ContinentalUnion", {}) == "geo.continental_union"
    assert to_geo_entity_type("Region", {}) == "geo.region"
