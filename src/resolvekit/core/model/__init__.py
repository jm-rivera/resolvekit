"""Core model types for ResolveKit.

This module exports all the core data types used throughout the system.
Import from here rather than from individual modules.
"""

from resolvekit.core.model.bulk_result import BulkResult, ResolutionSummary
from resolvekit.core.model.candidate import (
    Candidate,
    CandidateEvidence,
    ConstraintOutcome,
    ConstraintRole,
    FeatureVector,
    RetrievalSummary,
    ScoreSummary,
    Severity,
)
from resolvekit.core.model.crosswalk import IGNORE, Crosswalk
from resolvekit.core.model.entity import (
    CodeRecord,
    EntityRecord,
    NameRecord,
    RelationRecord,
)
from resolvekit.core.model.features import FeaturesV1
from resolvekit.core.model.generation import GenerationContext
from resolvekit.core.model.inspection import InspectionReport, InspectMatch
from resolvekit.core.model.query import (
    NormalizedText,
    Query,
    ResolutionContext,
)
from resolvekit.core.model.result import (
    CandidateEvidenceSummary,
    CandidateSummary,
    MatchClass,
    MatchTier,
    ReasonCode,
    RefinementHint,
    ResolutionResult,
    ResolutionResultList,
    ResolutionStatus,
    SuggestionResult,
    Trace,
)

__all__ = [
    "IGNORE",
    "BulkResult",
    "Candidate",
    "CandidateEvidence",
    "CandidateEvidenceSummary",
    "CandidateSummary",
    "CodeRecord",
    "ConstraintOutcome",
    "ConstraintRole",
    "Crosswalk",
    "EntityRecord",
    "FeatureVector",
    "FeaturesV1",
    "GenerationContext",
    "InspectMatch",
    "InspectionReport",
    "MatchClass",
    "MatchTier",
    "NameRecord",
    "NormalizedText",
    "Query",
    "ReasonCode",
    "RefinementHint",
    "RelationRecord",
    "ResolutionContext",
    "ResolutionResult",
    "ResolutionResultList",
    "ResolutionStatus",
    "ResolutionSummary",
    "RetrievalSummary",
    "ScoreSummary",
    "Severity",
    "SuggestionResult",
    "Trace",
]
