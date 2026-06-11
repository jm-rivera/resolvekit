"""Entity discovery for Data Commons geo source."""

from __future__ import annotations

from collections.abc import Callable

from resolvekit.builder.sources.datacommons.geo._admin_walk import (
    discover_requested_admin_entities_incremental,
)
from resolvekit.builder.sources.datacommons.geo._geo_regions import (
    discover_geo_region_entities,
    discover_requested_geo_regions_incremental,
)
from resolvekit.builder.sources.datacommons.geo._streaming import (
    StreamProgressContext,
    emit_root_entities,
    stream_parent_children,
)
from resolvekit.builder.sources.datacommons.geo._type_mappings import (
    admin_place_types,
    canonical_type_mapping,
    discovery_unit_for_raw_type,
    requested_admin_levels,
)
from resolvekit.builder.sources.datacommons.geo.dc_api import GeoDcApi
from resolvekit.builder.sources.datacommons.geo.mappings import (
    DISCOVERY_MAX_WORKERS,
    DISCOVERY_PARENT_BATCH_SIZE,
    PLACE_TYPE_ADMINISTRATIVE_AREA,
    PLACE_TYPE_CITY,
    PLACE_TYPE_COUNTRY,
    PLACE_TYPE_GEO_REGION,
    ROOT_PLACE_DCID,
    SPECIAL_PLACE_TYPES,
    UN_REGION_DCID,
    admin_level_from_raw_type,
)
from resolvekit.builder.sources.discovery_events import (
    DiscoveryProgressEvent,
    DomainComplete,
    DomainStart,
    UnitBatch,
)
from resolvekit.builder.sources.protocol import (
    DiscoveryBatchFn,
    DiscoveryProgressFn,
    RetryFn,
)


def discover_entities(
    *,
    dc_api: GeoDcApi,
    with_retries: RetryFn,
    discovery_parent_batch_size: int = DISCOVERY_PARENT_BATCH_SIZE,
) -> list[str]:
    """Discover geo entity IDs for extraction."""
    return sorted(
        _discover_all_geo_entities(
            dc_api=dc_api,
            with_retries=with_retries,
            discovery_parent_batch_size=discovery_parent_batch_size,
        )
    )


def discover_entities_filtered(
    *,
    dc_api: GeoDcApi,
    with_retries: RetryFn,
    include_entity_types: list[str],
    include_relation_targets: bool,
    discovery_parent_batch_size: int = DISCOVERY_PARENT_BATCH_SIZE,
) -> list[str]:
    """Discover only selected geo entity types and optional parent targets."""
    discovered: set[str] = set()

    def _emit_entities(
        _unit: str,
        entity_ids: list[str],
        _metadata: DiscoveryProgressEvent,
    ) -> None:
        discovered.update(entity_ids)

    discover_entities_filtered_incremental(
        dc_api=dc_api,
        with_retries=with_retries,
        include_entity_types=include_entity_types,
        include_relation_targets=include_relation_targets,
        emit_entities=_emit_entities,
        emit_progress=lambda _payload: None,
        discovery_parent_batch_size=discovery_parent_batch_size,
    )

    return sorted(discovered)


