"""Low-level Data Commons API fetch helpers for the geo adapter."""

from __future__ import annotations

from collections.abc import Callable
from functools import cached_property
from typing import Any, override

from resolvekit.builder.sources.datacommons.base_dc_api import BaseDcApi
from resolvekit.builder.sources.datacommons.constants import (
    DEFAULT_CHUNK_SIZE,
    NODE_VALUE_ATTR,
    SUBCLASS_OF_PROPERTY,
    TYPE_OF_PROPERTY,
)
from resolvekit.builder.sources.datacommons.geo.mappings import (
    ALIAS_PROPERTIES,
    ATTR_PROPERTIES,
    CENTROID_LAT_KEY,
    CENTROID_LON_KEY,
    CODES_CHUNK_SIZE,
    CODES_PROPERTIES,
    ENTITY_TYPE_CHUNK_SIZE,
    LAT_LONG_PROPERTIES,
    PLACE_TYPE_ADMINISTRATIVE_AREA,
    PLACE_TYPE_CITY,
    PLACE_TYPE_COUNTRY,
    PLACE_TYPE_GEO_REGION,
    PLACE_TYPE_PARENT_NODES,
    admin_level_from_raw_type,
)
from resolvekit.builder.sources.datacommons.node import (
    node_string,
    select_preferred_type,
    walk_type_families,
)


