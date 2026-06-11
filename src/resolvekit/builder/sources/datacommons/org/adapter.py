"""Bounded Data Commons org source adapter."""

from __future__ import annotations

from typing import Any

from resolvekit.builder.sources.datacommons.adapter import (
    DataCommonsSourceAdapter,
    DomainAdapterConfig,
)
from resolvekit.builder.sources.datacommons.client import DataCommons
from resolvekit.builder.sources.datacommons.org.dc_api import OrgDcApi
from resolvekit.builder.sources.datacommons.org.fetch import fetch_raw_chunk
from resolvekit.builder.sources.datacommons.org.mappings import to_org_entity_type
from resolvekit.builder.sources.datacommons.org.profile import ORG_DOMAIN_SPEC
from resolvekit.packs.org.normalizer import OrgNormalizer


def filter_org_entities(
    *,
    runtime: DataCommons,
    dc_api: OrgDcApi,
    entity_ids: list[str],
    include_entity_types: list[str],
) -> list[str]:
    """Filter discovered org entity IDs by canonical entity type."""
    allowlist = {value.strip() for value in include_entity_types if value.strip()}
    if not allowlist or not entity_ids:
        return list(entity_ids)

    try:
        raw_types = runtime.with_retries(
            dc_api.get_entity_types,
            entity_ids=entity_ids,
        )
    except Exception:
        return list(entity_ids)

    return [
        entity_id
        for entity_id in entity_ids
        if (raw_type := raw_types.get(entity_id)) is not None
        and to_org_entity_type(raw_type) in allowlist
    ]


ORG_ADAPTER_CONFIG = DomainAdapterConfig(
    domain_spec=ORG_DOMAIN_SPEC,
    dc_api_factory=OrgDcApi,
    fetch_raw_chunk_fn=fetch_raw_chunk,
    filter_entities_fn=filter_org_entities,
    code_normalizer=OrgNormalizer(),
)


class DataCommonsOrgSourceAdapter(DataCommonsSourceAdapter):
    """Bounded org extraction adapter backed by Data Commons."""

    def __init__(self, **kwargs: Any):
        super().__init__(ORG_ADAPTER_CONFIG, **kwargs)
