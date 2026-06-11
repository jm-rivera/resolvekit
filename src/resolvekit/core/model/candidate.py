"""Candidate and evidence models for resolution pipeline."""

from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from resolvekit.core.model.result import MatchTier


class Severity(StrEnum):
    """Constraint severity levels."""

    HARD = "hard"  # Candidate is filtered out if constraint fails
    SOFT = "soft"  # Constraint failure adds negative signal but doesn't filter


class ConstraintRole(StrEnum):
    """Semantic role of a constraint outcome — replaces constraint_name string checks.

    Engine reads outcome.role instead of outcome.constraint_name so domain knowledge
    stays in the packs, not the engine.
    """

    PARENT_SCOPE = "parent_scope"  # Org parent / geo containment constraint
    COUNTRY_SCOPE = "country_scope"  # Org country-relevance constraint
    TYPE_SCOPE = "type_scope"  # Entity type filter constraint
    TEMPORAL_SCOPE = "temporal_scope"  # Date-range / snapshot constraint
    MEMBERSHIP_SCOPE = "membership_scope"  # Group membership constraint
    CONTAINMENT_SCOPE = "containment_scope"  # Spatial containment constraint


class CandidateEvidence(BaseModel):
    """Evidence from a single candidate source.

    Each source that produces a candidate adds one evidence entry.
    This allows tracking how each source contributed to finding the candidate.

    Attributes:
        entity_id: Entity this evidence belongs to
        source_name: Name of the source (e.g., "exact_code", "fts", "acronym")
        raw_score: Source-native score (if applicable)
        rank: Position in source's result list (1-based, if applicable)
        matched_field: Which field matched (e.g., "code.iso2", "name.canonical")
        matched_value: The value that matched (for trace; not always returned to user)
        signals: Component signals for feature extraction (e.g., fuzzy_edit_sim)
    """

    model_config = ConfigDict(frozen=True)

    entity_id: str = Field(..., min_length=1, description="Resolved entity ID")
    source_name: str = Field(..., min_length=1)
    raw_score: float | None = Field(default=None)
    rank: int | None = Field(default=None, ge=1)
    matched_field: str | None = Field(default=None)
    matched_value: str | None = Field(default=None)
    signals: dict[str, float] = Field(default_factory=dict)
    match_tier: MatchTier | None = Field(
        default=None,
        description=(
            "Authoritative tier of THIS evidence; stamped from the source's reason_code"
            " at emission — set explicitly only for synthetic evidence whose source"
            " isn't a registered CandidateSource."
        ),
    )


class RetrievalSummary(BaseModel):
    """Merged retrieval information across all sources.

    Summarizes the best evidence from all sources that produced this candidate.

    Attributes:
        best_source: Source with strongest evidence
        best_rank: Best rank across all sources (1-based)
        best_raw_score: Best raw score across all sources
        signals: Derived signals for feature extraction (e.g., normalized BM25)
    """

    model_config = ConfigDict(frozen=True)

    best_source: str = Field(..., min_length=1)
    best_rank: int | None = Field(default=None, ge=1)
    best_raw_score: float | None = Field(default=None)
    signals: dict[str, float] = Field(default_factory=dict)


class ConstraintOutcome(BaseModel):
    """Result of applying a constraint to a candidate.

    Attributes:
        constraint_name: Name of the constraint
        passed: Whether the constraint passed (None = not evaluated)
        severity: HARD (filters) or SOFT (signal only)
        reason: Explanation if constraint failed
    """

    model_config = ConfigDict(frozen=True)

    constraint_name: str = Field(..., min_length=1)
    passed: bool | None = Field(default=None)
    severity: Severity = Field(default=Severity.SOFT)
    reason: str | None = Field(default=None)
    role: ConstraintRole | None = Field(
        default=None,
        description=(
            "Semantic role of this constraint — constraints feeding parent/country"
            " checks MUST declare a role so the engine can read outcome.role instead"
            " of outcome.constraint_name."
        ),
    )


class ScoreSummary(BaseModel):
    """Scoring information for a candidate.

    Attributes:
        raw_score: Score from the scorer (pre-calibration)
        calibrated_score: Calibrated probability (0-1)
    """

    model_config = ConfigDict(frozen=True)

    raw_score: float = Field(..., description="Uncalibrated model score (unbounded)")
    calibrated_score: float = Field(..., ge=0.0, le=1.0)


@runtime_checkable
class FeatureVector(Protocol):
    """Protocol for typed feature vectors.

    Domain packs implement concrete feature schemas (e.g., GeoFeaturesV1).
    This is a structural protocol - classes don't need to inherit from it.
    Any class with matching methods automatically satisfies this protocol.

    Note: @runtime_checkable is required because Pydantic uses isinstance()
    checks for field validation when FeatureVector is used as a type hint.
    """

    @property
    def schema_version(self) -> str:
        """Return the schema version string."""
        ...

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization/scoring."""
        ...


class Candidate(BaseModel):
    """A resolution candidate with all associated data.

    Candidates are the unit of work after retrieval. They accumulate
    evidence, features, scores, and constraint outcomes as they flow
    through the pipeline.

    IMPORTANT: Unlike other models, Candidate is MUTABLE (frozen=False).
    This is intentional because candidates are incrementally enriched as
    they flow through the pipeline:
    - sources: New evidence may be added by reranker sources
    - retrieval: Updated when better evidence is found
    - features: Set during feature extraction step
    - scores: Set during scoring step
    - constraint_outcomes: Appended by each constraint

    This mutation pattern is more efficient than creating new immutable
    objects at each step. The runner owns the candidate lifecycle and
    ensures thread-safe access.

    Attributes:
        entity_id: The entity this candidate represents
        sources: Evidence from each source that produced this candidate
        retrieval: Merged retrieval summary
        features: Typed feature vector (domain-specific)
        scores: Raw and calibrated scores
        constraint_outcomes: Results of constraint checks
    """

    model_config = ConfigDict(frozen=False, arbitrary_types_allowed=True)

    entity_id: str = Field(..., min_length=1)
    sources: list[CandidateEvidence] = Field(..., min_length=1)
    retrieval: RetrievalSummary
    features: FeatureVector | None = Field(default=None)
    scores: ScoreSummary
    constraint_outcomes: list[ConstraintOutcome] = Field(default_factory=list)
