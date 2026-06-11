"""Tests for GeoDcApi node-value parsing behavior."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from resolvekit.builder.sources.datacommons.client import DataCommons
from resolvekit.builder.sources.datacommons.constants import TYPE_OF_PROPERTY
from resolvekit.builder.sources.datacommons.geo.dc_api import GeoDcApi
from resolvekit.builder.sources.datacommons.node import walk_type_families


class _FakeRuntime:
    def __init__(self, payload):
        self._payload = payload

    def fetch_property_values(self, entity_ids, properties, chunk_size=1000, **kwargs):
        _ = (entity_ids, properties, chunk_size, kwargs)
        return self._payload


def test_get_entity_types_reads_dcid_when_value_missing() -> None:
    runtime = _FakeRuntime(
        {
            "country/USA": {
                TYPE_OF_PROPERTY: [SimpleNamespace(dcid="Country")],
            }
        }
    )
    api = GeoDcApi(cast(DataCommons, runtime))

    result = api.get_entity_types(["country/USA"])

    assert result == {"country/USA": "Country"}


def test_get_entity_types_reads_value_when_present() -> None:
    runtime = _FakeRuntime(
        {
            "region/NAM": {
                TYPE_OF_PROPERTY: [SimpleNamespace(value="GeoRegion", dcid="Ignored")],
            }
        }
    )
    api = GeoDcApi(cast(DataCommons, runtime))

    result = api.get_entity_types(["region/NAM"])

    assert result == {"region/NAM": "GeoRegion"}


def test_get_entity_types_prefers_most_specific_geo_type() -> None:
    runtime = _FakeRuntime(
        {
            "region/EU": {
                TYPE_OF_PROPERTY: [
                    SimpleNamespace(value="Place"),
                    SimpleNamespace(value="GeoRegion"),
                    SimpleNamespace(value="ContinentalUnion"),
                ],
                "subClassOf": [],
            },
            "GeoRegion": {
                "subClassOf": [SimpleNamespace(value="ContinentalUnion")],
            },
            "AdministrativeArea": {"subClassOf": []},
        }
    )
    api = GeoDcApi(cast(DataCommons, runtime))

    result = api.get_entity_types(["region/EU"])

    assert result == {"region/EU": "ContinentalUnion"}


def test_get_admin_levels_uses_direct_administrative_area_suffixes() -> None:
    runtime = _FakeRuntime({})
    api = GeoDcApi(cast(DataCommons, runtime))

    result = api.get_admin_levels(
        ["admin/CA", "admin/SF"],
        entity_types={
            "admin/CA": "AdministrativeArea1",
            "admin/SF": "AdministrativeArea2",
        },
        parents_by_entity={},
    )

    assert result == {
        "admin/CA": 1,
        "admin/SF": 2,
    }


def test_walk_type_families_stops_on_cycles() -> None:
    graph = {
        "GeoRegion": ["ContinentalUnion"],
        "ContinentalUnion": ["GeoRegion"],
    }

    depths, families = walk_type_families(
        roots=["GeoRegion"],
        fetch_children=lambda raw_type: graph.get(raw_type, []),
    )

    assert depths == {
        "GeoRegion": 0,
        "ContinentalUnion": 1,
    }
    assert families == {
        "GeoRegion": "GeoRegion",
        "ContinentalUnion": "GeoRegion",
    }
