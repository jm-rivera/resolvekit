"""Core interfaces for pipeline components.

These interfaces define the extension points for the resolution engine.
Domain packs implement these to provide domain-specific behavior.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import (
    TYPE_CHECKING,
    Literal,
    Protocol,
    TypeVar,
    runtime_checkable,
)

from resolvekit.core.explain import TraceSink
from resolvekit.core.model import (
    Candidate,
    CandidateEvidence,
    EntityRecord,
    FeatureVector,
    GenerationContext,
    MatchTier,
    Query,
    ReasonCode,
    ResolutionContext,
    ResolutionResult,
    ResolutionStatus,
    RetrievalSummary,
)
from resolvekit.core.store import EntityStore

if TYPE_CHECKING:
    from resolvekit.core.engine.suggest_rank import SuggestCandidate

TFeatures = TypeVar("TFeatures", bound=FeatureVector)


@dataclass
class PipelineResult:
    """Result from pipeline execution, including candidates.

    Attributes:
        result: The resolution result
        candidates: Full candidate list with all details
        pack_id: Domain pack ID that produced this result (for multi-pack resolution)
    """

    result: ResolutionResult
    candidates: list[Candidate] | None = None
    pack_id: str | None = None


_TIMEOUT_RESULT = ResolutionResult(
    status=ResolutionStatus.ERROR,
    reasons=(ReasonCode.TIMEOUT,),
)


@dataclass(frozen=True)
class ConfidenceBand:
    """Per-pack metadata declaring what score ranges mean for cross-pack normalization."""

    high_confidence_floor: float  # Score above which pack is "highly confident"
    medium_confidence_floor: float  # Score above which pack has "medium confidence"
    low_confidence_floor: float  # Score above which pack has "low confidence"


@dataclass(frozen=True)
class DecisionThresholds:
    """Thresholds for the decision policy, declared by the scorer.

    ML scorers and calibrators produce output on a different scale than
    heuristics. These thresholds tell the decision policy how to interpret
    the scorer's output.
    """

    confidence_threshold: float = 0.7
    min_gap: float = 0.1
    exact_code_min_score: float = 0.9


@runtime_checkable
class ScoringModel(Protocol):
    """Protocol for ML scoring models."""

    def predict(self, features: FeatureVector) -> float:
        """Return a score for the given features."""
        ...

    @property
    def model_version(self) -> str:
        """Return model version string for traceability."""
        ...


@runtime_checkable
class ResolverBackend(Protocol):
    """Public runner contract consumed by the Resolver facade."""

    def resolve(
        self,
        query: Query,
        context: ResolutionContext,
        *,
        trace_sink: TraceSink | None = None,
        deadline: float | None = None,
    ) -> ResolutionResult:
        """Resolve a query and return the final resolution result."""
        ...

    def resolve_detailed(
        self,
        query: Query,
        context: ResolutionContext,
        *,
        trace_sink: TraceSink | None = None,
        deadline: float | None = None,
    ) -> PipelineResult:
        """Resolve a query and return full pipeline data including candidates."""
        ...

    def close(self) -> None:
        """Release resources held by the backend."""
        ...

    def get_entity(self, entity_id: str) -> EntityRecord | None:
        """Look up a fully hydrated entity by ID."""
        ...

    def lookup_code(
        self,
        system: str,
        value_norm: str,
        *,
        pack_filter: frozenset[str] | None = None,
    ) -> list[str]:
        """Look up entity IDs by code system and normalized value."""
        ...

    @property
    def available_packs(self) -> frozenset[str]:
        """Return the set of valid pack identifiers for explicit routing."""
        ...

    @property
    def available_entity_types(self) -> frozenset[str]:
        """Return all entity types declared across loaded packs."""
        ...

    @property
    def available_code_systems(self) -> frozenset[str]:
        """Return all code systems available across loaded stores."""
        ...

    @property
    def available_group_types(self) -> frozenset[str]:
        """Return all group entity types declared across loaded packs."""
        ...

    def get_reverse_relations(
        self,
        *,
        entity_id: str,
        relation_type: str,
        as_of: date | None = None,
    ) -> list[str]:
        """Return entity IDs that have a relation of relation_type pointing to entity_id."""
        ...

    def get_relations_as_of(
        self,
        *,
        entity_id: str,
        relation_type: str,
        as_of: date,
    ) -> frozenset[str]:
        """Return the set of target entity IDs for a relation as of a given date."""
        ...

    def list_entities_by_type(
        self,
        *,
        entity_type: str,
    ) -> list[EntityRecord]:
        """Return all entities with the given entity_type across loaded stores."""
        ...

    def get_pack_group_types(
        self,
        *,
        pack_id: str,
    ) -> frozenset[str]:
        """Return the group entity types declared by the given pack."""
        ...

    def is_snapshot_entity(
        self,
        *,
        entity_id: str,
    ) -> bool:
        """Return True if the entity is a snapshot (time-bounded membership) entity."""
        ...

    def lookup_pack_id(self) -> str | None:
        """Return the single pack ID for single-pack backends; None for multi-pack."""
        ...

    def lookup_name_exact(
        self,
        *,
        value: str,
        pack_filter: frozenset[str] | None = None,
    ) -> list[tuple[str, str]]:
        """Return (pack_id, entity_id) pairs matching the given name exactly."""
        ...

    def lookup_code_attributed(
        self,
        *,
        system: str,
        value_norm: str,
        pack_filter: frozenset[str] | None = None,
    ) -> list[tuple[str, str]]:
        """Return (pack_id, entity_id) pairs matching the code in the given system."""
        ...

    def normalize_code_value(
        self, system: str, value: str, *, pack_filter: frozenset[str] | None = None
    ) -> str:
        """Normalize *value* for *system* using the owning pack's code normalizer.

        Routes to the normalizer of the first in-scope pack that declares *system*
        in its ``available_code_systems``.  Falls back to
        ``BaseNormalizer().normalize_code`` when no pack owns the system.

        Args:
            system: Code system name (e.g., ``"iso3"``, ``"duns"``).
            value: Raw query value.
            pack_filter: When set, restrict the search to those pack IDs.

        Returns:
            Normalized code value ready for a single ``lookup_code`` call.
        """
        ...

    def store_for_domain(self, domain: str) -> EntityStore:
        """Return the EntityStore for the given domain.

        Raises:
            ValueError: If no store is found for the given domain.
        """
        ...

    def suggest_prefix(
        self,
        *,
        query_norm: str,
        top_k: int,
        entity_type_prefixes: frozenset[str] | None = None,
        fuzzy: Literal["auto", "always", "never"] = "auto",
        deadline: float | None = None,
        pack_filter: frozenset[str] | None = None,
    ) -> list[SuggestCandidate]:
        """Return a ranked list of suggest candidates for a normalized prefix query.

        Implementations should union exact-prefix, token-infix, and (when
        permitted) fuzzy candidates, deduplicate by entity_id, and return at
        most ``top_k`` results sorted by ``suggest_rank.sort_key``.

        Args:
            query_norm: Normalized query prefix.
            top_k: Maximum number of candidates to return.
            entity_type_prefixes: When set, restrict candidates to entity types
                that start with one of these prefixes.
            fuzzy: ``"auto"`` runs fuzzy only on small non-denylisted tiers;
                ``"always"`` forces fuzzy regardless; ``"never"`` skips fuzzy.
            deadline: Absolute ``time.monotonic()`` deadline.  When exceeded
                before the fuzzy phase, return partial results rather than
                raising.
            pack_filter: When set, restrict to these pack IDs.  Single-pack
                runners accept the parameter for interface parity but ignore it
                (they own exactly one pack).  Multi-pack runners skip packs
                whose ID is not in the filter.

        Returns:
            Sorted ``list[SuggestCandidate]``, at most ``top_k`` entries.
        """
        return []


class CandidateSource(ABC):
    """Interface for candidate generators.

    Each source produces candidate evidence entries. The engine handles
    merging evidence into Candidate objects.

    Implementations:
    - ExactCodeSource: Look up by code (ISO, DCID, etc.)
    - ExactNameSource: Exact name match
    - FTSSource: Full-text search
    - FuzzySource: Fuzzy/edit-distance matching
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this source (e.g., 'exact_code', 'fts')."""
        ...

    @property
    def reason_code(self) -> ReasonCode:
        """ReasonCode to use when this source provides the best match.

        Override this property to specify a custom reason code.
        Default is FTS_MATCH for generic sources.
        """
        return ReasonCode.FTS_MATCH

    @property
    def tier(self) -> MatchTier | None:
        """The tier this source's evidence defaults to; used for source-level skip/routing
        decisions before the source runs.

        Override to declare the tier. Defaults to None (tier derived from reason_code).
        """
        return None

    @abstractmethod
    def supports(self, domain_pack_id: str) -> bool:
        """Check if this source supports the given domain pack."""
        ...

    @property
    def requires_existing_candidates(self) -> bool:
        """Whether this source needs existing candidates (e.g., fuzzy rerankers)."""
        return False

    @abstractmethod
    def generate(self, ctx: GenerationContext) -> list[CandidateEvidence]:
        """Generate candidate evidence.

        Args:
            ctx: Generation context containing query, store, budget, trace, etc.

        Returns:
            List of evidence entries (one per matched entity)
        """
        ...


class Constraint(ABC):
    """Interface for constraints (hard filters and soft enrichers).

    Constraints can:
    - Filter out candidates (hard constraint)
    - Add constraint features (soft signal)

    Each candidate gets a ConstraintOutcome appended.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this constraint."""
        ...

    @abstractmethod
    def apply(
        self,
        query: Query,
        context: ResolutionContext,
        candidates: list[Candidate],
        store: EntityStore,
        trace: TraceSink,
    ) -> list[Candidate]:
        """Apply constraint to candidates.

        May filter candidates (return fewer) or just add outcomes.

        Args:
            query: The resolution query
            context: Resolution context
            candidates: Candidates to check
            store: Entity data store
            trace: Trace sink

        Returns:
            Filtered/updated candidates
        """
        ...


class FeatureExtractor(ABC):
    """Interface for feature extraction.

    Domain packs own feature extraction. The extractor produces
    a typed FeatureVector that matches the pack's schema version.
    """

    @property
    @abstractmethod
    def schema_version(self) -> str:
        """Feature schema version this extractor produces."""
        ...

    @abstractmethod
    def extract(
        self,
        query: Query,
        context: ResolutionContext,
        candidate: Candidate,
        store: EntityStore,
        trace: TraceSink,
    ) -> FeatureVector:
        """Extract features for a candidate.

        Args:
            query: The resolution query
            context: Resolution context
            candidate: Candidate to extract features for
            store: Entity data store
            trace: Trace sink

        Returns:
            Typed feature vector matching schema_version
        """
        ...


class Scorer(ABC):
    """Interface for scoring and calibration.

    Scorers convert feature vectors into calibrated confidence scores.
    """

    @abstractmethod
    def score(self, features: FeatureVector, retrieval: RetrievalSummary) -> float:
        """Compute raw score from features.

        Args:
            features: Feature vector from extractor
            retrieval: Retrieval summary with source signals

        Returns:
            Raw score (unbounded, will be calibrated)
        """
        ...

    @abstractmethod
    def calibrate(self, raw_score: float, query: Query, candidate: Candidate) -> float:
        """Calibrate raw score to probability.

        Args:
            raw_score: Score from score()
            query: The query
            candidate: The candidate

        Returns:
            Calibrated probability (0-1)
        """
        ...

    def fallback_score(
        self, features: FeatureVector, retrieval: RetrievalSummary
    ) -> float:
        """Fallback scoring when model is unavailable.

        Default implementation calls score(). Override for custom fallback logic.

        Args:
            features: Feature vector
            retrieval: Retrieval summary

        Returns:
            Fallback score (0-1)
        """
        return self.score(features, retrieval)

    @property
    def scorer_type(self) -> str:
        """Return 'heuristic' or 'model' for trace metadata."""
        return "heuristic"

    @property
    def confidence_band(self) -> ConfidenceBand | None:
        """Optional: declare confidence bands for cross-pack normalization."""
        return None

    @property
    def decision_thresholds(self) -> DecisionThresholds:
        """Thresholds appropriate for this scorer's output distribution.

        Decision policies should use these rather than hardcoded constants,
        since ML models and calibrators produce scores on a different scale
        than heuristic scorers.
        """
        return DecisionThresholds()


class DecisionPolicy(ABC):
    """Interface for final decision making.

    Decides the resolution status using calibrated scores,
    constraints, and domain-specific rules.
    """

    @abstractmethod
    def decide(
        self,
        query: Query,
        context: ResolutionContext,
        candidates: list[Candidate],
        trace: TraceSink,
    ) -> ResolutionResult:
        """Make final resolution decision.

        Args:
            query: The resolution query
            context: Resolution context
            candidates: Scored candidates (sorted by confidence)
            trace: Trace sink

        Returns:
            Final ResolutionResult
        """
        ...
