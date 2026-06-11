"""Trace events for the explanation system."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventType(StrEnum):
    """Types of trace events emitted during resolution."""

    QUERY_NORMALIZED = "query_normalized"
    CANDIDATES_GENERATED = "candidates_generated"
    CANDIDATES_MERGED = "candidates_merged"
    CONSTRAINT_APPLIED = "constraint_applied"
    FEATURES_EXTRACTED = "features_extracted"
    SCORED = "scored"
    DECIDED = "decided"
    ERROR = "error"


class TraceEvent(BaseModel):
    """A single trace event from the resolution pipeline.

    Events are emitted by pipeline steps and collected by a TraceSink.
    They provide structured insight into how resolution proceeded.

    Attributes:
        event_type: Type of event
        source: Which component emitted this (e.g., source name, constraint name)
        data: Event-specific payload
        timestamp: When the event occurred
    """

    model_config = ConfigDict(frozen=True)

    event_type: EventType
    source: str | None = Field(default=None)
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
