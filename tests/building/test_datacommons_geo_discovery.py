"""Tests for Data Commons geo discovery behavior."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar, cast

from resolvekit.builder.sources.datacommons.geo._ordered_emitter import (
    OrderedBatchEmitter,
)
from resolvekit.builder.sources.datacommons.geo._progress_context import (
    StreamProgressContext,
)
from resolvekit.builder.sources.datacommons.geo._type_mappings import (
    canonical_type_mapping,
)
from resolvekit.builder.sources.datacommons.geo.dc_api import GeoDcApi
from resolvekit.builder.sources.datacommons.geo.discovery import (
    discover_entities,
    discover_entities_filtered,
    discover_entities_filtered_incremental,
)
from resolvekit.builder.sources.datacommons.geo.mappings import (
    DISCOVERY_MAX_WORKERS,
    DISCOVERY_PARENT_BATCH_SIZE,
    PLACE_TYPE_ADMINISTRATIVE_AREA,
    PLACE_TYPE_CITY,
    PLACE_TYPE_COUNTRY,
    PLACE_TYPE_GEO_REGION,
)

T = TypeVar("T")


class _FakeGeoDcApi:
    def __init__(self) -> None:
        self.single_calls: list[tuple[str, str]] = []
        self.batch_calls: list[tuple[str, tuple[str, ...], int, int]] = []
        self.type_calls: list[str] = []

    def get_place_types(self) -> list[str]:
        return [
            PLACE_TYPE_COUNTRY,
            PLACE_TYPE_GEO_REGION,
            PLACE_TYPE_ADMINISTRATIVE_AREA,
            PLACE_TYPE_CITY,
        ]

    def get_geo_region_types(self) -> list[str]:
        return [PLACE_TYPE_GEO_REGION]

    def get_places(self, *, place_type: str, parent_place: str) -> list[str]:
        self.single_calls.append((place_type, parent_place))
        if (place_type, parent_place) == (PLACE_TYPE_GEO_REGION, "Earth"):
            return ["geo/region-1"]
        if (place_type, parent_place) == (PLACE_TYPE_COUNTRY, "Earth"):
            return ["country/a", "country/b"]
        return []

    def get_places_by_parents(
        self,
        *,
        place_type: str,
        parent_places: list[str],
        chunk_size: int,
        max_workers: int,
        on_chunk_complete: Any = None,
    ) -> dict[str, list[str]]:
        self.batch_calls.append(
            (
                place_type,
                tuple(parent_places),
                chunk_size,
                max_workers,
            )
        )
        lookup = {
            (
                PLACE_TYPE_ADMINISTRATIVE_AREA,
                ("country/a", "country/b"),
            ): {
                "country/a": ["admin/a1", "admin/a2"],
                "country/b": ["admin/b1"],
            },
            (
                PLACE_TYPE_ADMINISTRATIVE_AREA,
                ("admin/a1", "admin/a2", "admin/b1"),
            ): {
                "admin/a1": ["admin/a1-1"],
                "admin/a2": [],
                "admin/b1": [],
            },
            (
                PLACE_TYPE_ADMINISTRATIVE_AREA,
                ("admin/a1-1",),
            ): {"admin/a1-1": []},
            (
                PLACE_TYPE_CITY,
                ("country/a", "country/b"),
            ): {
                "country/a": ["city/a1"],
                "country/b": ["city/b1", "city/b2"],
            },
            (
                PLACE_TYPE_CITY,
                ("admin/a1", "admin/a2", "admin/b1"),
            ): {
                "admin/a1": ["city/a1-1"],
                "admin/a2": [],
                "admin/b1": [],
            },
            (
                PLACE_TYPE_CITY,
                ("admin/a1-1",),
            ): {"admin/a1-1": ["city/a1-2"]},
        }
        result = lookup.get((place_type, tuple(parent_places)), {})
        if on_chunk_complete is not None:
            on_chunk_complete(0, parent_places, result)
        return result

    def get_entities_by_type(self, *, raw_type: str) -> list[str]:
        self.type_calls.append(raw_type)
        return []


class _FakeSpecificGeoDcApi(_FakeGeoDcApi):
    def get_place_types(self) -> list[str]:
        return [
            PLACE_TYPE_COUNTRY,
            PLACE_TYPE_GEO_REGION,
            "AdministrativeArea1",
            "AdministrativeArea2",
            PLACE_TYPE_CITY,
        ]

    def get_places_by_parents(
        self,
        *,
        place_type: str,
        parent_places: list[str],
        chunk_size: int,
        max_workers: int,
        on_chunk_complete: Any = None,
    ) -> dict[str, list[str]]:
        self.batch_calls.append(
            (
                place_type,
                tuple(parent_places),
                chunk_size,
                max_workers,
            )
        )
        lookup = {
            ("AdministrativeArea1", ("country/a", "country/b")): {
                "country/a": ["admin/a1"],
                "country/b": ["admin/b1"],
            },
            ("AdministrativeArea2", ("admin/a1", "admin/b1")): {
                "admin/a1": ["admin/a1-1"],
                "admin/b1": [],
            },
            (PLACE_TYPE_CITY, ("country/a", "country/b")): {
                "country/a": ["city/a1"],
                "country/b": ["city/b1"],
            },
            (PLACE_TYPE_CITY, ("admin/a1", "admin/b1")): {
                "admin/a1": ["city/a1-1"],
                "admin/b1": [],
            },
            (PLACE_TYPE_CITY, ("admin/a1-1",)): {
                "admin/a1-1": ["city/a1-2"],
            },
        }
        result = lookup.get((place_type, tuple(parent_places)), {})
        if on_chunk_complete is not None:
            on_chunk_complete(0, parent_places, result)
        return result


class _FakeGeoRegionSubclassApi(_FakeGeoDcApi):
    def get_geo_region_types(self) -> list[str]:
        return [PLACE_TYPE_GEO_REGION, "ContinentalUnion"]

    def get_places(self, *, place_type: str, parent_place: str) -> list[str]:
        self.single_calls.append((place_type, parent_place))
        if (place_type, parent_place) == (PLACE_TYPE_GEO_REGION, "Earth"):
            return ["geo/region-1"]
        if (place_type, parent_place) == ("ContinentalUnion", "Earth"):
            return ["geo/EuropeanUnion"]
        if (place_type, parent_place) == (PLACE_TYPE_COUNTRY, "Earth"):
            return ["country/a", "country/b"]
        return []


class _FakeGeoRegionTypeFallbackApi(_FakeGeoDcApi):
    def get_geo_region_types(self) -> list[str]:
        return [PLACE_TYPE_GEO_REGION, "ContinentalUnion"]

    def get_places(self, *, place_type: str, parent_place: str) -> list[str]:
        self.single_calls.append((place_type, parent_place))
        if (place_type, parent_place) == (PLACE_TYPE_GEO_REGION, "Earth"):
            return ["geo/region-1"]
        if (place_type, parent_place) == (PLACE_TYPE_COUNTRY, "Earth"):
            return ["country/a", "country/b"]
        return []

    def get_entities_by_type(self, *, raw_type: str) -> list[str]:
        self.type_calls.append(raw_type)
        if raw_type == "ContinentalUnion":
            return ["geo/EuropeanUnion"]
        return []


class _FlakyGeoRegionSchemaApi(_FakeGeoRegionSubclassApi):
    def __init__(self) -> None:
        super().__init__()
        self.schema_attempts = 0

    def get_geo_region_types(self) -> list[str]:
        self.schema_attempts += 1
        if self.schema_attempts == 1:
            raise RuntimeError("temporary geo schema failure")
        return super().get_geo_region_types()


def test_discovery_recurses_admin_hierarchy_and_collects_nested_cities() -> None:
    api = _FakeGeoDcApi()
    retry_calls: list[str] = []

    def with_retries(fn: Callable[..., T], **kwargs: Any) -> T:
        retry_calls.append(fn.__name__)
        return fn(**kwargs)

    discovered = discover_entities(
        dc_api=cast(GeoDcApi, api),
        with_retries=with_retries,
    )

    assert discovered == [
        "UNGeoRegion",
        "admin/a1",
        "admin/a1-1",
        "admin/a2",
        "admin/b1",
        "city/a1",
        "city/a1-1",
        "city/a1-2",
        "city/b1",
        "city/b2",
        "country/a",
        "country/b",
        "geo/region-1",
    ]
    assert api.single_calls == [
        (PLACE_TYPE_GEO_REGION, "Earth"),
        (PLACE_TYPE_COUNTRY, "Earth"),
    ]
    assert sorted(api.batch_calls) == sorted(
        [
            (
                PLACE_TYPE_ADMINISTRATIVE_AREA,
                ("country/a", "country/b"),
                DISCOVERY_PARENT_BATCH_SIZE,
                DISCOVERY_MAX_WORKERS,
            ),
            (
                PLACE_TYPE_ADMINISTRATIVE_AREA,
                ("admin/a1", "admin/a2", "admin/b1"),
                DISCOVERY_PARENT_BATCH_SIZE,
                DISCOVERY_MAX_WORKERS,
            ),
            (
                PLACE_TYPE_ADMINISTRATIVE_AREA,
                ("admin/a1-1",),
                DISCOVERY_PARENT_BATCH_SIZE,
                DISCOVERY_MAX_WORKERS,
            ),
            (
                PLACE_TYPE_CITY,
                ("country/a", "country/b"),
                DISCOVERY_PARENT_BATCH_SIZE,
                DISCOVERY_MAX_WORKERS,
            ),
            (
                PLACE_TYPE_CITY,
                ("admin/a1", "admin/a2", "admin/b1"),
                DISCOVERY_PARENT_BATCH_SIZE,
                DISCOVERY_MAX_WORKERS,
            ),
            (
                PLACE_TYPE_CITY,
                ("admin/a1-1",),
                DISCOVERY_PARENT_BATCH_SIZE,
                DISCOVERY_MAX_WORKERS,
            ),
            (
                PLACE_TYPE_GEO_REGION,
                ("geo/region-1",),
                DISCOVERY_PARENT_BATCH_SIZE,
                DISCOVERY_MAX_WORKERS,
            ),
        ]
    )
    assert retry_calls == [
        "get_place_types",
        "get_geo_region_types",
        "get_places",
        "get_places_by_parents",  # second-level GeoRegion subregion call (UN M.49 fix)
        "get_places",
        "get_places_by_parents",
        "get_places_by_parents",
        "get_places_by_parents",
        "get_places_by_parents",
        "get_places_by_parents",
        "get_places_by_parents",
    ]


def test_discovery_filtered_country_with_relation_targets_skips_child_scans() -> None:
    api = _FakeGeoDcApi()
    retry_calls: list[str] = []

    def with_retries(fn: Callable[..., T], **kwargs: Any) -> T:
        retry_calls.append(fn.__name__)
        return fn(**kwargs)

    discovered = discover_entities_filtered(
        dc_api=cast(GeoDcApi, api),
        with_retries=with_retries,
        include_entity_types=["geo.country"],
        include_relation_targets=True,
    )

    assert discovered == ["UNGeoRegion", "country/a", "country/b", "geo/region-1"]
    assert api.batch_calls == []
    assert sorted(api.single_calls) == sorted(
        [
            (PLACE_TYPE_COUNTRY, "Earth"),
            (PLACE_TYPE_GEO_REGION, "Earth"),
        ]
    )
    assert retry_calls == [
        "get_place_types",
        "get_geo_region_types",
        "get_places",
        "get_places",
    ]


def test_discovery_filtered_admin2_and_city_walks_admin_hierarchy() -> None:
    api = _FakeGeoDcApi()

    discovered = discover_entities_filtered(
        dc_api=cast(GeoDcApi, api),
        with_retries=lambda fn, **kwargs: fn(**kwargs),
        include_entity_types=["geo.admin2", "geo.city"],
        include_relation_targets=False,
    )

    assert discovered == [
        "admin/a1-1",
        "city/a1",
        "city/a1-1",
        "city/a1-2",
        "city/b1",
        "city/b2",
    ]


def test_discovery_uses_specific_admin_place_types_when_available() -> None:
    api = _FakeSpecificGeoDcApi()

    discovered = discover_entities_filtered(
        dc_api=cast(GeoDcApi, api),
        with_retries=lambda fn, **kwargs: fn(**kwargs),
        include_entity_types=["geo.admin1", "geo.admin2", "geo.city"],
        include_relation_targets=False,
    )

    assert discovered == [
        "admin/a1",
        "admin/a1-1",
        "admin/b1",
        "city/a1",
        "city/a1-1",
        "city/a1-2",
        "city/b1",
    ]
    assert (
        "AdministrativeArea1",
        ("country/a", "country/b"),
        DISCOVERY_PARENT_BATCH_SIZE,
        DISCOVERY_MAX_WORKERS,
    ) in api.batch_calls


def test_filtered_geo_discovery_incremental_emits_only_requested_units() -> None:
    api = _FakeGeoDcApi()
    emitted: list[tuple[str, list[str]]] = []
    progress: list[dict[str, Any]] = []

    discover_entities_filtered_incremental(
        dc_api=cast(GeoDcApi, api),
        with_retries=lambda fn, **kwargs: fn(**kwargs),
        include_entity_types=["geo.admin2", "geo.city"],
        include_relation_targets=False,
        emit_entities=lambda unit, entity_ids, _metadata: emitted.append(
            (unit, list(entity_ids))
        ),
        emit_progress=lambda payload: progress.append(dict(payload)),
    )

    assert emitted == [
        ("cities", ["city/a1", "city/b1", "city/b2"]),
        ("cities", ["city/a1-1"]),
        ("admin2", ["admin/a1-1"]),
        ("cities", ["city/a1-2"]),
    ]
    assert {payload["unit"] for payload in progress if "unit" in payload} >= {
        "admin1",
        "admin2",
        "admin3",
        "cities",
    }
    assert all(unit != "admin1" for unit, _entity_ids in emitted)


def test_filtered_geo_discovery_queries_geo_region_subclasses_from_earth() -> None:
    api = _FakeGeoRegionSubclassApi()

    discovered = discover_entities_filtered(
        dc_api=cast(GeoDcApi, api),
        with_retries=lambda fn, **kwargs: fn(**kwargs),
        include_entity_types=["geo.continental_union"],
        include_relation_targets=False,
    )

    assert discovered == ["geo/EuropeanUnion"]
    assert ("ContinentalUnion", "Earth") in api.single_calls


def test_canonical_type_mapping_keeps_geo_region_reserved_for_georegion() -> None:
    mapping = canonical_type_mapping(
        ["AdministrativeArea1", "Region", "ContinentalUnion"],
        {"GeoRegion", "ContinentalUnion", "Region"},
    )

    assert mapping["geo.region"] == {"GeoRegion", "Region"}
    assert "geo.region_like" not in mapping


def test_filtered_geo_discovery_falls_back_to_inverse_type_for_region_subclasses() -> (
    None
):
    api = _FakeGeoRegionTypeFallbackApi()

    discovered = discover_entities_filtered(
        dc_api=cast(GeoDcApi, api),
        with_retries=lambda fn, **kwargs: fn(**kwargs),
        include_entity_types=["geo.continental_union"],
        include_relation_targets=False,
    )

    assert discovered == ["geo/EuropeanUnion"]
    assert api.type_calls == ["ContinentalUnion"]


def test_filtered_geo_discovery_retries_geo_region_type_enumeration() -> None:
    api = _FlakyGeoRegionSchemaApi()

    def with_retries(fn: Callable[..., T], **kwargs: Any) -> T:
        for _ in range(2):
            try:
                return fn(**kwargs)
            except RuntimeError:
                continue
        raise AssertionError("retry budget exhausted")

    discovered = discover_entities_filtered(
        dc_api=cast(GeoDcApi, api),
        with_retries=with_retries,
        include_entity_types=["geo.continental_union"],
        include_relation_targets=False,
    )

    assert discovered == ["geo/EuropeanUnion"]
    assert api.schema_attempts == 2


def test_ordered_discovery_batches_emits_in_order_when_completed_out_of_order() -> None:
    """Verify OrderedBatchEmitter re-orders out-of-order batch completions."""
    emitted: list[tuple[str, list[str]]] = []
    progress_events: list[dict[str, Any]] = []

    parent_batches = [
        ["country/a"],
        ["country/b"],
        ["country/c"],
    ]

    ordered = OrderedBatchEmitter(
        unit="admin1",
        parent_batches=parent_batches,
        emit_entities=lambda unit, ids, meta: emitted.append((unit, list(ids))),
        emit_progress=lambda payload: progress_events.append(dict(payload)),
        progress=StreamProgressContext(raw_type="AdministrativeArea1"),
    )

    # Complete batches out of order: 2, 0, 1
    ordered.record(2, {"country/c": ["admin/c1", "admin/c2"]})
    assert emitted == [], "batch 2 should be held until 0 and 1 complete"

    ordered.record(0, {"country/a": ["admin/a1"]})
    assert len(emitted) == 1, "batch 0 should flush immediately"
    assert emitted[0] == ("admin1", ["admin/a1"])

    ordered.record(1, {"country/b": ["admin/b1", "admin/b2"]})
    # Now batch 1 and 2 should both flush
    assert len(emitted) == 3
    assert emitted[1] == ("admin1", ["admin/b1", "admin/b2"])
    assert emitted[2] == ("admin1", ["admin/c1", "admin/c2"])

    # Final ordered_ids should be in batch order
    assert ordered.ordered_ids == [
        "admin/a1",
        "admin/b1",
        "admin/b2",
        "admin/c1",
        "admin/c2",
    ]
    assert ordered.discovered_total == 5
