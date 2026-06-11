"""Trace emission helpers to reduce boilerplate."""

from typing import Any

from resolvekit.core.explain.events import EventType, TraceEvent
from resolvekit.core.explain.sink import TraceSink


def emit_candidates_generated(
    trace: TraceSink,
    source: str,
    count: int,
    *,
    entity_ids: list[str] | None = None,
    query: str | None = None,
    **extra: Any,
) -> None:
    """Emit CANDIDATES_GENERATED event.

    Args:
        trace: Trace sink to emit to
        source: Name of the source generating candidates
        count: Number of candidates/evidence generated
        entity_ids: Optional list of entity IDs generated
        query: Optional normalized query text
        **extra: Additional data fields to include
    """
    data: dict[str, Any] = {"count": count, **extra}
    if entity_ids is not None:
        data["entity_ids"] = entity_ids
    if query is not None:
        data["query"] = query
    trace.emit(
        TraceEvent(event_type=EventType.CANDIDATES_GENERATED, source=source, data=data)
    )


def emit_constraint_applied(
    trace: TraceSink,
    source: str,
    *,
    checked: int | None = None,
    filtered: int | None = None,
    remaining: int | None = None,
    **extra: Any,
) -> None:
    """Emit CONSTRAINT_APPLIED event.

    Args:
        trace: Trace sink to emit to
        source: Name of the constraint
        checked: Number of candidates checked
        filtered: Number of candidates filtered out
        remaining: Number of candidates remaining after filter
        **extra: Additional data fields to include
    """
    data: dict[str, Any] = {**extra}
    if checked is not None:
        data["checked"] = checked
    if filtered is not None:
        data["filtered"] = filtered
    if remaining is not None:
        data["remaining"] = remaining
    trace.emit(
        TraceEvent(event_type=EventType.CONSTRAINT_APPLIED, source=source, data=data)
    )


def emit_features_extracted(
    trace: TraceSink,
    source: str,
    entity_id: str,
    **extra: Any,
) -> None:
    """Emit FEATURES_EXTRACTED event.

    Args:
        trace: Trace sink to emit to
        source: Name of the feature extractor
        entity_id: ID of the entity whose features were extracted
        **extra: Additional data fields to include
    """
    trace.emit(
        TraceEvent(
            event_type=EventType.FEATURES_EXTRACTED,
            source=source,
            data={"entity_id": entity_id, **extra},
        )
    )
