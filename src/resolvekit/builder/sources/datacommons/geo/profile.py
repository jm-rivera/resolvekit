"""Geo domain mapping profile for shared Data Commons row builder."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from resolvekit.builder.inspection import DiscoveredEntityFacts
from resolvekit.builder.sources.datacommons import DataCommonsDomainProfile
from resolvekit.builder.sources.datacommons.constants import DATACOMMONS_SOURCE
from resolvekit.builder.sources.datacommons.geo.discovery import (
    discover_entities,
    discover_entities_filtered,
)
from resolvekit.builder.sources.datacommons.geo.mappings import (
    GEO_DEFAULT_RELATION_TYPE,
    GEO_DOMAIN,
    normalize_code_system,
    to_geo_entity_type,
    to_name_kind,
)
from resolvekit.builder.sources.datacommons.specs import DataCommonsDomainSpec

GEO_DOMAIN_PROFILE = DataCommonsDomainProfile(
    domain=GEO_DOMAIN,
    entity_type_mapper=to_geo_entity_type,
    alias_kind_mapper=to_name_kind,
    code_system_mapper=normalize_code_system,
    default_relation_type=GEO_DEFAULT_RELATION_TYPE,
    source_label=DATACOMMONS_SOURCE,
)


def collect_geo_discovered_entity_facts(
    *,
    dc_api: Any,
    profile: DataCommonsDomainProfile,
    entity_ids: list[str],
) -> dict[str, DiscoveredEntityFacts]:
    with ThreadPoolExecutor(max_workers=2) as executor:
        types_f = executor.submit(dc_api.get_entity_types, entity_ids)
        parents_f = executor.submit(dc_api.get_parents, entity_ids)
        raw_types = types_f.result()
        parents = parents_f.result()
    admin_levels = dc_api.get_admin_levels(
        entity_ids,
        entity_types=raw_types,
        parents_by_entity=parents,
    )
    facts: dict[str, DiscoveredEntityFacts] = {}
    for entity_id in entity_ids:
        raw_type = raw_types.get(entity_id)
        attrs: dict[str, Any] = {}
        if entity_id in admin_levels:
            attrs["admin_level"] = admin_levels[entity_id]
        if raw_type is not None:
            attrs["source_class_family"] = dc_api.get_source_class_family(raw_type)
        facts[entity_id] = DiscoveredEntityFacts(
            entity_id=entity_id,
            raw_entity_type=raw_type,
            canonical_entity_type=(
                None
                if raw_type is None
                else profile.entity_type_mapper(raw_type, attrs)
            ),
            attrs=attrs,
        )
    return facts


GEO_DOMAIN_SPEC = DataCommonsDomainSpec(
    domain=GEO_DOMAIN,
    profile=GEO_DOMAIN_PROFILE,
    discover_entities=discover_entities,
    discover_entities_filtered=discover_entities_filtered,
    collect_discovered_entity_facts=collect_geo_discovered_entity_facts,
)
