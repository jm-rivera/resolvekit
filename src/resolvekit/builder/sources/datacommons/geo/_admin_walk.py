"""Admin-hierarchy traversal: dispatcher, two algorithm variants, seed-frontier prepass."""

from __future__ import annotations

from collections.abc import Callable

from resolvekit.builder.sources.datacommons.geo._streaming import (
    StreamProgressContext,
    stream_parent_children,
)
from resolvekit.builder.sources.datacommons.geo.dc_api import GeoDcApi
from resolvekit.builder.sources.datacommons.geo.mappings import (
    DISCOVERY_PARENT_BATCH_SIZE,
    PLACE_TYPE_ADMINISTRATIVE_AREA,
    PLACE_TYPE_CITY,
)
from resolvekit.builder.sources.discovery_events import UnitComplete, UnitStart
from resolvekit.builder.sources.protocol import (
    DiscoveryBatchFn,
    DiscoveryProgressFn,
    RetryFn,
)


def discover_requested_admin_entities_incremental(
    *,
    dc_api: GeoDcApi,
    with_retries: RetryFn,
    requested_raw_types: set[str],
    requested_admin_levels: set[int],
    admin_place_types: list[tuple[int, str]],
    countries: Callable[[], list[str]],
    emit_entities: DiscoveryBatchFn,
    emit_progress: DiscoveryProgressFn,
    discovery_parent_batch_size: int = DISCOVERY_PARENT_BATCH_SIZE,
    seed_frontier: dict[str, list[str]] | None = None,
) -> None:
    if not requested_admin_levels and PLACE_TYPE_CITY not in requested_raw_types:
        return

    country_ids = countries()
    include_cities = PLACE_TYPE_CITY in requested_raw_types
    max_admin_level = (
        None if include_cities else max(requested_admin_levels, default=None)
    )

    if admin_place_types:
        _discover_admin_hierarchy_by_specific_types_incremental(
            dc_api=dc_api,
            with_retries=with_retries,
            countries=country_ids,
            admin_place_types=admin_place_types,
            include_cities=include_cities,
            emit_admin_levels=requested_admin_levels,
            max_admin_level=max_admin_level,
            emit_entities=emit_entities,
            emit_progress=emit_progress,
            discovery_parent_batch_size=discovery_parent_batch_size,
            seed_frontier=seed_frontier,
        )
        return

    _discover_admin_hierarchy_by_generic_type_incremental(
        dc_api=dc_api,
        with_retries=with_retries,
        countries=country_ids,
        include_cities=include_cities,
        emit_admin_levels=requested_admin_levels,
        max_admin_level=max_admin_level,
        emit_entities=emit_entities,
        emit_progress=emit_progress,
        discovery_parent_batch_size=discovery_parent_batch_size,
        seed_frontier=seed_frontier,
    )


def _emit_cached_level_progress(
    *,
    unit: str,
    raw_type: str,
    level: int,
    entity_count: int,
    emit_progress: DiscoveryProgressFn,
) -> None:
    """Emit start/complete progress for a level served entirely from cache."""
    emit_progress(
        UnitStart(
            unit=unit,
            raw_type=raw_type,
            level=level,
            batch_count=0,
            source_unit="cache",
        )
    )
    emit_progress(
        UnitComplete(
            unit=unit,
            raw_type=raw_type,
            level=level,
            batch_count=0,
            completed_batches=0,
            discovered_entities=entity_count,
        )
    )


