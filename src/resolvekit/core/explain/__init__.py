"""Trace and explanation system."""

from resolvekit.core.explain.events import EventType, TraceEvent
from resolvekit.core.explain.helpers import (
    emit_candidates_generated,
    emit_constraint_applied,
    emit_features_extracted,
)
from resolvekit.core.explain.protocol import Explainer
from resolvekit.core.explain.renderers import (
    JSONRenderer,
    MarkdownRenderer,
    ScorecardRenderer,
    TextRenderer,
    get_renderer,
)
from resolvekit.core.explain.result_types import ExplainedResolution
from resolvekit.core.explain.scorecard import (
    CandidateScorecard,
    ConstraintSummary,
    PipelineTiming,
    Scorecard,
    ScorecardBuilder,
    SourceContribution,
    Verbosity,
)
from resolvekit.core.explain.sink import (
    LoggingTraceSink,
    MemoryTraceSink,
    NullTraceSink,
    TraceSink,
)

__all__ = [
    "CandidateScorecard",
    "ConstraintSummary",
    "EventType",
    "ExplainedResolution",
    "Explainer",
    "JSONRenderer",
    "LoggingTraceSink",
    "MarkdownRenderer",
    "MemoryTraceSink",
    "NullTraceSink",
    "PipelineTiming",
    "Scorecard",
    "ScorecardBuilder",
    "ScorecardRenderer",
    "SourceContribution",
    "TextRenderer",
    "TraceEvent",
    "TraceSink",
    "Verbosity",
    "emit_candidates_generated",
    "emit_constraint_applied",
    "emit_features_extracted",
    "get_renderer",
]
