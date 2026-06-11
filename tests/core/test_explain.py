"""Tests for the trace/explain system."""


class TestEventTypes:
    """Tests for trace event types."""

    def test_event_type_enum(self):
        from resolvekit.core.explain.events import EventType

        assert EventType.QUERY_NORMALIZED == "query_normalized"
        assert EventType.CANDIDATES_GENERATED == "candidates_generated"
        assert EventType.CANDIDATES_MERGED == "candidates_merged"
        assert EventType.CONSTRAINT_APPLIED == "constraint_applied"
        assert EventType.FEATURES_EXTRACTED == "features_extracted"
        assert EventType.SCORED == "scored"
        assert EventType.DECIDED == "decided"


class TestTraceEvent:
    """Tests for TraceEvent model."""

    def test_create_event(self):
        from resolvekit.core.explain.events import EventType, TraceEvent

        event = TraceEvent(
            event_type=EventType.CANDIDATES_GENERATED,
            source="exact_code",
            data={"count": 1, "entity_ids": ["country/USA"]},
        )
        assert event.event_type == EventType.CANDIDATES_GENERATED
        assert event.source == "exact_code"
        assert event.data["count"] == 1
        assert event.timestamp is not None

    def test_event_has_timestamp(self):
        from datetime import datetime

        from resolvekit.core.explain.events import EventType, TraceEvent

        event = TraceEvent(
            event_type=EventType.QUERY_NORMALIZED,
            data={"normalized": "usa"},
        )
        assert isinstance(event.timestamp, datetime)


class TestTraceSink:
    """Tests for TraceSink interface and implementations."""

    def test_memory_sink_collects_events(self):
        from resolvekit.core.explain.events import EventType, TraceEvent
        from resolvekit.core.explain.sink import MemoryTraceSink

        sink = MemoryTraceSink()

        sink.emit(
            TraceEvent(
                event_type=EventType.QUERY_NORMALIZED,
                data={"normalized": "usa"},
            )
        )
        sink.emit(
            TraceEvent(
                event_type=EventType.CANDIDATES_GENERATED,
                source="exact_code",
                data={"count": 1},
            )
        )

        events = sink.get_events()
        assert len(events) == 2
        assert events[0].event_type == EventType.QUERY_NORMALIZED
        assert events[1].event_type == EventType.CANDIDATES_GENERATED

    def test_null_sink_discards_events(self):
        from resolvekit.core.explain.events import EventType, TraceEvent
        from resolvekit.core.explain.sink import NullTraceSink

        sink = NullTraceSink()
        sink.emit(
            TraceEvent(
                event_type=EventType.QUERY_NORMALIZED,
                data={},
            )
        )
        # No error, events are simply discarded
        assert sink.get_events() == []

    def test_memory_sink_clear(self):
        from resolvekit.core.explain.events import EventType, TraceEvent
        from resolvekit.core.explain.sink import MemoryTraceSink

        sink = MemoryTraceSink()
        sink.emit(TraceEvent(event_type=EventType.QUERY_NORMALIZED, data={}))
        assert len(sink.get_events()) == 1

        sink.clear()
        assert len(sink.get_events()) == 0