def _apply_seed_frontier_prepass(
    *,
    dc_api: GeoDcApi,
    with_retries: RetryFn,
    countries: list[str],
    seed_frontier: dict[str, list[str]] | None,
    include_cities: bool,
    emit_entities: DiscoveryBatchFn,
    emit_progress: DiscoveryProgressFn,
    discovery_parent_batch_size: int,
    discovered_cities: set[str],
    discovered_admins: set[str] | None = None,
) -> tuple[list[str], int, set[int]]:
    """Apply seed_frontier cache-hit emits and the country→city scan.

    Always runs the country→city scan (when include_cities) to catch cities
    parented directly under a country (Singapore, Vatican, Monaco style).
    Then walks the contiguous cached admin chain in seed_frontier, emitting
    only cached-level progress (no entity batch) and city scans per level.

    Returns (frontier, start_level, city_scanned_levels): the frontier to
    resume from, the level number to start walking, and the set of admin
    levels whose city scan has already been completed.

    ``discovered_cities`` is mutated in place (shared dedup set).
    ``discovered_admins`` is mutated in place when provided (generic-type
    callers pass their admin dedup set so cached IDs are registered).
    """
    city_scanned_levels: set[int] = set()
    if include_cities and countries:
        stream_parent_children(
            dc_api=dc_api,
            with_retries=with_retries,
            place_type=PLACE_TYPE_CITY,
            parent_places=countries,
            unit="cities",
            emit_entities=emit_entities,
            emit_progress=emit_progress,
            seen_ids=discovered_cities,
            progress=StreamProgressContext(
                raw_type=PLACE_TYPE_CITY, source_unit="countries"
            ),
            discovery_parent_batch_size=discovery_parent_batch_size,
        )
        city_scanned_levels.add(1)

    frontier: list[str] = []
    start_level = 1
    if not seed_frontier:
        return frontier, start_level, city_scanned_levels

    for cached_unit in [f"admin{i}" for i in range(1, 7)]:
        if cached_unit not in seed_frontier:
            break
        cached_level = int(cached_unit.removeprefix("admin"))
        cached_ids = seed_frontier[cached_unit]
        _emit_cached_level_progress(
            unit=cached_unit,
            raw_type=PLACE_TYPE_ADMINISTRATIVE_AREA,
            level=cached_level,
            entity_count=len(cached_ids),
            emit_progress=emit_progress,
        )
        if discovered_admins is not None:
            discovered_admins.update(cached_ids)
        if include_cities:
            stream_parent_children(
                dc_api=dc_api,
                with_retries=with_retries,
                place_type=PLACE_TYPE_CITY,
                parent_places=cached_ids,
                unit="cities",
                emit_entities=emit_entities,
                emit_progress=emit_progress,
                seen_ids=discovered_cities,
                progress=StreamProgressContext(
                    raw_type=PLACE_TYPE_CITY,
                    source_unit=cached_unit,
                ),
                discovery_parent_batch_size=discovery_parent_batch_size,
            )
            city_scanned_levels.add(cached_level + 1)
        frontier = list(cached_ids)
        start_level = cached_level + 1

    return frontier, start_level, city_scanned_levels


def _discover_admin_hierarchy_by_specific_types_incremental(
    *,
    dc_api: GeoDcApi,
    with_retries: RetryFn,
    countries: list[str],
    admin_place_types: list[tuple[int, str]],
    include_cities: bool,
    emit_admin_levels: set[int],
    emit_entities: DiscoveryBatchFn,
    emit_progress: DiscoveryProgressFn,
    max_admin_level: int | None = None,
    discovery_parent_batch_size: int = DISCOVERY_PARENT_BATCH_SIZE,
    seed_frontier: dict[str, list[str]] | None = None,
) -> None:
    discovered_cities: set[str] = set()
    country_frontier = (
        list(seed_frontier["countries"])
        if seed_frontier and "countries" in seed_frontier
        else list(countries)
    )
    frontier, start_level, city_scanned_levels = _apply_seed_frontier_prepass(
        dc_api=dc_api,
        with_retries=with_retries,
        countries=country_frontier,
        seed_frontier=seed_frontier,
        include_cities=include_cities,
        emit_entities=emit_entities,
        emit_progress=emit_progress,
        discovery_parent_batch_size=discovery_parent_batch_size,
        discovered_cities=discovered_cities,
        discovered_admins=None,
    )
    if not frontier:
        frontier = list(countries)
    skip_levels = {level for level, _ in admin_place_types if level < start_level}

    for level, place_type in admin_place_types:
        if max_admin_level is not None and level > max_admin_level:
            break

        if level in skip_levels:
            continue

        unit = f"admin{level}"
        next_frontier = stream_parent_children(
            dc_api=dc_api,
            with_retries=with_retries,
            place_type=place_type,
            parent_places=frontier,
            unit=unit,
            emit_entities=emit_entities,
            emit_progress=emit_progress,
            emit_discovered=level in emit_admin_levels,
            progress=StreamProgressContext(
                raw_type=place_type,
                level=level,
                source_unit="countries" if level == 1 else f"admin{level - 1}",
            ),
            discovery_parent_batch_size=discovery_parent_batch_size,
        )
        if not next_frontier:
            break
        frontier = next_frontier
        if include_cities and (level + 1) not in city_scanned_levels:
            stream_parent_children(
                dc_api=dc_api,
                with_retries=with_retries,
                place_type=PLACE_TYPE_CITY,
                parent_places=frontier,
                unit="cities",
                emit_entities=emit_entities,
                emit_progress=emit_progress,
                seen_ids=discovered_cities,
                progress=StreamProgressContext(
                    raw_type=PLACE_TYPE_CITY,
                    source_unit=unit,
                    source_level=level,
                ),
                discovery_parent_batch_size=discovery_parent_batch_size,
            )


