"""Unit tests for OrderedBatchEmitter (_ordered_emitter.py characterization).

Tests pin the ordering invariant, dedup behavior, and emit_discovered flag of
the OrderedBatchEmitter class against the current HEAD implementation.
"""

from __future__ import annotations

from resolvekit.builder.sources.datacommons.geo._ordered_emitter import (
    OrderedBatchEmitter,
)
from resolvekit.builder.sources.datacommons.geo._streaming import StreamProgressContext
from resolvekit.builder.sources.discovery_events import (
    BatchComplete,
    DiscoveryProgressEvent,
    UnitBatch,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_emitter(
    *,
    parent_batches: list[list[str]],
    emit_discovered: bool = True,
    seen_ids: set[str] | None = None,
) -> tuple[
    OrderedBatchEmitter,
    list[tuple[str, list[str], DiscoveryProgressEvent]],
    list[DiscoveryProgressEvent],
]:
    """Build an OrderedBatchEmitter instance with capture callbacks.

    Returns:
        (emitter, entity_calls, progress_calls) where entity_calls is a list
        of (unit, ids, metadata) tuples and progress_calls is a list of
        typed event instances.
    """
    entity_calls: list[tuple[str, list[str], DiscoveryProgressEvent]] = []
    progress_calls: list[DiscoveryProgressEvent] = []

    def emit_entities(
        unit: str, ids: list[str], metadata: DiscoveryProgressEvent
    ) -> None:
        entity_calls.append((unit, list(ids), metadata))

    def emit_progress(payload: DiscoveryProgressEvent) -> None:
        progress_calls.append(payload)

    emitter = OrderedBatchEmitter(
        unit="admin1",
        parent_batches=parent_batches,
        emit_entities=emit_entities,
        emit_progress=emit_progress,
        progress=StreamProgressContext(raw_type="AdministrativeArea1", level=1),
        emit_discovered=emit_discovered,
        seen_ids=seen_ids,
    )
    return emitter, entity_calls, progress_calls


# ---------------------------------------------------------------------------
# ordered-emitter tests
# ---------------------------------------------------------------------------


def test_empty_parent_batches_emits_nothing() -> None:
    """Zero parent batches → no entity events, no progress events, empty ids."""
    emitter, entity_calls, progress_calls = make_emitter(parent_batches=[])

    assert emitter.ordered_ids == []
    assert emitter.discovered_total == 0
    assert emitter.completed_batches == 0
    assert entity_calls == []
    assert progress_calls == []


def test_record_in_monotonic_order_emits_unit_batches_in_order() -> None:
    """Batches arriving 0, 1, 2 must produce unit_batch events in that order."""
    parent_batches = [
        ["country/USA"],
        ["country/GBR"],
        ["country/FRA"],
    ]
    batch_results = [
        {"country/USA": ["admin1/CA", "admin1/NY"]},
        {"country/GBR": ["admin1/ENG", "admin1/SCT"]},
        {"country/FRA": ["admin1/IDF"]},
    ]
    emitter, entity_calls, _progress_calls = make_emitter(
        parent_batches=parent_batches,
    )

    for i, result in enumerate(batch_results):
        emitter.record(i, result)

    # unit_batch events fire via emit_entities; their batch_index is in metadata
    unit_batch_metas = [
        meta for _u, _ids, meta in entity_calls if isinstance(meta, UnitBatch)
    ]
    assert [m.batch_index for m in unit_batch_metas] == [1, 2, 3]

    # entity_calls should contain all ids, sorted within each batch
    assert (entity_calls[0][0], entity_calls[0][1]) == (
        "admin1",
        sorted(["admin1/CA", "admin1/NY"]),
    )
    assert (entity_calls[1][0], entity_calls[1][1]) == (
        "admin1",
        sorted(["admin1/ENG", "admin1/SCT"]),
    )
    assert (entity_calls[2][0], entity_calls[2][1]) == ("admin1", ["admin1/IDF"])

    # ordered_ids is the concatenation of per-batch sorted lists
    assert emitter.ordered_ids == [
        "admin1/CA",
        "admin1/NY",
        "admin1/ENG",
        "admin1/SCT",
        "admin1/IDF",
    ]
    assert emitter.discovered_total == 5
    assert emitter.completed_batches == 3


def test_record_in_reverse_order_buffers_until_zero_arrives() -> None:
    """Batches arriving 2, 1, 0 must buffer 2 and 1 until 0 arrives, then
    flush 0 → 1 → 2 in index order."""
    parent_batches = [
        ["country/USA"],
        ["country/GBR"],
        ["country/FRA"],
    ]
    batch_results = [
        {"country/USA": ["admin1/CA"]},
        {"country/GBR": ["admin1/ENG"]},
        {"country/FRA": ["admin1/IDF"]},
    ]
    emitter, entity_calls, _progress_calls = make_emitter(
        parent_batches=parent_batches,
    )

    def unit_batch_indexes() -> list[int]:
        return [
            meta.batch_index
            for _u, _ids, meta in entity_calls
            if isinstance(meta, UnitBatch)
        ]

    # Deliver in reverse order
    emitter.record(2, batch_results[2])
    assert unit_batch_indexes() == []

    emitter.record(1, batch_results[1])
    assert unit_batch_indexes() == []

    emitter.record(0, batch_results[0])
    assert unit_batch_indexes() == [1, 2, 3]

    assert emitter.ordered_ids == ["admin1/CA", "admin1/ENG", "admin1/IDF"]
    assert emitter.completed_batches == 3


def test_record_in_random_order_flushes_in_index_order() -> None:
    """Out-of-order arrivals (1, 0, 2) emit unit_batch in batch_index order."""
    parent_batches = [
        ["country/USA"],
        ["country/GBR"],
        ["country/FRA"],
    ]
    batch_results = [
        {"country/USA": ["admin1/CA"]},
        {"country/GBR": ["admin1/ENG"]},
        {"country/FRA": ["admin1/IDF"]},
    ]
    emitter, entity_calls, _progress_calls = make_emitter(
        parent_batches=parent_batches,
    )

    def unit_batch_indexes() -> list[int]:
        return [
            meta.batch_index
            for _u, _ids, meta in entity_calls
            if isinstance(meta, UnitBatch)
        ]

    # deliver: batch 1 first, then 0 (flushes 0+1), then 2
    emitter.record(1, batch_results[1])
    assert unit_batch_indexes() == []

    emitter.record(0, batch_results[0])
    assert unit_batch_indexes() == [1, 2]

    emitter.record(2, batch_results[2])
    assert unit_batch_indexes() == [1, 2, 3]

    assert emitter.ordered_ids == ["admin1/CA", "admin1/ENG", "admin1/IDF"]


def test_seen_ids_dedups_across_batches() -> None:
    """IDs already in seen_ids (from a prior batch or shared set) are dropped."""
    parent_batches = [
        ["country/USA"],
        ["country/GBR"],
    ]
    # batch 1 produces admin1/CA; batch 2 re-produces admin1/CA (dupe) + new admin1/ENG
    batch_results = [
        {"country/USA": ["admin1/CA", "admin1/NY"]},
        {"country/GBR": ["admin1/CA", "admin1/ENG"]},  # admin1/CA is a duplicate
    ]
    emitter, _entity_calls, _progress_calls = make_emitter(
        parent_batches=parent_batches,
    )

    emitter.record(0, batch_results[0])
    emitter.record(1, batch_results[1])

    # admin1/CA must appear only once in ordered_ids
    assert emitter.ordered_ids.count("admin1/CA") == 1
    assert "admin1/NY" in emitter.ordered_ids
    assert "admin1/ENG" in emitter.ordered_ids
    assert emitter.discovered_total == 3  # CA + NY + ENG (CA deduped)


def test_emit_discovered_false_aggregates_ordered_ids_without_emitting_entities() -> (
    None
):
    """When emit_discovered=False, ordered_ids accumulates but emit_entities is
    never called and no unit_batch progress event fires."""
    parent_batches = [
        ["country/USA"],
        ["country/GBR"],
    ]
    batch_results = [
        {"country/USA": ["admin1/CA", "admin1/NY"]},
        {"country/GBR": ["admin1/ENG"]},
    ]
    emitter, entity_calls, _progress_calls = make_emitter(
        parent_batches=parent_batches,
        emit_discovered=False,
    )

    emitter.record(0, batch_results[0])
    emitter.record(1, batch_results[1])

    # emit_entities must never be called (so no unit_batch event ever fires)
    assert entity_calls == []

    # but ordered_ids and discovered_total still accumulate
    assert set(emitter.ordered_ids) == {"admin1/CA", "admin1/NY", "admin1/ENG"}
    assert emitter.discovered_total == 3


def test_batch_complete_carries_progress_context_fields() -> None:
    """batch_complete events emitted by record() carry raw_type and level from
    the StreamProgressContext passed at construction."""
    parent_batches = [["country/USA"]]
    batch_results = [{"country/USA": ["admin1/CA"]}]

    emitter, _entity_calls, progress_calls = make_emitter(
        parent_batches=parent_batches,
    )
    emitter.record(0, batch_results[0])

    batch_complete_events = [p for p in progress_calls if isinstance(p, BatchComplete)]
    assert len(batch_complete_events) == 1
    bce = batch_complete_events[0]
    assert bce.raw_type == "AdministrativeArea1"
    assert bce.level == 1
    assert bce.unit == "admin1"
