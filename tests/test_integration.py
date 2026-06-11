"""Integration tests for resolution."""

from resolvekit.core.engine import PipelineRunner
from resolvekit.core.engine.decision import ThresholdDecisionPolicy
from resolvekit.core.explain.events import EventType
from resolvekit.core.model import (
    ReasonCode,
    ResolutionStatus,
)
from resolvekit.packs.geo import GeoExactCodeSource
from tests.conftest import make_query

_DEFAULT_POLICY = ThresholdDecisionPolicy(
    confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
)


class TestEndToEndResolution:
    """End-to-end integration tests."""

    def test_resolve_usa_by_iso2_code(self, usa_store, memory_trace, empty_context):
        """Test resolving 'US' returns United States."""
        runner = PipelineRunner(
            trace_sink=memory_trace,
            store=usa_store,
            sources=[GeoExactCodeSource()],
            decision_policy=_DEFAULT_POLICY,
        )

        query = make_query("US")
        result = runner.resolve(query, empty_context)

        # Assertions
        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "country/USA"
        assert result.confidence is not None
        assert result.confidence >= 0.8

        # Check trace recorded events
        events = memory_trace.get_events()
        assert any(e.source == "geo_exact_code" for e in events)

    def test_resolve_no_match_returns_explicit_status(
        self, empty_store, null_trace, empty_context
    ):
        """Test that unknown queries return NO_MATCH, not None."""
        runner = PipelineRunner(
            trace_sink=null_trace,
            store=empty_store,
            sources=[GeoExactCodeSource()],
            decision_policy=_DEFAULT_POLICY,
        )

        query = make_query("ZZZZZ")
        result = runner.resolve(query, empty_context)

        # CRITICAL: status is NEVER None
        assert result.status is not None
        assert result.status == ResolutionStatus.NO_MATCH
        assert ReasonCode.NO_CANDIDATES in result.reasons

    def test_trace_shows_sources_that_ran(
        self, empty_store, memory_trace, empty_context
    ):
        """Acceptance criteria: trace shows which sources ran."""
        runner = PipelineRunner(
            trace_sink=memory_trace,
            store=empty_store,
            sources=[GeoExactCodeSource()],
            decision_policy=_DEFAULT_POLICY,
        )

        query = make_query("FR")
        runner.resolve(query, empty_context)

        # Check trace shows the source ran
        events = memory_trace.get_events()
        source_events = [
            e for e in events if e.event_type == EventType.CANDIDATES_GENERATED
        ]
        assert len(source_events) >= 1
        assert any(e.source == "geo_exact_code" for e in source_events)