class GeoDcApi(BaseDcApi):
    """Data Commons geo-domain fetch API with normalized payload helpers."""

    _alias_properties = ALIAS_PROPERTIES
    _code_properties = CODES_PROPERTIES
    _attr_properties = ATTR_PROPERTIES
    _codes_chunk_size = CODES_CHUNK_SIZE

    def get_place_types(self) -> list[str]:
        props = self._get_property_values(
            PLACE_TYPE_PARENT_NODES,
            [SUBCLASS_OF_PROPERTY],
            out=False,
        )
        nodes = []
        for parent in PLACE_TYPE_PARENT_NODES:
            nodes.extend(props.get(parent, {}).get(SUBCLASS_OF_PROPERTY, []))
        types = [node_string(n) for n in nodes]
        return [place_type for place_type in types if place_type]

    def get_places(self, *, place_type: str, parent_place: str) -> list[str]:
        return self._runtime.fetch_place_children(
            place_type=place_type,
            parent_place=parent_place,
        )

    def get_places_by_parents(
        self,
        *,
        place_type: str,
        parent_places: list[str],
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        max_workers: int = 1,
        on_chunk_complete: Callable[[int, list[str], dict[str, list[str]]], None]
        | None = None,
    ) -> dict[str, list[str]]:
        return self._runtime.fetch_place_children_for_parents(
            place_type=place_type,
            parent_places=parent_places,
            chunk_size=chunk_size,
            max_workers=max_workers,
            on_chunk_complete=on_chunk_complete,
        )

    @override
    def get_entity_types(self, entity_ids: list[str]) -> dict[str, str]:
        raw = self._get_property_values(
            entity_ids,
            [TYPE_OF_PROPERTY],
            chunk_size=ENTITY_TYPE_CHUNK_SIZE,
        )
        types: dict[str, str] = {}
        for entity_id, props in raw.items():
            raw_type = select_preferred_type(
                props.get(TYPE_OF_PROPERTY, []),
                rank_by_type=self._type_ranks,
            )
            if raw_type is not None:
                types[entity_id] = raw_type
        return types

    def get_lat_long(self, entity_ids: list[str]) -> dict[str, dict[str, str]]:
        raw = self._get_property_values(entity_ids, LAT_LONG_PROPERTIES)
        lat_prop, lon_prop = LAT_LONG_PROPERTIES
        out: dict[str, dict[str, str]] = {}
        for entity_id, props in raw.items():
            coords: dict[str, str] = {}
            lat = self._most_precise_value(props.get(lat_prop, []))
            lon = self._most_precise_value(props.get(lon_prop, []))
            if lat is not None:
                coords[CENTROID_LAT_KEY] = lat
            if lon is not None:
                coords[CENTROID_LON_KEY] = lon
            if coords:
                out[entity_id] = coords
        return out

    @staticmethod
    def _most_precise_value(values: list[Any]) -> str | None:
        rendered = [
            str(value)
            for node in values
            if (value := getattr(node, NODE_VALUE_ATTR, None)) is not None
        ]
        if not rendered:
            return None
        return max(rendered, key=GeoDcApi._decimal_precision)

    @staticmethod
    def _decimal_precision(value: str) -> int:
        if "." not in value:
            return 0
        return len(value.rsplit(".", maxsplit=1)[-1])

    def get_parents(self, entity_ids: list[str]) -> dict[str, list[str]]:
        return self._runtime.fetch_place_parents(entity_ids)

    def get_geo_region_types(self) -> list[str]:
        return sorted(
            self._geo_region_type_depths,
            key=lambda raw_type: (self._geo_region_type_depths[raw_type], raw_type),
        )

    def get_source_class_family(self, raw_type: str) -> str:
        normalized = raw_type.strip()
        if normalized in self._geo_region_families:
            return PLACE_TYPE_GEO_REGION
        if (
            normalized == PLACE_TYPE_ADMINISTRATIVE_AREA
            or admin_level_from_raw_type(normalized) is not None
            or normalized in self._admin_type_families
        ):
            return PLACE_TYPE_ADMINISTRATIVE_AREA
        if normalized == PLACE_TYPE_COUNTRY:
            return PLACE_TYPE_COUNTRY
        if normalized == PLACE_TYPE_CITY:
            return PLACE_TYPE_CITY
        return normalized

    @cached_property
    def _geo_region_walk(self) -> tuple[dict[str, int], dict[str, str]]:
        return walk_type_families(
            roots=[PLACE_TYPE_GEO_REGION],
            fetch_children=self._get_type_subclasses_cached,
        )

    @cached_property
    def _admin_walk(self) -> tuple[dict[str, int], dict[str, str]]:
        return walk_type_families(
            roots=[PLACE_TYPE_ADMINISTRATIVE_AREA],
            fetch_children=self._get_type_subclasses_cached,
        )

    @property
    def _geo_region_type_depths(self) -> dict[str, int]:
        return self._geo_region_walk[0]

    @property
    def _geo_region_families(self) -> dict[str, str]:
        return self._geo_region_walk[1]

    @property
    def _admin_type_depths(self) -> dict[str, int]:
        return self._admin_walk[0]

    @property
    def _admin_type_families(self) -> dict[str, str]:
        return self._admin_walk[1]

    @cached_property
    def _type_ranks(self) -> dict[str, int]:
        ranks: dict[str, int] = {
            PLACE_TYPE_COUNTRY: 100,
            PLACE_TYPE_CITY: 100,
        }
        for raw_type, depth in self._admin_type_depths.items():
            ranks[raw_type] = max(ranks.get(raw_type, 0), 200 + depth)
        for raw_type, depth in self._geo_region_type_depths.items():
            ranks[raw_type] = max(ranks.get(raw_type, 0), 300 + depth)
        return ranks

    def _get_type_subclasses_cached(self, raw_type: str) -> list[str]:
        return self.get_type_subclasses(raw_type=raw_type)

    def get_admin_levels(
        self,
        entity_ids: list[str],
        *,
        entity_types: dict[str, str] | None = None,
        parents_by_entity: dict[str, list[str]] | None = None,
    ) -> dict[str, int]:
        """Infer administrative depth from parent containment chains."""
        if not entity_ids:
            return {}

        type_cache = dict(entity_types or {})
        parent_cache = {
            entity_id: list(parent_ids)
            for entity_id, parent_ids in (parents_by_entity or {}).items()
        }
        pending = [
            entity_id
            for entity_id in entity_ids
            if type_cache.get(entity_id) == PLACE_TYPE_ADMINISTRATIVE_AREA
        ]
        visited: set[str] = set()

        while pending:
            current = [entity_id for entity_id in pending if entity_id not in visited]
            if not current:
                break
            visited.update(current)

            missing_parents = [
                entity_id for entity_id in current if entity_id not in parent_cache
            ]
            if missing_parents:
                parent_cache.update(self.get_parents(missing_parents))

            unresolved_parent_ids = [
                parent_id
                for entity_id in current
                for parent_id in parent_cache.get(entity_id, [])
                if parent_id not in type_cache
            ]
            unseen_parent_ids = list(dict.fromkeys(unresolved_parent_ids))
            if unseen_parent_ids:
                type_cache.update(self.get_entity_types(unseen_parent_ids))

            pending = [
                parent_id
                for parent_id in unseen_parent_ids
                if type_cache.get(parent_id) == PLACE_TYPE_ADMINISTRATIVE_AREA
            ]

        memo: dict[str, int] = {}
        active: set[str] = set()

        def compute_level(entity_id: str) -> int | None:
            if entity_id in memo:
                return memo[entity_id]
            if entity_id in active:
                return 1
            raw_type = type_cache.get(entity_id)
            if raw_type is None:
                return None
            if (direct_level := admin_level_from_raw_type(raw_type)) is not None:
                memo[entity_id] = direct_level
                return direct_level
            if raw_type != PLACE_TYPE_ADMINISTRATIVE_AREA:
                return None

            active.add(entity_id)
            parent_ids = parent_cache.get(entity_id, [])
            admin_parent_levels = [
                level
                for parent_id in parent_ids
                if (level := compute_level(parent_id)) is not None
            ]
            level = max(admin_parent_levels) + 1 if admin_parent_levels else 1
            active.remove(entity_id)
            memo[entity_id] = level
            return level

        return {
            entity_id: level
            for entity_id in entity_ids
            if (level := compute_level(entity_id)) is not None
        }