def discover_entities_filtered_incremental(
    *,
    dc_api: GeoDcApi,
    with_retries: RetryFn,
    include_entity_types: list[str],
    include_relation_targets: bool,
    emit_entities: DiscoveryBatchFn,
    emit_progress: DiscoveryProgressFn,
    discovery_parent_batch_size: int = DISCOVERY_PARENT_BATCH_SIZE,
    seed_frontier: dict[str, list[str]] | None = None,
) -> None:
    """Discover selected geo entity types and emit ordered batches + progress."""
    requested_types = {value.strip() for value in include_entity_types if value.strip()}
    if not requested_types:
        _emit_full_universe(
            dc_api=dc_api,
            with_retries=with_retries,
            discovery_parent_batch_size=discovery_parent_batch_size,
            emit_entities=emit_entities,
            emit_progress=emit_progress,
            requested_entity_types=[],
        )
        return

    place_types = with_retries(dc_api.get_place_types)
    geo_region_types = set(with_retries(dc_api.get_geo_region_types))
    child_place_types = [
        place_type
        for place_type in place_types
        if place_type not in SPECIAL_PLACE_TYPES
    ]
    typed_admins = admin_place_types(child_place_types)
    canonical_to_raw = canonical_type_mapping(child_place_types, geo_region_types)

    requested_raw_types = {
        raw_type
        for entity_type in requested_types
        for raw_type in canonical_to_raw.get(entity_type, set())
    }
    if not requested_raw_types:
        _emit_full_universe(
            dc_api=dc_api,
            with_retries=with_retries,
            discovery_parent_batch_size=discovery_parent_batch_size,
            emit_entities=emit_entities,
            emit_progress=emit_progress,
            requested_entity_types=sorted(requested_types),
        )
        return

    countries: list[str] | None = None
    root_regions: list[str] | None = None
    admin_levels = requested_admin_levels(requested_types)

    def ensure_countries() -> list[str]:
        nonlocal countries
        if countries is None:
            if seed_frontier and "countries" in seed_frontier:
                countries = list(seed_frontier["countries"])
            else:
                countries = with_retries(
                    dc_api.get_places,
                    place_type=PLACE_TYPE_COUNTRY,
                    parent_place=ROOT_PLACE_DCID,
                )
        return countries

    def ensure_root_regions() -> list[str]:
        nonlocal root_regions
        if root_regions is None:
            root_regions = with_retries(
                dc_api.get_places,
                place_type=PLACE_TYPE_GEO_REGION,
                parent_place=ROOT_PLACE_DCID,
            )
            root_regions = [*root_regions, UN_REGION_DCID]
        return root_regions

    emit_progress(
        DomainStart(
            unit="geo",
            requested_entity_types=sorted(requested_types),
            include_relation_targets=include_relation_targets,
        )
    )

    if PLACE_TYPE_COUNTRY in requested_raw_types:
        emit_root_entities(
            unit="countries",
            entity_ids=ensure_countries(),
            emit_entities=emit_entities,
            emit_progress=emit_progress,
            raw_type=PLACE_TYPE_COUNTRY,
        )
    discover_requested_geo_regions_incremental(
        dc_api=dc_api,
        with_retries=with_retries,
        requested_raw_types=requested_raw_types,
        geo_region_types=geo_region_types,
        emit_entities=emit_entities,
        emit_progress=emit_progress,
    )
    discover_requested_admin_entities_incremental(
        dc_api=dc_api,
        with_retries=with_retries,
        requested_raw_types=requested_raw_types,
        requested_admin_levels=admin_levels,
        admin_place_types=typed_admins,
        countries=ensure_countries,
        emit_entities=emit_entities,
        emit_progress=emit_progress,
        discovery_parent_batch_size=discovery_parent_batch_size,
        seed_frontier=seed_frontier,
    )
    _discover_requested_country_scoped_children_incremental(
        dc_api=dc_api,
        with_retries=with_retries,
        requested_raw_types=requested_raw_types,
        child_place_types=child_place_types,
        geo_region_types=geo_region_types,
        countries=ensure_countries,
        emit_entities=emit_entities,
        emit_progress=emit_progress,
        discovery_parent_batch_size=discovery_parent_batch_size,
    )

    if include_relation_targets:
        # Bound parent closure for relation-target recipes to countries + root
        # regions; broader scans add cost without surfacing useful targets.
        emit_root_entities(
            unit="countries",
            entity_ids=ensure_countries(),
            emit_entities=emit_entities,
            emit_progress=emit_progress,
            raw_type=PLACE_TYPE_COUNTRY,
        )
        emit_root_entities(
            unit="regions",
            entity_ids=ensure_root_regions(),
            emit_entities=emit_entities,
            emit_progress=emit_progress,
            raw_type=PLACE_TYPE_GEO_REGION,
        )

    emit_progress(
        DomainComplete(
            unit="geo",
            requested_entity_types=sorted(requested_types),
        )
    )


def _emit_full_universe(
    *,
    dc_api: GeoDcApi,
    with_retries: RetryFn,
    discovery_parent_batch_size: int,
    emit_entities: DiscoveryBatchFn,
    emit_progress: DiscoveryProgressFn,
    requested_entity_types: list[str],
) -> None:
    """Emit the full unfiltered universe as one UnitBatch + DomainComplete pair.

    Used by `discover_entities_filtered_incremental` when the requested-types
    filter is empty or maps to nothing — the contract is: behave like
    `discover_entities` but through the streaming surface.
    """
    discovered = sorted(
        _discover_all_geo_entities(
            dc_api=dc_api,
            with_retries=with_retries,
            discovery_parent_batch_size=discovery_parent_batch_size,
        )
    )
    if discovered:
        emit_entities(
            "geo",
            discovered,
            UnitBatch(
                unit="geo",
                batch_index=1,
                batch_count=1,
                discovered_in_batch=len(discovered),
            ),
        )
    emit_progress(
        DomainComplete(
            unit="geo",
            requested_entity_types=requested_entity_types,
            discovered_entities=len(discovered),
        )
    )


