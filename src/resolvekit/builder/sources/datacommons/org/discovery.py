"""Entity discovery for the curated Data Commons org source."""

from __future__ import annotations

from resolvekit.builder.sources.datacommons.org.dc_api import OrgDcApi
from resolvekit.builder.sources.datacommons.org.mappings import (
    ORG_UNFILTERED_ENTITY_TYPES,
    to_org_entity_type,
)
from resolvekit.builder.sources.protocol import RetryFn


def discover_entities(
    *,
    dc_api: OrgDcApi,
    with_retries: RetryFn,
) -> list[str]:
    """Discover org entity IDs from populated live schema families."""
    supported_raw_types = with_retries(dc_api.get_supported_raw_types)
    discovered: set[str] = set()
    for raw_type in _org_unfiltered_raw_types(supported_raw_types):
        discovered.update(
            with_retries(
                dc_api.get_entities_by_type,
                raw_type=raw_type,
            )
        )
    return sorted(discovered)


def discover_entities_filtered(
    *,
    dc_api: OrgDcApi,
    with_retries: RetryFn,
    include_entity_types: list[str],
    include_relation_targets: bool,
) -> list[str]:
    """Discover only the requested canonical org entity types."""
    requested_types = {value.strip() for value in include_entity_types if value.strip()}
    if not requested_types:
        return discover_entities(dc_api=dc_api, with_retries=with_retries)

    supported_raw_types = with_retries(dc_api.get_supported_raw_types)
    matching_raw_types = [
        raw_type
        for raw_type in supported_raw_types
        if to_org_entity_type(raw_type) in requested_types
    ]
    if not matching_raw_types:
        return []

    discovered: set[str] = set()
    for raw_type in matching_raw_types:
        discovered.update(
            with_retries(
                dc_api.get_entities_by_type,
                raw_type=raw_type,
            )
        )
    if include_relation_targets and discovered:
        relations = with_retries(
            dc_api.get_relations,
            entity_ids=sorted(discovered),
        )
        discovered.update(
            relation["target_id"]
            for entity_relations in relations.values()
            for relation in entity_relations
            if relation.get("target_id")
        )
    return sorted(discovered)


def _org_unfiltered_raw_types(supported_raw_types: list[str]) -> list[str]:
    return [
        raw_type
        for raw_type in supported_raw_types
        if to_org_entity_type(raw_type) in ORG_UNFILTERED_ENTITY_TYPES
    ]
