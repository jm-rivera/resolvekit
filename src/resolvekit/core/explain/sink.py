"""Trace sinks for collecting events."""

import json
import logging
import threading
from abc import ABC, abstractmethod
from typing import Literal

from resolvekit.core.explain.events import TraceEvent


class TraceSink(ABC):
    """Abstract interface for trace event collectors.

    Implementations determine what happens with emitted events:
    - MemoryTraceSink: Collect in memory for later retrieval
    - NullTraceSink: Discard events (for production when tracing disabled)
    - LoggingTraceSink: Write one log record per event via Python logging

    Only emit() is abstract - all sinks must accept events. The retrieval
    methods have default implementations since not all sinks store events
    (e.g., NullTraceSink discards them, LoggingTraceSink writes them out).
    """

    @abstractmethod
    def emit(self, event: TraceEvent) -> None:
        """Emit a trace event."""
        ...

    def get_events(self) -> list[TraceEvent]:
        """Get all collected events.

        Default returns empty list. Override in sinks that store events.
        """
        return []

    def clear(self) -> None:  # noqa: B027
        """Clear collected events.

        Default is no-op. Override in sinks that store events.
        """


class MemoryTraceSink(TraceSink):
    """In-memory trace sink for debugging and testing."""

    def __init__(self) -> None:
        self._events: list[TraceEvent] = []
        self._lock = threading.Lock()

    def emit(self, event: TraceEvent) -> None:
        with self._lock:
            self._events.append(event)

    def get_events(self) -> list[TraceEvent]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


class NullTraceSink(TraceSink):
    """Null sink that discards all events.

    Use in production when tracing is disabled to avoid memory overhead.
    """

    def emit(self, event: TraceEvent) -> None:
        pass  # Discard

    def get_events(self) -> list[TraceEvent]:
        return []

    def clear(self) -> None:
        pass


class LoggingTraceSink(TraceSink):
    """Trace sink that writes one log record per TraceEvent.

    Args:
        logger_name: Name of the Python logger to write to.
            Defaults to ``"resolvekit.resolution"``.
        level: Log level for emitted records (e.g., ``logging.DEBUG``).
            Defaults to ``logging.DEBUG``.
        output_format: Output format. ``"text"`` produces a short human-readable
            line; ``"json"`` produces a single JSON line with all fields.
            Defaults to ``"text"``.
    """

    def __init__(
        self,
        *,
        logger_name: str = "resolvekit.resolution",
        level: int = logging.DEBUG,
        output_format: Literal["text", "json"] = "text",
    ) -> None:
        self._logger = logging.getLogger(logger_name)
        self._level = level
        self._format = output_format

    def emit(self, event: TraceEvent) -> None:
        if self._format == "json":
            message = json.dumps(
                {
                    "event_type": str(event.event_type),
                    "source": event.source,
                    "data": event.data,
                    "timestamp": event.timestamp.isoformat(),
                },
                default=str,
            )
        else:
            kv = " ".join(f"{k}={v}" for k, v in event.data.items())
            source = event.source or "?"
            message = f"[{source}] {event.event_type} {kv}".rstrip()
        self._logger.log(self._level, message)