def _discover_all_geo_entities(
    *,
    dc_api: GeoDcApi,
    with_retries: RetryFn,
    discovery_parent_batch_size: int = DISCOVERY_PARENT_BATCH_SIZE,
) -> set[str]:
    """Return the full unfiltered geo entity universe as an unsorted set.

    Covers: all geo regions + UN_REGION_DCID + countries + full admin hierarchy
    (specific types or generic fallback) + cities + custom child types under
    countries (e.g. BoroughNYCType).
    """
    place_types = with_retries(dc_api.get_place_types)
    geo_region_types = with_retries(dc_api.get_geo_region_types)
    child_place_types = [
        item for item in place_types if item not in SPECIAL_PLACE_TYPES
    ]
    typed_admins = admin_place_types(child_place_types)

    discovered: set[str] = set()

    for place_type in geo_region_types:
        discovered.update(
            discover_geo_region_entities(
                dc_api=dc_api,
                with_retries=with_retries,
                raw_type=place_type,
            )
        )
    discovered.add(UN_REGION_DCID)

    countries = with_retries(
        dc_api.get_places,
        place_type=PLACE_TYPE_COUNTRY,
        parent_place=ROOT_PLACE_DCID,
    )
    discovered.update(countries)

    def _collect(_unit: str, ids: list[str], _meta: DiscoveryProgressEvent) -> None:
        discovered.update(ids)

    # Walk every admin level the DC instance reports; a wide fallback covers
    # the generic-type path (no typed_admins) where depth is unknown until the
    # walk's frontier exhausts. The legacy form had no level cap.
    admin_levels_to_emit = (
        {level for level, _ in typed_admins} if typed_admins else set(range(1, 20))
    )
    discover_requested_admin_entities_incremental(
        dc_api=dc_api,
        with_retries=with_retries,
        requested_raw_types={PLACE_TYPE_CITY},
        requested_admin_levels=admin_levels_to_emit,
        admin_place_types=typed_admins,
        countries=lambda: countries,
        emit_entities=_collect,
        emit_progress=lambda _payload: None,
        discovery_parent_batch_size=discovery_parent_batch_size,
        seed_frontier=None,
    )

    # Sweep custom child types (non-admin, non-city, non-region) under
    # countries — e.g. BoroughNYCType-style oddities that don't fit the
    # standard admin/city/region taxonomy.
    skip_place_types = {PLACE_TYPE_ADMINISTRATIVE_AREA, PLACE_TYPE_CITY} | set(
        geo_region_types
    )
    for place_type in child_place_types:
        if place_type in skip_place_types:
            continue
        children_by_country = with_retries(
            dc_api.get_places_by_parents,
            place_type=place_type,
            parent_places=countries,
            chunk_size=discovery_parent_batch_size,
            max_workers=DISCOVERY_MAX_WORKERS,
        )
        for child_ids in children_by_country.values():
            discovered.update(child_ids)

    return discovered


def _discover_requested_country_scoped_children_incremental(
    *,
    dc_api: GeoDcApi,
    with_retries: RetryFn,
    requested_raw_types: set[str],
    child_place_types: list[str],
    geo_region_types: set[str],
    countries: Callable[[], list[str]],
    emit_entities: DiscoveryBatchFn,
    emit_progress: DiscoveryProgressFn,
    discovery_parent_batch_size: int = DISCOVERY_PARENT_BATCH_SIZE,
) -> None:
    selected_child_types = [
        place_type
        for place_type in child_place_types
        if place_type in requested_raw_types
        and place_type not in {PLACE_TYPE_ADMINISTRATIVE_AREA, PLACE_TYPE_CITY}
        and place_type not in geo_region_types
        and admin_level_from_raw_type(place_type) is None
    ]
    if not selected_child_types:
        return

    parent_countries = countries()
    for place_type in selected_child_types:
        unit = discovery_unit_for_raw_type(place_type)
        if unit is None:
            continue
        stream_parent_children(
            dc_api=dc_api,
            with_retries=with_retries,
            place_type=place_type,
            parent_places=parent_countries,
            unit=unit,
            emit_entities=emit_entities,
            emit_progress=emit_progress,
            progress=StreamProgressContext(
                raw_type=place_type,
                source_unit="countries",
            ),
            discovery_parent_batch_size=discovery_parent_batch_size,
        )
