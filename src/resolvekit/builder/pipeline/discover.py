"""Discover-stage helpers for domain entity-ID collection."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from resolvekit.builder.geo_shared import GeoSharedStore
from resolvekit.builder.models import EntityFilter
from resolvekit.builder.pipeline.build_report import write_build_report
from resolvekit.builder.pipeline.geo_staging import (
    _compute_geo_seed_frontier,
    _geo_coverage_status,
    _set_geo_coverage_meta,
)

# Geo discovery short-circuits when shared coverage is already ready,
# and seeds the streaming adapter with cached parent IDs from the
# shared store. These helpers live in geo_staging.py because they
# also drive packaging-time DB resolution; importing them here is
# the only cross-module dependency in the new pipeline split.
from resolvekit.builder.sources.discovery_events import (
    BatchComplete,
    DiscoverProgress,
    DiscoveryProgressEvent,
    DomainComplete,
    DomainProgress,
    DomainStart,
    UnitBatch,
    UnitComplete,
    UnitProgress,
    UnitStart,
)
from resolvekit.builder.sources.protocol import (
    IncrementalFilteredDiscoveryAdapter,
    adapter_supports_filtered_discovery,
)
from resolvekit.builder.utils import chunk_list

if TYPE_CHECKING:
    from resolvekit.builder.pipeline.core import BuildContext

from resolvekit.builder.pipeline.types import BuildExecutionError


def _domain_filters_for_domain(
    context: BuildContext, domain: str
) -> list[EntityFilter]:
    return [
        recipe.entity_filter
        for recipe in context.plan.recipes
        if recipe.domain == domain
    ]


def _merged_entity_types(
    domain_filters: list[EntityFilter],
) -> set[str] | None:
    """Return merged entity types from filters, or None if any filter is open."""
    if not domain_filters:
        return None
    if any(not domain_filter.include_entity_types for domain_filter in domain_filters):
        return None
    merged = {
        entity_type.strip()
        for domain_filter in domain_filters
        for entity_type in domain_filter.include_entity_types
        if entity_type.strip()
    }
    return merged or None


def _discovery_requirements(
    context: BuildContext, domain: str
) -> dict[str, Any] | None:
    """Return typed discovery requirements when recipes are explicit."""
    domain_filters = _domain_filters_for_domain(context, domain)
    merged = _merged_entity_types(domain_filters)
    if merged is None:
        return None

    return {
        "include_entity_types": sorted(merged),
        "include_relation_targets": any(
            domain_filter.include_relation_targets for domain_filter in domain_filters
        ),
    }


def _discovery_entity_type_allowlist(
    context: BuildContext,
    domain: str,
) -> set[str] | None:
    """Return a safe discovery-time type allowlist for a domain, if any."""
    domain_filters = _domain_filters_for_domain(context, domain)
    # Keep behavior unchanged unless every recipe is explicit about entity types
    # and none depend on relation-target expansion during packaging.
    if any(domain_filter.include_relation_targets for domain_filter in domain_filters):
        return None
    return _merged_entity_types(domain_filters)


def _filter_discovered_entities(
    *,
    adapter: Any,
    domain: str,
    entity_ids: list[str],
    include_entity_types: list[str],
) -> list[str]:
    """Optionally prune discovered IDs via adapter-specific typed filtering."""
    if not adapter_supports_filtered_discovery(adapter):
        return entity_ids

    filtered = adapter.filter_discovered_entities(
        domain,
        entity_ids,
        include_entity_types,
    )
    # Preserve stable order and de-duplicate in case an adapter returns duplicates.
    return list(dict.fromkeys(filtered))


def _ensure_domain_discover_progress(
    progress: DiscoverProgress,
    domain: str,
) -> DomainProgress:
    return progress.domains.setdefault(domain, DomainProgress())


def _discover_domain(
    *,
    context: BuildContext,
    domain: str,
    progress: DiscoverProgress,
) -> None:
    adapter = context.adapters.get(domain)
    if adapter is None:
        raise BuildExecutionError(
            f"No source adapter registered for domain '{domain}'."
        )

    context.state.delete_chunks_for_domain(domain)
    domain_progress = _ensure_domain_discover_progress(progress, domain)
    _persist_discover_progress(context, progress, force=True)

    geo_missing_units: set[str] | None = None
    geo_ready_units: set[str] = set()
    if domain == "geo":
        geo_status = _geo_coverage_status(context)
        _, geo_ready_units, missing = geo_status
        domain_progress.coverage = _set_geo_coverage_meta(context, status=geo_status)
        geo_missing_units = missing
        if not geo_missing_units:
            domain_progress.mode = "shared_ready"
            domain_progress.status = "shared_ready"
            domain_progress.last_event = "shared_ready"
            _persist_discover_progress(context, progress, force=True)
            return

    requirements = _discovery_requirements(context, domain)
    if domain == "geo" and geo_missing_units is not None:
        missing_entity_types = sorted(
            GeoSharedStore.units_to_entity_types(geo_missing_units)
        )
        if missing_entity_types:
            requirements = {
                "include_entity_types": missing_entity_types,
                "include_relation_targets": False,
            }

    seed_frontier: dict[str, list[str]] | None = None
    if domain == "geo" and geo_missing_units is not None and requirements:
        seed_frontier = _compute_geo_seed_frontier(
            context, geo_missing_units, ready_units=geo_ready_units
        )

    entity_ids = _discover_domain_entity_ids(
        context=context,
        adapter=adapter,
        domain=domain,
        requirements=requirements,
        progress=progress,
        seed_frontier=seed_frontier,
    )

    written_chunks = 0
    for index, chunk_ids in enumerate(
        chunk_list(entity_ids, context.options.chunk_size)
    ):
        context.state.upsert_chunk(f"{domain}:{index:06d}", domain, chunk_ids)
        written_chunks = index + 1
    if entity_ids:
        domain_progress.chunk_count = written_chunks
        domain_progress.discovered_entities = len(entity_ids)
    domain_progress.status = "complete"
    domain_progress.last_event = "domain_complete"
    _persist_discover_progress(context, progress, force=True)


def _discover_domain_entity_ids(
    *,
    context: BuildContext,
    adapter: Any,
    domain: str,
    requirements: dict[str, Any] | None,
    progress: DiscoverProgress,
    seed_frontier: dict[str, list[str]] | None = None,
) -> list[str]:
    domain_progress = _ensure_domain_discover_progress(progress, domain)
    if requirements and isinstance(adapter, IncrementalFilteredDiscoveryAdapter):
        return _discover_entities_incrementally(
            context=context,
            adapter=adapter,
            domain=domain,
            requirements=requirements,
            progress=progress,
            seed_frontier=seed_frontier,
        )
    if requirements and adapter_supports_filtered_discovery(adapter):
        domain_progress.mode = "filtered"
        domain_progress.status = "running"
        domain_progress.requested_entity_types = list(
            requirements["include_entity_types"]
        )
        domain_progress.include_relation_targets = bool(
            requirements["include_relation_targets"]
        )
        _persist_discover_progress(context, progress, force=True)
        return adapter.discover_entities_filtered(
            domain,
            requirements["include_entity_types"],
            requirements["include_relation_targets"],
        )

    domain_progress.mode = "full"
    domain_progress.status = "running"
    _persist_discover_progress(context, progress, force=True)
    entity_ids = adapter.discover_entities(domain)
    allowlist = _discovery_entity_type_allowlist(context, domain)
    if not allowlist:
        return entity_ids
    return _filter_discovered_entities(
        adapter=adapter,
        domain=domain,
        entity_ids=entity_ids,
        include_entity_types=sorted(allowlist),
    )


_PERSIST_DEBOUNCE_SECONDS: float = 2.0


def _persist_discover_progress(
    context: BuildContext,
    progress: DiscoverProgress,
    *,
    force: bool = False,
) -> None:
    now = time.monotonic()
    if (
        not force
        and (now - context._last_discover_persist_time) < _PERSIST_DEBOUNCE_SECONDS
    ):
        return
    context._last_discover_persist_time = now
    context.state.set_meta(
        "discover_progress",
        progress.model_dump(mode="json", exclude_none=True),
    )
    context.state.set_meta("discovered_chunks", context.state.count_chunks_by_domain())
    write_build_report(context)


def _apply_unit_event(
    unit_progress: UnitProgress,
    event: UnitStart | UnitBatch | BatchComplete | UnitComplete,
) -> None:
    match event:
        case UnitStart():
            unit_progress.raw_type = event.raw_type
            unit_progress.level = event.level
            unit_progress.source_unit = event.source_unit
            unit_progress.source_level = event.source_level
            unit_progress.batch_count = event.batch_count
            unit_progress.parent_count = event.parent_count
            unit_progress.status = "running"
        case UnitBatch():
            unit_progress.raw_type = event.raw_type
            unit_progress.level = event.level
            unit_progress.source_unit = event.source_unit
            unit_progress.source_level = event.source_level
            unit_progress.batch_index = event.batch_index
            unit_progress.batch_count = event.batch_count
            unit_progress.discovered_in_batch = event.discovered_in_batch
            unit_progress.discovered_total = event.discovered_total
            unit_progress.status = "running"
        case BatchComplete():
            unit_progress.raw_type = event.raw_type
            unit_progress.level = event.level
            unit_progress.source_unit = event.source_unit
            unit_progress.source_level = event.source_level
            unit_progress.batch_index = event.batch_index
            unit_progress.batch_count = event.batch_count
            unit_progress.completed_batches = event.completed_batches
            unit_progress.status = "running"
        case UnitComplete():
            unit_progress.raw_type = event.raw_type
            unit_progress.level = event.level
            unit_progress.source_unit = event.source_unit
            unit_progress.source_level = event.source_level
            unit_progress.batch_count = event.batch_count
            unit_progress.completed_batches = event.completed_batches
            unit_progress.discovered_entities = event.discovered_entities
            unit_progress.status = "complete"


def _merge_discover_progress_event(
    domain_progress: DomainProgress,
    event: DiscoveryProgressEvent,
) -> None:
    domain_progress.last_event = event.event
    match event:
        case DomainStart():
            domain_progress.status = "running"
            domain_progress.requested_entity_types = list(event.requested_entity_types)
            domain_progress.include_relation_targets = event.include_relation_targets
        case DomainComplete():
            domain_progress.status = "complete"
            domain_progress.requested_entity_types = list(event.requested_entity_types)
            if event.discovered_entities is not None:
                domain_progress.discovered_entities = event.discovered_entities
        case UnitStart() | UnitBatch() | BatchComplete() | UnitComplete():
            domain_progress.current_unit = event.unit
            unit_progress = domain_progress.units.setdefault(event.unit, UnitProgress())
            _apply_unit_event(unit_progress, event)


def _discover_entities_incrementally(
    *,
    context: BuildContext,
    adapter: IncrementalFilteredDiscoveryAdapter,
    domain: str,
    requirements: dict[str, Any],
    progress: DiscoverProgress,
    seed_frontier: dict[str, list[str]] | None = None,
) -> list[str]:
    domain_progress = _ensure_domain_discover_progress(progress, domain)
    domain_progress.mode = "incremental_filtered"
    domain_progress.status = "running"
    domain_progress.requested_entity_types = list(requirements["include_entity_types"])
    domain_progress.include_relation_targets = bool(
        requirements["include_relation_targets"]
    )
    _persist_discover_progress(context, progress, force=True)

    seen_ids: set[str] = set()
    chunk_buffer: list[str] = []
    next_chunk_index = 0

    def flush_chunks(*, force: bool = False) -> None:
        nonlocal chunk_buffer, next_chunk_index
        while len(chunk_buffer) >= context.options.chunk_size or (
            force and chunk_buffer
        ):
            chunk_ids = chunk_buffer[: context.options.chunk_size]
            chunk_buffer = chunk_buffer[context.options.chunk_size :]
            context.state.upsert_chunk(
                f"{domain}:{next_chunk_index:06d}",
                domain,
                chunk_ids,
            )
            next_chunk_index += 1
            domain_progress.chunk_count = next_chunk_index
            _persist_discover_progress(context, progress, force=force)

    def emit_entities(
        unit: str,
        entity_ids: list[str],
        metadata: DiscoveryProgressEvent,
    ) -> None:
        new_ids = [entity_id for entity_id in entity_ids if entity_id not in seen_ids]
        _merge_discover_progress_event(domain_progress, metadata)
        if not new_ids:
            return
        seen_ids.update(new_ids)
        chunk_buffer.extend(new_ids)
        domain_progress.discovered_entities = len(seen_ids)
        flush_chunks()

    def emit_progress(payload: DiscoveryProgressEvent) -> None:
        _merge_discover_progress_event(domain_progress, payload)
        force = isinstance(payload, DomainStart | DomainComplete | UnitComplete)
        _persist_discover_progress(context, progress, force=force)

    adapter.discover_entities_filtered_incremental(
        domain,
        include_entity_types=requirements["include_entity_types"],
        include_relation_targets=requirements["include_relation_targets"],
        emit_entities=emit_entities,
        emit_progress=emit_progress,
        seed_frontier=seed_frontier,
    )

    flush_chunks(force=True)
    domain_progress.chunk_count = next_chunk_index
    domain_progress.discovered_entities = len(seen_ids)
    domain_progress.status = "complete"
    domain_progress.last_event = "domain_complete"
    return []