def _discover_admin_hierarchy_by_generic_type_incremental(
    *,
    dc_api: GeoDcApi,
    with_retries: RetryFn,
    countries: list[str],
    include_cities: bool,
    emit_admin_levels: set[int],
    emit_entities: DiscoveryBatchFn,
    emit_progress: DiscoveryProgressFn,
    max_admin_level: int | None = None,
    discovery_parent_batch_size: int = DISCOVERY_PARENT_BATCH_SIZE,
    seed_frontier: dict[str, list[str]] | None = None,
) -> None:
    discovered_admins: set[str] = set()
    discovered_cities: set[str] = set()
    country_frontier = (
        list(seed_frontier["countries"])
        if seed_frontier and "countries" in seed_frontier
        else list(countries)
    )
    frontier, start_level, city_scanned_levels = _apply_seed_frontier_prepass(
        dc_api=dc_api,
        with_retries=with_retries,
        countries=country_frontier,
        seed_frontier=seed_frontier,
        include_cities=include_cities,
        emit_entities=emit_entities,
        emit_progress=emit_progress,
        discovery_parent_batch_size=discovery_parent_batch_size,
        discovered_cities=discovered_cities,
        discovered_admins=discovered_admins,
    )
    if not frontier:
        frontier = list(countries)
    level = start_level

    while frontier:
        if include_cities and level not in city_scanned_levels:
            source_unit = "countries" if level == 1 else f"admin{level - 1}"
            stream_parent_children(
                dc_api=dc_api,
                with_retries=with_retries,
                place_type=PLACE_TYPE_CITY,
                parent_places=frontier,
                unit="cities",
                emit_entities=emit_entities,
                emit_progress=emit_progress,
                seen_ids=discovered_cities,
                progress=StreamProgressContext(
                    raw_type=PLACE_TYPE_CITY,
                    source_unit=source_unit,
                ),
                discovery_parent_batch_size=discovery_parent_batch_size,
            )

        if max_admin_level is not None and level > max_admin_level:
            break

        unit = f"admin{level}"
        next_frontier = stream_parent_children(
            dc_api=dc_api,
            with_retries=with_retries,
            place_type=PLACE_TYPE_ADMINISTRATIVE_AREA,
            parent_places=frontier,
            unit=unit,
            emit_entities=emit_entities,
            emit_progress=emit_progress,
            emit_discovered=level in emit_admin_levels,
            seen_ids=discovered_admins,
            progress=StreamProgressContext(
                raw_type=PLACE_TYPE_ADMINISTRATIVE_AREA,
                level=level,
                source_unit="countries" if level == 1 else f"admin{level - 1}",
            ),
            discovery_parent_batch_size=discovery_parent_batch_size,
        )
        if not next_frontier:
            break
        frontier = next_frontier
        level += 1
