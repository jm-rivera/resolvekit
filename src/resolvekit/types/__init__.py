"""resolvekit.types — stable public type exports.

Enumerations and named types that users need to annotate their own code or
pass as arguments.  Import from here rather than from internal paths.

Example::

    from resolvekit.types import ResolutionStatus, RoutingMode, BulkResult
"""

from resolvekit.core.api.cache import CacheInfo
from resolvekit.core.api.info import ResolverInfo
from resolvekit.core.api.modules import ModuleInfo
from resolvekit.core.engine.router import RoutingMode
from resolvekit.core.explain.scorecard import Scorecard, Verbosity
from resolvekit.core.explain.sink import LoggingTraceSink
from resolvekit.core.model import EntityRecord, ResolutionContext, ResolutionResult
from resolvekit.core.model.bulk_result import BulkResult
from resolvekit.core.model.inspection import InspectionReport, InspectMatch
from resolvekit.core.model.result import (
    CandidateSummary,
    MatchTier,
    ReasonCode,
    RefinementHint,
    ResolutionStatus,
)
from resolvekit.core.store.sqlite import SQLiteTuning

__all__ = [
    "BulkResult",
    "CacheInfo",
    "CandidateSummary",
    "EntityRecord",
    "InspectMatch",
    "InspectionReport",
    "LoggingTraceSink",
    "MatchTier",
    "ModuleInfo",
    "ReasonCode",
    "RefinementHint",
    "ResolutionContext",
    "ResolutionResult",
    "ResolutionStatus",
    "ResolverInfo",
    "RoutingMode",
    "SQLiteTuning",
    "Scorecard",
    "Verbosity",
]
