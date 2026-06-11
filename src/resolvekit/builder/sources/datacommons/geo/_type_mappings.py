"""Type-name parsing and unit-lookup helpers for geo discovery."""

from __future__ import annotations

import re

from resolvekit.builder.sources.datacommons.geo.mappings import (
    PLACE_TYPE_ADMINISTRATIVE_AREA,
    PLACE_TYPE_CITY,
    PLACE_TYPE_COUNTRY,
    admin_level_from_raw_type,
    to_geo_entity_type,
)

UNIT_BY_CANONICAL_TYPE = {
    "geo.country": "countries",
    "geo.region": "regions",
    "geo.continental_union": "continental_unions",
    "geo.continent": "continents",
    "geo.city": "cities",
    **{f"geo.admin{level}": f"admin{level}" for level in range(1, 7)},
}


def canonical_type_mapping(
    child_place_types: list[str],
    geo_region_types: set[str],
) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {
        to_geo_entity_type(PLACE_TYPE_COUNTRY): {PLACE_TYPE_COUNTRY},
        "geo.city": {PLACE_TYPE_CITY},
    }
    typed_admins = admin_place_types(child_place_types)
    if typed_admins:
        for level, place_type in typed_admins:
            mapping[f"geo.admin{level}"] = {place_type}
    else:
        for level in range(1, 7):
            mapping[f"geo.admin{level}"] = {PLACE_TYPE_ADMINISTRATIVE_AREA}
    for place_type in sorted(set(child_place_types) | geo_region_types):
        canonical = to_geo_entity_type(place_type)
        mapping.setdefault(canonical, set()).add(place_type)
    return mapping


def admin_place_types(child_place_types: list[str]) -> list[tuple[int, str]]:
    admin_types: list[tuple[int, str]] = []
    for place_type in child_place_types:
        level = admin_level_from_raw_type(place_type)
        if level is not None:
            admin_types.append((level, place_type))
    return sorted(admin_types)


def discovery_unit_for_raw_type(raw_type: str) -> str | None:
    return UNIT_BY_CANONICAL_TYPE.get(to_geo_entity_type(raw_type))


def requested_admin_levels(requested_types: set[str]) -> set[int]:
    levels: set[int] = set()
    for entity_type in requested_types:
        match = re.fullmatch(r"geo\.admin(\d+)", entity_type)
        if match is not None:
            levels.add(int(match.group(1)))
    return levels
