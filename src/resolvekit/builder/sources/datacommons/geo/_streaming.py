"""Streaming-batch emit primitives for geo discovery."""

from __future__ import annotations

from resolvekit.builder.sources.datacommons.geo._chunk_callback import (
    call_get_places_by_parents_with_progress,
)
from resolvekit.builder.sources.datacommons.geo._ordered_emitter import (
    OrderedBatchEmitter,
)
from resolvekit.builder.sources.datacommons.geo._progress_context import (
    StreamProgressContext,
)
from resolvekit.builder.sources.datacommons.geo.dc_api import GeoDcApi
from resolvekit.builder.sources.datacommons.geo.mappings import (
    DISCOVERY_PARENT_BATCH_SIZE,
)
from resolvekit.builder.sources.discovery_events import (
    UnitBatch,
    UnitComplete,
    UnitStart,
)
from resolvekit.builder.sources.protocol import (
    DiscoveryBatchFn,
    DiscoveryProgressFn,
    RetryFn,
)
from resolvekit.builder.utils import chunk_list


def emit_root_entities(
    *,
    unit: str,
    entity_ids: list[str],
    emit_entities: DiscoveryBatchFn,
    emit_progress: DiscoveryProgressFn,
    raw_type: str,
) -> None:
    ordered_ids = sorted(dict.fromkeys(entity_ids))
    emit_progress(UnitStart(unit=unit, raw_type=raw_type, batch_count=1))
    if ordered_ids:
        emit_entities(
            unit,
            ordered_ids,
            UnitBatch(
                unit=unit,
                raw_type=raw_type,
                batch_index=1,
                batch_count=1,
                discovered_in_batch=len(ordered_ids),
            ),
        )
    emit_progress(
        UnitComplete(
            unit=unit,
            raw_type=raw_type,
            batch_count=1,
            completed_batches=1,
            discovered_entities=len(ordered_ids),
        )
    )


def stream_parent_children(
    *,
    dc_api: GeoDcApi,
    with_retries: RetryFn,
    place_type: str,
    parent_places: list[str],
    unit: str,
    emit_entities: DiscoveryBatchFn,
    emit_progress: DiscoveryProgressFn,
    progress: StreamProgressContext,
    emit_discovered: bool = True,
    seen_ids: set[str] | None = None,
    discovery_parent_batch_size: int = DISCOVERY_PARENT_BATCH_SIZE,
) -> list[str]:
    if not parent_places:
        emit_progress(
            UnitComplete(
                unit=unit,
                raw_type=progress.raw_type,
                level=progress.level,
                source_unit=progress.source_unit,
                source_level=progress.source_level,
                batch_count=0,
                completed_batches=0,
                discovered_entities=0,
            )
        )
        return []

    parent_batches = list(chunk_list(parent_places, discovery_parent_batch_size))
    emit_progress(
        UnitStart(
            unit=unit,
            raw_type=progress.raw_type,
            level=progress.level,
            source_unit=progress.source_unit,
            source_level=progress.source_level,
            batch_count=len(parent_batches),
            parent_count=len(parent_places),
        )
    )
    ordered = OrderedBatchEmitter(
        unit=unit,
        parent_batches=parent_batches,
        emit_entities=emit_entities,
        emit_progress=emit_progress,
        progress=progress,
        emit_discovered=emit_discovered,
        seen_ids=seen_ids,
    )
    results_by_parent, callback_seen = call_get_places_by_parents_with_progress(
        dc_api=dc_api,
        with_retries=with_retries,
        place_type=place_type,
        parent_places=parent_places,
        on_chunk_complete=ordered.record,
        discovery_parent_batch_size=discovery_parent_batch_size,
    )
    if not callback_seen:
        for batch_index, parent_batch in enumerate(parent_batches):
            ordered.record(
                batch_index,
                {
                    parent_id: results_by_parent.get(parent_id, [])
                    for parent_id in parent_batch
                },
            )
    emit_progress(
        UnitComplete(
            unit=unit,
            raw_type=progress.raw_type,
            level=progress.level,
            source_unit=progress.source_unit,
            source_level=progress.source_level,
            batch_count=len(parent_batches),
            completed_batches=ordered.completed_batches,
            discovered_entities=ordered.discovered_total,
        )
    )
    return ordered.ordered_ids
