"""Geo-region traversal: scan Earth's region children (with UN M.49 two-step)."""

from __future__ import annotations

from resolvekit.builder.sources.datacommons.geo._streaming import emit_root_entities
from resolvekit.builder.sources.datacommons.geo._type_mappings import (
    discovery_unit_for_raw_type,
)
from resolvekit.builder.sources.datacommons.geo.dc_api import GeoDcApi
from resolvekit.builder.sources.datacommons.geo.mappings import (
    DISCOVERY_MAX_WORKERS,
    DISCOVERY_PARENT_BATCH_SIZE,
    PLACE_TYPE_GEO_REGION,
    ROOT_PLACE_DCID,
    UN_REGION_DCID,
)
from resolvekit.builder.sources.protocol import (
    DiscoveryBatchFn,
    DiscoveryProgressFn,
    RetryFn,
)


def discover_requested_geo_regions_incremental(
    *,
    dc_api: GeoDcApi,
    with_retries: RetryFn,
    requested_raw_types: set[str],
    geo_region_types: set[str],
    emit_entities: DiscoveryBatchFn,
    emit_progress: DiscoveryProgressFn,
) -> None:
    for raw_type in sorted(requested_raw_types):
        if raw_type not in geo_region_types:
            continue
        entity_ids = sorted(
            discover_geo_region_entities(
                dc_api=dc_api,
                with_retries=with_retries,
                raw_type=raw_type,
            )
        )
        if raw_type == PLACE_TYPE_GEO_REGION:
            entity_ids = sorted({*entity_ids, UN_REGION_DCID})
        unit = discovery_unit_for_raw_type(raw_type)
        if unit is None:
            continue
        emit_root_entities(
            unit=unit,
            entity_ids=entity_ids,
            emit_entities=emit_entities,
            emit_progress=emit_progress,
            raw_type=raw_type,
        )


def discover_geo_region_entities(
    *,
    dc_api: GeoDcApi,
    with_retries: RetryFn,
    raw_type: str,
) -> set[str]:
    discovered: set[str] = set(
        with_retries(
            dc_api.get_places,
            place_type=raw_type,
            parent_place=ROOT_PLACE_DCID,
        )
    )
    if discovered:
        # UN M.49 subregions (e.g. "Western Europe") parent under Europe, not
        # directly under Earth — the first call doesn't reach them.
        if raw_type == PLACE_TYPE_GEO_REGION:
            subregion_map = with_retries(
                dc_api.get_places_by_parents,
                place_type=PLACE_TYPE_GEO_REGION,
                parent_places=list(discovered),
                chunk_size=DISCOVERY_PARENT_BATCH_SIZE,
                max_workers=DISCOVERY_MAX_WORKERS,
            )
            for subregion_ids in subregion_map.values():
                discovered.update(subregion_ids)
        return discovered

    # Fallback for non-standard type names not parented under Earth.
    discovered.update(
        with_retries(
            dc_api.get_entities_by_type,
            raw_type=raw_type,
        )
    )
    return discovered
