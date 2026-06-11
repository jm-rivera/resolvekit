"""Shared progress-context dataclass for streaming + emitter collaboration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class StreamProgressContext:
    """Caller-supplied context fields propagated into events emitted by
    stream_parent_children + OrderedBatchEmitter.

    Field-population semantics:
    - raw_type: always populated (e.g. "City", "AdministrativeArea1"). Required.
    - level: populated for admin-hierarchy walks (level=1..6). None for city /
      custom-child sweeps where 'level' has no meaning.
    - source_unit: populated for derived units to identify the parent unit
      they were fetched from ("countries", "admin1", "cache"). None for root
      entity emits (countries themselves) and for the unfiltered fallback.
    - source_level: populated only when both source_unit is an admin level
      AND the consumer needs to disambiguate which level. None otherwise.
    """

    raw_type: str
    level: int | None = None
    source_unit: str | None = None
    source_level: int | None = None
