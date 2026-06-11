"""Shared fakes and helpers for geo discovery characterization tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from resolvekit.builder.sources.datacommons.geo.mappings import (
    PLACE_TYPE_COUNTRY,
    PLACE_TYPE_GEO_REGION,
    ROOT_PLACE_DCID,
)
from resolvekit.builder.sources.discovery_events import DiscoveryProgressEvent
from resolvekit.builder.utils import chunk_list


def noop_with_retries[T](fn: Callable[..., T], **kwargs: Any) -> T:
    """RetryFn implementation that calls fn(**kwargs) exactly once."""
    return fn(**kwargs)


class EventCapture:
    """Records every emit_entities and emit_progress call in arrival order."""

    def __init__(self) -> None:
        self.events: list[tuple[Any, ...]] = []

    def emit_entities(
        self,
        unit: str,
        ids: list[str],
        metadata: DiscoveryProgressEvent,
    ) -> None:
        self.events.append(("entities", unit, list(ids), metadata))

    def emit_progress(self, event: DiscoveryProgressEvent) -> None:
        self.events.append(("progress", event))

    def progress_events(self) -> list[DiscoveryProgressEvent]:
        return [event[1] for event in self.events if event[0] == "progress"]

    def entity_events(self) -> list[tuple[str, list[str], DiscoveryProgressEvent]]:
        return [
            (event[1], event[2], event[3])
            for event in self.events
            if event[0] == "entities"
        ]


# _supports_on_chunk_complete is @lru_cache'd on the class type, so two distinct
# classes are required to exercise both the parallel-callback path and the
# sync-fallback path in the same test process.


class _StubGeoDcApiBase:
    """Shared state and simple query methods for both stub variants."""

    def __init__(
        self,
        *,
        place_types: list[str],
        geo_region_types: list[str],
        root_children: dict[str, list[str]],
        children_by_parent: dict[tuple[str, str], list[str]],
        entities_by_type: dict[str, list[str]] | None = None,
    ) -> None:
        self._place_types = list(place_types)
        self._geo_region_types = list(geo_region_types)
        self._root_children = dict(root_children)
        self._children_by_parent = dict(children_by_parent)
        self._entities_by_type = dict(entities_by_type or {})

    def get_place_types(self) -> list[str]:
        return list(self._place_types)

    def get_geo_region_types(self) -> list[str]:
        return list(self._geo_region_types)

    def get_places(self, *, place_type: str, parent_place: str) -> list[str]:
        if parent_place == ROOT_PLACE_DCID:
            return list(self._root_children.get(place_type, []))
        return list(self._children_by_parent.get((place_type, parent_place), []))

    def get_entities_by_type(self, *, raw_type: str) -> list[str]:
        return list(self._entities_by_type.get(raw_type, []))

    def _children_for(self, *, place_type: str, parent_id: str) -> list[str]:
        return list(self._children_by_parent.get((place_type, parent_id), []))


class StubGeoDcApiWithCallback(_StubGeoDcApiBase):
    """Deterministic in-memory GeoDcApi fake with on_chunk_complete support."""

    def get_places_by_parents(
        self,
        *,
        place_type: str,
        parent_places: list[str],
        chunk_size: int = 500,
        max_workers: int = 1,
        on_chunk_complete: Callable[[int, list[str], dict[str, list[str]]], None]
        | None = None,
    ) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for batch_index, parent_chunk in enumerate(
            chunk_list(parent_places, chunk_size)
        ):
            batch_result = {
                parent_id: children
                for parent_id in parent_chunk
                if (
                    children := self._children_for(
                        place_type=place_type, parent_id=parent_id
                    )
                )
            }
            result.update(batch_result)
            if on_chunk_complete is not None:
                on_chunk_complete(batch_index, list(parent_chunk), batch_result)
        return result


class StubGeoDcApiNoCallback(_StubGeoDcApiBase):
    """Deterministic in-memory GeoDcApi fake WITHOUT on_chunk_complete.

    Drives the sync-fallback path in _call_get_places_by_parents_with_progress
    because _supports_on_chunk_complete returns False for this class.
    """

    def get_places_by_parents(
        self,
        *,
        place_type: str,
        parent_places: list[str],
        chunk_size: int = 500,
        max_workers: int = 1,
    ) -> dict[str, list[str]]:
        return {
            parent_id: children
            for parent_id in parent_places
            if (
                children := self._children_for(
                    place_type=place_type, parent_id=parent_id
                )
            )
        }


# Fixture topology:
#   root → Country: country/USA; GeoRegion: region/Americas
#   country/USA → AdministrativeArea1: admin1/CA, admin1/NY; BoroughNYCType: borough/Manhattan
#   admin1/CA → AdministrativeArea2: admin2/SF, admin2/LA
#   admin1/NY → AdministrativeArea2: admin2/NYC
#   admin2/SF → City: city/SanFrancisco
#   admin2/NYC → City: city/NewYork


PLACE_TYPES_SPECIFIC = [
    "Country",
    "AdministrativeArea1",
    "AdministrativeArea2",
    "City",
    "BoroughNYCType",
]

PLACE_TYPES_GENERIC = [
    "Country",
    "AdministrativeArea",
    "City",
    "BoroughNYCType",
]

_GEO_REGION_TYPES = ["GeoRegion"]

_ROOT_CHILDREN = {
    PLACE_TYPE_COUNTRY: ["country/USA"],
    PLACE_TYPE_GEO_REGION: ["region/Americas"],
}

_CHILDREN_BY_PARENT: dict[tuple[str, str], list[str]] = {
    ("AdministrativeArea1", "country/USA"): ["admin1/CA", "admin1/NY"],
    ("AdministrativeArea", "country/USA"): ["admin1/CA", "admin1/NY"],
    ("AdministrativeArea2", "admin1/CA"): ["admin2/SF", "admin2/LA"],
    ("AdministrativeArea2", "admin1/NY"): ["admin2/NYC"],
    ("AdministrativeArea", "admin1/CA"): ["admin2/SF", "admin2/LA"],
    ("AdministrativeArea", "admin1/NY"): ["admin2/NYC"],
    ("AdministrativeArea", "admin2/SF"): [],
    ("AdministrativeArea", "admin2/LA"): [],
    ("AdministrativeArea", "admin2/NYC"): [],
    ("City", "admin2/SF"): ["city/SanFrancisco"],
    ("City", "admin2/NYC"): ["city/NewYork"],
    ("City", "country/USA"): ["city/DistrictOfColumbia"],
    ("City", "admin1/CA"): [],
    ("City", "admin1/NY"): [],
    ("BoroughNYCType", "country/USA"): ["borough/Manhattan"],
    ("GeoRegion", "region/Americas"): [],
}


def make_geo_fixture(
    *,
    use_generic_types: bool = False,
) -> StubGeoDcApiWithCallback:
    place_types = PLACE_TYPES_GENERIC if use_generic_types else PLACE_TYPES_SPECIFIC
    return StubGeoDcApiWithCallback(
        place_types=place_types,
        geo_region_types=_GEO_REGION_TYPES,
        root_children=_ROOT_CHILDREN,
        children_by_parent=_CHILDREN_BY_PARENT,
    )


def make_geo_fixture_no_callback(
    *,
    use_generic_types: bool = False,
) -> StubGeoDcApiNoCallback:
    place_types = PLACE_TYPES_GENERIC if use_generic_types else PLACE_TYPES_SPECIFIC
    return StubGeoDcApiNoCallback(
        place_types=place_types,
        geo_region_types=_GEO_REGION_TYPES,
        root_children=_ROOT_CHILDREN,
        children_by_parent=_CHILDREN_BY_PARENT,
    )
