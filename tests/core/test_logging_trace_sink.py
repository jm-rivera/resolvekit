"""Tests for LoggingTraceSink."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from resolvekit.core.api import Resolver
from resolvekit.core.explain import LoggingTraceSink, MemoryTraceSink, NullTraceSink
from resolvekit.core.explain.events import EventType, TraceEvent


def _make_event(
    *,
    event_type: EventType = EventType.CANDIDATES_GENERATED,
    source: str | None = "fts",
    data: dict | None = None,
) -> TraceEvent:
    return TraceEvent(
        event_type=event_type,
        source=source,
        data=data or {"count": 3},
        timestamp=datetime(2026, 4, 24, 12, 0, 0, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# Text format
# ---------------------------------------------------------------------------


def test_logging_sink_text_format(caplog: pytest.LogCaptureFixture) -> None:
    sink = LoggingTraceSink(logger_name="resolvekit.resolution", output_format="text")
    event = _make_event()

    with caplog.at_level(logging.DEBUG, logger="resolvekit.resolution"):
        sink.emit(event)

    assert len(caplog.records) == 1
    msg = caplog.records[0].message
    assert "[fts]" in msg
    assert "candidates_generated" in msg
    assert "count=3" in msg


def test_logging_sink_text_format_no_source(caplog: pytest.LogCaptureFixture) -> None:
    sink = LoggingTraceSink(logger_name="resolvekit.resolution", output_format="text")
    event = _make_event(source=None, data={"candidates": 5})

    with caplog.at_level(logging.DEBUG, logger="resolvekit.resolution"):
        sink.emit(event)

    msg = caplog.records[0].message
    assert "[?]" in msg
    assert "candidates=5" in msg


# ---------------------------------------------------------------------------
# JSON format
# ---------------------------------------------------------------------------


def test_logging_sink_json_format(caplog: pytest.LogCaptureFixture) -> None:
    sink = LoggingTraceSink(logger_name="resolvekit.resolution", output_format="json")
    event = _make_event()

    with caplog.at_level(logging.DEBUG, logger="resolvekit.resolution"):
        sink.emit(event)

    assert len(caplog.records) == 1
    msg = caplog.records[0].message
    parsed = json.loads(msg)
    assert parsed["event_type"] == "candidates_generated"
    assert parsed["source"] == "fts"
    assert parsed["data"] == {"count": 3}
    assert "timestamp" in parsed
    datetime.fromisoformat(parsed["timestamp"])


def test_logging_sink_json_format_null_source(caplog: pytest.LogCaptureFixture) -> None:
    sink = LoggingTraceSink(logger_name="resolvekit.resolution", output_format="json")
    event = _make_event(source=None)

    with caplog.at_level(logging.DEBUG, logger="resolvekit.resolution"):
        sink.emit(event)

    parsed = json.loads(caplog.records[0].message)
    assert parsed["source"] is None


# ---------------------------------------------------------------------------
# Level control
# ---------------------------------------------------------------------------


def test_logging_sink_respects_level(caplog: pytest.LogCaptureFixture) -> None:
    sink = LoggingTraceSink(logger_name="resolvekit.resolution", level=logging.WARNING)
    event = _make_event()

    with caplog.at_level(logging.DEBUG, logger="resolvekit.resolution"):
        sink.emit(event)

    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING


def test_logging_sink_debug_records_not_captured_at_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = LoggingTraceSink(logger_name="resolvekit.resolution", level=logging.DEBUG)
    event = _make_event()

    with caplog.at_level(logging.WARNING, logger="resolvekit.resolution"):
        sink.emit(event)

    assert len(caplog.records) == 0


# ---------------------------------------------------------------------------
# Resolver integration
# ---------------------------------------------------------------------------


def test_resolver_trace_sink_kwarg(
    geo_test_datapack: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Resolver.from_datapacks(trace=LoggingTraceSink()) emits log records."""
    sink = LoggingTraceSink(logger_name="resolvekit.resolution", output_format="text")

    with (
        caplog.at_level(logging.DEBUG, logger="resolvekit.resolution"),
        Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], trace=sink
        ) as resolver,
    ):
        resolver.resolve("United States")

    assert len(caplog.records) > 0


def test_resolver_trace_true_still_uses_memory_sink(geo_test_datapack: Path) -> None:
    """Passing trace=True installs a MemoryTraceSink (backward-compat)."""
    with Resolver.from_datapacks(
        datapack_paths=[geo_test_datapack], trace=True
    ) as resolver:
        runner = resolver._runner
        sink = getattr(runner, "_trace", None)
        assert isinstance(sink, MemoryTraceSink)


def test_resolver_trace_false_uses_null_sink(geo_test_datapack: Path) -> None:
    """Default trace=False installs NullTraceSink."""
    with Resolver.from_datapacks(datapack_paths=[geo_test_datapack]) as resolver:
        runner = resolver._runner
        sink = getattr(runner, "_trace", None)
        assert isinstance(sink, NullTraceSink)
