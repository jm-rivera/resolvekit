"""Data Commons geo source adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any, override

from resolvekit.builder.sources.datacommons.adapter import (
    DataCommonsSourceAdapter,
    DomainAdapterConfig,
)
from resolvekit.builder.sources.datacommons.client import DataCommons
from resolvekit.builder.sources.datacommons.geo.dc_api import GeoDcApi
from resolvekit.builder.sources.datacommons.geo.discovery import (
    discover_entities_filtered_incremental,
)
from resolvekit.builder.sources.datacommons.geo.fetch import fetch_raw_chunk
from resolvekit.builder.sources.datacommons.geo.mappings import (
    DISCOVERY_PARENT_BATCH_SIZE,
    to_geo_entity_type,
)
from resolvekit.builder.sources.datacommons.geo.profile import GEO_DOMAIN_SPEC
from resolvekit.builder.sources.datacommons.models import RawChunk
from resolvekit.builder.sources.protocol import DiscoveryBatchFn, DiscoveryProgressFn
from resolvekit.packs.geo.normalizer import GeoNormalizer


def filter_geo_entities(
    *,
    runtime: DataCommons,
    dc_api: GeoDcApi,
    entity_ids: list[str],
    include_entity_types: list[str],
) -> list[str]:
    """Filter discovered geo entity IDs by canonical entity type."""
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

    admin_levels: dict[str, int] = {}
    if any(entity_type.startswith("geo.admin") for entity_type in allowlist):
        try:
            admin_levels = dc_api.get_admin_levels(
                entity_ids,
                entity_types=raw_types,
            )
        except Exception:
            admin_levels = {}

    filtered: list[str] = []
    for entity_id in entity_ids:
        raw_type = raw_types.get(entity_id)
        if raw_type is None:
            continue
        attrs = (
            {"admin_level": admin_levels[entity_id]}
            if entity_id in admin_levels
            else {}
        )
        if to_geo_entity_type(raw_type, attrs) in allowlist:
            filtered.append(entity_id)
    return filtered


GEO_ADAPTER_CONFIG = DomainAdapterConfig(
    domain_spec=GEO_DOMAIN_SPEC,
    dc_api_factory=GeoDcApi,
    fetch_raw_chunk_fn=fetch_raw_chunk,
    filter_entities_fn=filter_geo_entities,
    code_normalizer=GeoNormalizer(),
)


class DataCommonsGeoSourceAdapter(DataCommonsSourceAdapter):
    """Geo extraction adapter backed by Data Commons Python client."""

    def __init__(
        self,
        *,
        discovery_parent_batch_size: int = DISCOVERY_PARENT_BATCH_SIZE,
        wikidata_cache_dir: Path | None = None,
        dc_cache_dir: Path | None = None,
        **kwargs: Any,
    ):
        super().__init__(GEO_ADAPTER_CONFIG, cache_dir=dc_cache_dir, **kwargs)
        self._discovery_parent_batch_size = discovery_parent_batch_size
        self._wikidata_cache_dir = wikidata_cache_dir

    @override
    def fetch_raw_chunk(self, domain: str, entity_ids: list[str]) -> RawChunk:
        self._ensure_domain(domain)
        return fetch_raw_chunk(
            entity_ids=entity_ids,
            dc_api=self._dc_api,
            languages=self._languages,
            wikidata_cache_dir=self._wikidata_cache_dir,
        )

    def discover_entities_filtered_incremental(
        self,
        domain: str,
        *,
        include_entity_types: list[str],
        include_relation_targets: bool,
        emit_entities: DiscoveryBatchFn,
        emit_progress: DiscoveryProgressFn,
        seed_frontier: dict[str, list[str]] | None = None,
    ) -> None:
        self._ensure_domain(domain)
        discover_entities_filtered_incremental(
            dc_api=self._dc_api,
            with_retries=self._runtime.with_retries,
            include_entity_types=include_entity_types,
            include_relation_targets=include_relation_targets,
            emit_entities=emit_entities,
            emit_progress=emit_progress,
            discovery_parent_batch_size=self._discovery_parent_batch_size,
            seed_frontier=seed_frontier,
        )
