"""Ordered emitter for parallel-batch discovery results."""

from __future__ import annotations

from resolvekit.builder.sources.datacommons.geo._progress_context import (
    StreamProgressContext,
)
from resolvekit.builder.sources.discovery_events import BatchComplete, UnitBatch
from resolvekit.builder.sources.protocol import (
    DiscoveryBatchFn,
    DiscoveryProgressFn,
)


class OrderedBatchEmitter:
    """Buffer parallel-arrival batch results and emit unit_batch events in
    monotonic batch_index order.

    Construction is kwargs-only. The emitter takes ownership of a ``seen_ids``
    set if one is passed in (mutated in place to share dedup state across
    sibling emitters); when None, an internal set is created.
    """

    def __init__(
        self,
        *,
        unit: str,
        parent_batches: list[list[str]],
        emit_entities: DiscoveryBatchFn,
        emit_progress: DiscoveryProgressFn,
        progress: StreamProgressContext,
        emit_discovered: bool = True,
        seen_ids: set[str] | None = None,
    ) -> None:
        self.unit = unit
        self.parent_batches = parent_batches
        self.emit_entities = emit_entities
        self.emit_progress = emit_progress
        self.progress = progress
        self.emit_discovered = emit_discovered
        self.seen_ids = seen_ids if seen_ids is not None else set()
        self._pending: dict[int, dict[str, list[str]]] = {}
        self._next_batch_index = 0
        self._completed_batches = 0
        self._discovered_total = 0
        self._ordered_ids: list[str] = []

    def record(self, batch_index: int, batch_result: dict[str, list[str]]) -> None:
        """Record a batch result; emits batch_complete then flushes ready batches."""
        self._completed_batches += 1
        self._pending[batch_index] = batch_result
        self.emit_progress(
            BatchComplete(
                unit=self.unit,
                raw_type=self.progress.raw_type,
                level=self.progress.level,
                source_unit=self.progress.source_unit,
                source_level=self.progress.source_level,
                completed_batches=self._completed_batches,
                batch_count=len(self.parent_batches),
                batch_index=batch_index + 1,
            )
        )
        self._flush_ready_batches()

    def _flush_ready_batches(self) -> None:
        while self._next_batch_index in self._pending:
            batch_result = self._pending.pop(self._next_batch_index)
            new_ids: list[str] = []
            for parent_id in self.parent_batches[self._next_batch_index]:
                for entity_id in batch_result.get(parent_id, []):
                    if entity_id in self.seen_ids:
                        continue
                    self.seen_ids.add(entity_id)
                    new_ids.append(entity_id)
            new_ids = sorted(new_ids)
            if new_ids:
                self._discovered_total += len(new_ids)
                self._ordered_ids.extend(new_ids)
                if self.emit_discovered:
                    self.emit_entities(
                        self.unit,
                        new_ids,
                        UnitBatch(
                            unit=self.unit,
                            raw_type=self.progress.raw_type,
                            level=self.progress.level,
                            source_unit=self.progress.source_unit,
                            source_level=self.progress.source_level,
                            batch_index=self._next_batch_index + 1,
                            batch_count=len(self.parent_batches),
                            discovered_in_batch=len(new_ids),
                            discovered_total=self._discovered_total,
                        ),
                    )
            self._next_batch_index += 1

    @property
    def ordered_ids(self) -> list[str]:
        """All discovered IDs, in flush order (per-batch sorted, batches in index order)."""
        return self._ordered_ids

    @property
    def discovered_total(self) -> int:
        """Cumulative count of new (post-dedup) IDs emitted so far."""
        return self._discovered_total

    @property
    def completed_batches(self) -> int:
        """Count of batches recorded (not yet necessarily flushed)."""
        return self._completed_batches
