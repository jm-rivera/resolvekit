"""Typed discovery events and accumulator.

The 6 event classes plus `DiscoveryProgressEvent` are the public protocol
surface — any source adapter that implements
`IncrementalFilteredDiscoveryAdapter` constructs these and passes them to
`emit_progress` / `emit_entities`.

`DiscoverProgress`, `DomainProgress`, `UnitProgress` are pipeline-internal
accumulators consumed only by `pipeline/discover.py` and (read-only) by
`pipeline/build_report.py`. They are exported for typing, not for
construction by source adapters.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from resolvekit.builder.geo_shared import GeoCoverageMeta

__all__ = [  # noqa: RUF022 — grouped by surface (public events vs internal accumulators), not alphabetical
    # Public protocol surface — events crossing the producer/consumer boundary.
    "DiscoveryProgressEvent",
    "DomainStart",
    "DomainComplete",
    "UnitStart",
    "UnitBatch",
    "BatchComplete",
    "UnitComplete",
    # Pipeline-internal accumulators (re-exported for typing on consumer side).
    "DiscoverProgress",
    "DomainProgress",
    "UnitProgress",
]


class _EventBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    unit: str


class DomainStart(_EventBase):
    event: Literal["domain_start"] = "domain_start"
    requested_entity_types: list[str] = Field(default_factory=list)
    include_relation_targets: bool = False


class DomainComplete(_EventBase):
    event: Literal["domain_complete"] = "domain_complete"
    requested_entity_types: list[str] = Field(default_factory=list)
    discovered_entities: int | None = None


class UnitStart(_EventBase):
    event: Literal["unit_start"] = "unit_start"
    raw_type: str | None = None
    level: int | None = None
    source_unit: str | None = None
    source_level: int | None = None
    batch_count: int = 0
    parent_count: int | None = None


class UnitBatch(_EventBase):
    event: Literal["unit_batch"] = "unit_batch"
    raw_type: str | None = None
    level: int | None = None
    source_unit: str | None = None
    source_level: int | None = None
    batch_index: int
    batch_count: int
    discovered_in_batch: int
    discovered_total: int | None = None


class BatchComplete(_EventBase):
    event: Literal["batch_complete"] = "batch_complete"
    raw_type: str | None = None
    level: int | None = None
    source_unit: str | None = None
    source_level: int | None = None
    batch_index: int
    batch_count: int
    completed_batches: int


class UnitComplete(_EventBase):
    event: Literal["unit_complete"] = "unit_complete"
    raw_type: str | None = None
    level: int | None = None
    source_unit: str | None = None
    source_level: int | None = None
    batch_count: int = 0
    completed_batches: int = 0
    discovered_entities: int = 0


# Use TypeAlias rather than PEP 695 'type' keyword — pydantic v2 discriminated-union
# aliases are tested with TypeAlias; PEP 695 support is unverified.
DiscoveryProgressEvent: TypeAlias = Annotated[  # noqa: UP040 — see comment above re: PEP 695
    DomainStart | DomainComplete | UnitStart | UnitBatch | BatchComplete | UnitComplete,
    Field(discriminator="event"),
]


class UnitProgress(BaseModel):
    """Internal per-unit discovery-progress accumulator (consumer-mutated)."""

    model_config = ConfigDict(extra="ignore")
    status: Literal["pending", "running", "complete"] = "pending"
    raw_type: str | None = None
    level: int | None = None
    source_unit: str | None = None
    source_level: int | None = None
    batch_count: int = 0
    completed_batches: int = 0
    parent_count: int | None = None
    discovered_entities: int = 0
    discovered_in_batch: int | None = None
    discovered_total: int | None = None
    # Kept for behavior preservation: today's consumer opportunistically copies
    # batch_index from UnitBatch / BatchComplete payloads.
    batch_index: int | None = None


class DomainProgress(BaseModel):
    """Internal per-domain discovery-progress accumulator (consumer-mutated)."""

    model_config = ConfigDict(extra="ignore")
    mode: Literal[
        "pending", "filtered", "incremental_filtered", "full", "shared_ready"
    ] = "pending"
    status: Literal["pending", "running", "complete", "shared_ready"] = "pending"
    requested_entity_types: list[str] = Field(default_factory=list)
    include_relation_targets: bool = False
    discovered_entities: int = 0
    chunk_count: int = 0
    last_event: str | None = None
    current_unit: str | None = None
    units: dict[str, UnitProgress] = Field(default_factory=dict)
    coverage: GeoCoverageMeta | None = None


class DiscoverProgress(BaseModel):
    """Internal discovery-progress accumulator (top-level, persisted via set_meta)."""

    model_config = ConfigDict(extra="ignore")
    domains: dict[str, DomainProgress] = Field(default_factory=dict)
