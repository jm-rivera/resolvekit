"""Org domain mapping profile for shared Data Commons row builder."""

from __future__ import annotations

from collections import Counter
from typing import Any

from resolvekit.builder.inspection import DiscoveredEntityFacts
from resolvekit.builder.sources.datacommons import DataCommonsDomainProfile
from resolvekit.builder.sources.datacommons.constants import DATACOMMONS_SOURCE
from resolvekit.builder.sources.datacommons.org.discovery import (
    discover_entities,
    discover_entities_filtered,
)
from resolvekit.builder.sources.datacommons.org.mappings import (
    ORG_DEFAULT_RELATION_TYPE,
    ORG_DOMAIN,
    ORG_UNFILTERED_ENTITY_TYPES,
    to_org_entity_type,
)
from resolvekit.builder.sources.datacommons.specs import DataCommonsDomainSpec

_ORG_CODE_SYSTEM_MAPPING = {
    "wikidataid": "wikidata",
    "daccodestr": "dac",
    "daccodeint": "dac_numeric",
    "undatacode": "undata",
}


def map_org_entity_type(
    raw_entity_type: str,
    attrs: dict[str, Any] | None = None,
) -> str:
    _ = attrs
    return to_org_entity_type(raw_entity_type)


def to_org_name_kind(alias_type: str) -> str:
    """Map source alias types to canonical org name kinds."""
    normalized = alias_type.casefold().strip()
    if normalized in {"canonical", "primary"}:
        return "canonical"
    if normalized in {"short", "short_name"}:
        return "short"
    if normalized in {"legal", "legal_name"}:
        return "legal"
    if normalized in {"abbr", "abbreviation", "acronym"}:
        return "acronym"
    return "alias"


def normalize_org_code_system(raw_system: str) -> str:
    """Normalize org code-system names into canonical short keys."""
    lowered = raw_system.casefold().strip()
    return _ORG_CODE_SYSTEM_MAPPING.get(lowered, lowered)


ORG_DOMAIN_PROFILE = DataCommonsDomainProfile(
    domain=ORG_DOMAIN,
    entity_type_mapper=map_org_entity_type,
    alias_kind_mapper=to_org_name_kind,
    code_system_mapper=normalize_org_code_system,
    default_relation_type=ORG_DEFAULT_RELATION_TYPE,
    source_label=DATACOMMONS_SOURCE,
)


def collect_org_discovered_entity_facts(
    *,
    dc_api: Any,
    profile: DataCommonsDomainProfile,
    entity_ids: list[str],
) -> dict[str, DiscoveredEntityFacts]:
    raw_types = dc_api.get_entity_types(entity_ids)
    facts: dict[str, DiscoveredEntityFacts] = {}
    for entity_id in entity_ids:
        raw_type = raw_types.get(entity_id)
        attrs = (
            {}
            if raw_type is None
            else {"source_class_family": dc_api.get_source_class_family(raw_type)}
        )
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


def build_org_inspection_warnings(
    *,
    dc_api: Any,
    profile: DataCommonsDomainProfile,
    entity_ids: list[str],
    facts_by_entity: dict[str, DiscoveredEntityFacts],
    requested_entity_types: list[str],
    include_relation_targets: bool,
) -> list[str]:
    _ = (profile, requested_entity_types, include_relation_targets)
    warnings = [
        "Included org class roots: "
        + ", ".join(dc_api.get_supported_root_families())
        + "."
    ]
    warnings.append(
        "Unfiltered org discovery canonical types: "
        + ", ".join(ORG_UNFILTERED_ENTITY_TYPES)
        + "."
    )
    raw_counts = Counter(
        facts.raw_entity_type
        for facts in facts_by_entity.values()
        if facts.raw_entity_type is not None
    )
    if raw_counts:
        warnings.append(
            "Populated raw org classes: "
            + ", ".join(
                f"{raw_type} ({count})"
                for raw_type, count in sorted(raw_counts.items())
            )
            + "."
        )

    sample_ids = sorted(entity_ids)[:10]
    if sample_ids:
        sampled_properties = sorted(
            {
                label
                for labels in dc_api.get_property_labels(sample_ids).values()
                for label in labels
            }
        )[:15]
        if sampled_properties:
            warnings.append(
                "Sampled source properties: " + ", ".join(sampled_properties) + "."
            )
    return warnings


ORG_DOMAIN_SPEC = DataCommonsDomainSpec(
    domain=ORG_DOMAIN,
    profile=ORG_DOMAIN_PROFILE,
    discover_entities=discover_entities,
    discover_entities_filtered=discover_entities_filtered,
    collect_discovered_entity_facts=collect_org_discovered_entity_facts,
    inspection_warning_builder=build_org_inspection_warnings,
)
