"""Resolution result models - the stable public contract."""

from __future__ import annotations

import weakref
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from resolvekit.core.model.entity import EntityRecord

if TYPE_CHECKING:
    from resolvekit.core.explain.protocol import Explainer
    from resolvekit.core.explain.scorecard import Scorecard, Verbosity
    from resolvekit.core.model.query import ResolutionContext


class MatchClass(StrEnum):
    """How the candidate was matched during a suggest() call."""

    EXACT_PREFIX = "exact_prefix"
    TOKEN_PREFIX = "token_prefix"
    INFIX = "infix"
    FUZZY = "fuzzy"


class SuggestionResult(BaseModel):
    """A single ranked suggestion returned by ``Resolver.suggest()``.

    Attributes:
        entity_id: The entity identifier.
        canonical_name: The entity's canonical name, or ``None`` when unavailable.
        entity_type: Entity type string (e.g. ``"geo.country"``).
        pack_id: Pack that produced this candidate.
        match_class: How the candidate was found (prefix, infix, fuzzy).
        fuzzy_score: Raw ``partial_ratio`` score 0-100 from RapidFuzz.
            ``None`` unless ``match_class == FUZZY``; not a calibrated probability.
        ranking_quality: Tier-based honesty hint.  ``"ranked"`` when the tier
            has live prominence data (currently ``geo.country``); ``"unranked"``
            otherwise.  A country with no prominence value still reports
            ``"ranked"`` — the hint is tier-based, not per-candidate.
        display: ``to=``-rendered output string; follows ``on_missing="null"``.
        highlight_ranges: Unicode **code-point** offsets (NOT UTF-16),
            end-exclusive, into ``display``; JS/browser callers must convert.
            Empty list when no reliable span is available (e.g. fuzzy matches).
    """

    model_config = ConfigDict(frozen=True)

    entity_id: str
    canonical_name: str | None = None
    entity_type: str | None = None
    pack_id: str | None = None
    match_class: MatchClass
    fuzzy_score: float | None = None
    ranking_quality: Literal["ranked", "unranked"]
    display: str | None = None
    highlight_ranges: list[tuple[int, int]] = Field(default_factory=list)


class ResolutionStatus(StrEnum):
    """Explicit resolution status - never None."""

    RESOLVED = "resolved"  # Single entity matched with high confidence
    AMBIGUOUS = "ambiguous"  # Multiple plausible matches
    NO_MATCH = "no_match"  # No candidates found or all below threshold
    ERROR = "error"  # Internal error during resolution


class MatchTier(StrEnum):
    """Quality tier for a match or near-match."""

    EXACT_CODE = "exact_code"
    EXACT_NAME = "exact_name"
    ACRONYM = "acronym"
    FTS = "fts"
    FUZZY = "fuzzy"
    FALLBACK = "fallback"


class RefinementHint(StrEnum):
    """Which ResolutionContext field would most improve the next attempt."""

    ENTITY_TYPES = "entity_types"
    PARENT_IDS = "parent_ids"
    COUNTRY = "country"
    LANGUAGES = "languages"
    DID_YOU_MEAN = "did_you_mean"


# DID_YOU_MEAN is intentionally last: its multi-line output is a fallback,
# not the default when the pipeline supplies multiple hints simultaneously.
_REFINEMENT_HINT_PRIORITY: tuple[RefinementHint, ...] = (
    RefinementHint.ENTITY_TYPES,
    RefinementHint.COUNTRY,
    RefinementHint.PARENT_IDS,
    RefinementHint.LANGUAGES,
    RefinementHint.DID_YOU_MEAN,
)


class ReasonCode(StrEnum):
    """Stable reason codes for monitoring and debugging.

    These codes explain WHY a particular status was returned.
    They're invaluable for debugging and monitoring resolution quality.

    Note: ``ResolutionResult.reasons`` is currently always a single-element
    list. Callers should treat the field as ``[reason]`` and avoid logic that
    assumes multiple codes per result; this invariant may relax in a future
    minor version, with notice.
    """

    # Match reasons
    EXACT_CODE_MATCH = "exact_code_match"
    EXACT_NAME_MATCH = "exact_name_match"
    ACRONYM_MATCH = "acronym_match"
    FTS_MATCH = "fts_match"
    FUZZY_MATCH = "fuzzy_match"
    PARENT_CONTEXT_TIEBREAK = "parent_context_tiebreak"

    # No match reasons
    NO_CANDIDATES = "no_candidates"
    FILTERED_BY_CONSTRAINT = "filtered_by_constraint"
    BELOW_CONFIDENCE_THRESHOLD = "below_confidence_threshold"

    # Ambiguous reasons
    AMBIGUOUS_LOW_GAP = "ambiguous_low_gap"
    AMBIGUOUS_MULTIPLE_EXACT = "ambiguous_multiple_exact"
    ACRONYM_MATCH_AMBIGUOUS = "acronym_match_ambiguous"
    AMBIGUOUS_DOMAIN_COLLISION = "ambiguous_domain_collision"
    AMBIGUOUS_SIBLING_ENTITIES = "ambiguous_sibling_entities"

    # Tiebreak reasons (emitted by Resolver, not by pack decision policies)
    # GROUP_PREFERENCE_TIEBREAK: emitted when an AMBIGUOUS result is promoted to
    # RESOLVED because exactly one of the top-2 candidates is a pack-declared group type.
    GROUP_PREFERENCE_TIEBREAK = "group_preference_tiebreak"

    # HIERARCHY_PREFERENCE_TIEBREAK: emitted when a near-tie is broken because the
    # top candidate strictly outranks every close runner-up in the geo hierarchy
    # (e.g. a continent winning over a same-named sub-continental region).
    HIERARCHY_PREFERENCE_TIEBREAK = "hierarchy_preference_tiebreak"

    # Error reasons
    STORE_ERROR = "store_error"
    MODEL_MISSING_FALLBACK_USED = "model_missing_fallback_used"
    INTERNAL_ERROR = "internal_error"
    TIMEOUT = "timeout"

    # Context-related
    CONTEXT_PARENT_NOT_FOUND = "context_parent_not_found"
    CONTEXT_TYPE_MISMATCH = "context_type_mismatch"
    CONTEXT_PARENT_CONFLICT = "context_parent_conflict"
    CONTEXT_COUNTRY_CONFLICT = "context_country_conflict"
    INVALID_QUERY = "invalid_query"
    INVALID_INPUT_TYPE = "invalid_input_type"
    SENTINEL_BLOCKED = "sentinel_blocked"


class CandidateEvidenceSummary(BaseModel):
    """Minimal evidence summary for public results.

    A safe subset of CandidateEvidence for user-facing results.
    """

    model_config = ConfigDict(frozen=True)

    source_name: str = Field(..., min_length=1)
    matched_field: str | None = Field(default=None)
    matched_value: str | None = Field(default=None)


class CandidateSummary(BaseModel):
    """Summary of a candidate for public results.

    Contains only the information safe and useful to return to callers.
    Bounded in size to prevent result bloat.

    Attributes:
        entity_id: The entity ID
        confidence: Calibrated confidence score
        top_evidence: Key evidence (limited to top 3)
        key_features: Selected features for transparency (limited set)
    """

    model_config = ConfigDict(frozen=True)

    entity_id: str = Field(..., min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    canonical_name: str | None = Field(default=None)
    entity_type: str | None = Field(default=None)
    pack_id: str | None = Field(default=None)
    match_tier: MatchTier | None = Field(default=None)
    top_evidence: list[CandidateEvidenceSummary] = Field(
        default_factory=list, max_length=3
    )
    key_features: dict[str, float | bool | None] = Field(default_factory=dict)

    def __repr__(self) -> str:  # explicit by design
        conf = f"{self.confidence:.2f}" if self.confidence is not None else "?"
        ev = len(self.top_evidence)
        pack = f" [{self.pack_id}]" if self.pack_id else ""
        ev_str = f" ({ev} evidence)" if ev else ""
        return f"CandidateSummary({self.entity_id!r}, conf={conf}{pack}{ev_str})"


class Trace(BaseModel):
    """Optional detailed trace for debugging.

    Only populated when trace_level is FULL.
    Contains step-by-step events from the pipeline.
    """

    model_config = ConfigDict(frozen=True)

    events: list[dict[str, Any]] = Field(default_factory=list)
    timing_ms: dict[str, float] = Field(default_factory=dict)


class ResolutionResult(BaseModel):
    """The stable public contract for resolution results.

    CRITICAL: status is NEVER None. Every resolution returns an explicit status.

    Attributes:
        status: RESOLVED, AMBIGUOUS, NO_MATCH, or ERROR
        entity_id: The resolved entity ID (only if RESOLVED)
        entity: Full entity record (optional, only if requested)
        confidence: Calibrated confidence (only if RESOLVED)
        candidates: Top-k candidate summaries (bounded)
        reasons: Reason codes explaining the result
        trace: Detailed trace (only if requested)
    """

    model_config = ConfigDict(frozen=True)

    status: ResolutionStatus = Field(..., description="Explicit status, never None")
    entity_id: str | None = Field(default=None)
    entity: EntityRecord | None = Field(default=None)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    pack_id: str | None = Field(default=None)
    match_tier: MatchTier | None = Field(default=None)
    candidates: list[CandidateSummary] = Field(default_factory=list, max_length=10)
    reasons: list[ReasonCode] = Field(default_factory=list)
    refinement_hints: list[RefinementHint] = Field(default_factory=list, max_length=4)
    query_text: str | None = Field(default=None)
    trace: Trace | None = Field(default=None)

    # Weakref back to the Explainer (Resolver) that produced this result.
    # Set by Resolver._resolve_inner post-finalize; None on detached results
    # (deserialized from JSON, constructed in tests, etc.).
    # Typed as Explainer (protocol) so model/ has no import from api/.
    _explainer: weakref.ref[Explainer] | None = PrivateAttr(default=None)

    # Original call options stored so explain() can reproduce the exact resolution.
    # None means "not set" (default options were used).
    _resolve_domain: str | list[str] | None = PrivateAttr(default=None)
    _resolve_context: ResolutionContext | None = PrivateAttr(default=None)

    # ------------------------------------------------------------------
    # Pickle support — drop the unpicklable weakref on serialization
    # ------------------------------------------------------------------

    def __getstate__(self) -> dict[str, Any]:
        state = super().__getstate__()
        # Null out the _explainer weakref; weakrefs are never valid cross-process.
        # The unpickled result will use the existing graceful path in explain()
        # (raises ExplainNotAvailableError when ref is None).
        priv = state.get("__pydantic_private__")
        if priv is not None and priv.get("_explainer") is not None:
            state = dict(state)
            state["__pydantic_private__"] = {**priv, "_explainer": None}
        return state

    # ------------------------------------------------------------------
    # Proxy properties — delegate to self.entity when present
    # ------------------------------------------------------------------

    @property
    def iso2(self) -> str | None:
        """ISO 3166-1 alpha-2 code, proxied from ``entity``.

        Returns None when ``entity`` is not populated (``include_entity=False``).
        """
        return self.entity.iso2 if self.entity is not None else None

    @property
    def iso3(self) -> str | None:
        """ISO 3166-1 alpha-3 code, proxied from ``entity``.

        Returns None when ``entity`` is not populated (``include_entity=False``).
        """
        return self.entity.iso3 if self.entity is not None else None

    @property
    def name(self) -> str | None:
        """Canonical name, proxied from ``entity``.

        Returns None when ``entity`` is not populated (``include_entity=False``).
        """
        return self.entity.canonical_name if self.entity is not None else None

    @property
    def flag(self) -> str | None:
        """Flag emoji, proxied from ``entity``.

        Returns None when ``entity`` is not populated (``include_entity=False``).
        """
        return self.entity.flag if self.entity is not None else None

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict (delegates to ``model_dump()``)."""
        return self.model_dump()

    def to_json(self, *, indent: int | None = None) -> str:
        """Return a JSON string representation.

        Args:
            indent: JSON indentation level; ``None`` for compact output.
        """
        return self.model_dump_json(indent=indent)

    # ------------------------------------------------------------------
    # Explain back-ref
    # ------------------------------------------------------------------

    def explain(
        self,
        *,
        verbosity: Literal["minimal", "standard", "full"] | Verbosity = "standard",
    ) -> Scorecard:
        """Re-run the pipeline with full tracing and return a Scorecard.

        Re-executes the resolution for ``self.query_text`` via the stored
        ``_explainer`` weakref.  Useful for diagnosing why a particular result
        was returned without repeating the original call.

        Note:
            Re-execution cost: this calls back into the resolver and runs the
            full pipeline with a ``MemoryTraceSink``.  Cached ``resolve()``
            calls stay cheap; ``explain()`` pays the tracing cost only when
            invoked.

        Args:
            verbosity: Scorecard detail level.  Accepts the ``Verbosity`` enum
                or its string equivalents ``"minimal"``, ``"standard"``,
                ``"full"``.  Defaults to ``"standard"``.

        Returns:
            A :class:`~resolvekit.core.explain.scorecard.Scorecard` describing
            how the pipeline arrived at this result.

        Raises:
            ExplainNotAvailableError: When the result is detached (no live
                resolver back-ref).  Construct via a live resolver to obtain
                an explainable result.
        """
        from resolvekit.core.errors_base import ExplainNotAvailableError
        from resolvekit.core.explain.scorecard import Verbosity as _Verbosity

        ref = self._explainer
        if ref is None:
            raise ExplainNotAvailableError()
        resolver = ref()
        if resolver is None:
            raise ExplainNotAvailableError()

        query_text = self.query_text or ""
        if not query_text:
            raise ExplainNotAvailableError(
                hint="query_text is empty; result was not produced by a text resolution"
            )

        if isinstance(verbosity, str):
            verbosity = _Verbosity(verbosity)

        explained = resolver.resolve_explained(
            query_text,
            domain=self._resolve_domain,
            context=self._resolve_context,
            verbosity=verbosity,
        )
        return explained.scorecard

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    @property
    def is_resolved(self) -> bool:
        """True if the resolution succeeded with a single entity."""
        return self.status == ResolutionStatus.RESOLVED

    @property
    def is_ambiguous(self) -> bool:
        """True if multiple plausible entities matched."""
        return self.status == ResolutionStatus.AMBIGUOUS

    @property
    def best_candidate(self) -> CandidateSummary | None:
        """Return the highest-confidence candidate, or None."""
        return self.candidates[0] if self.candidates else None

    def top_candidates(self, n: int = 3) -> list[CandidateSummary]:
        """Return the top *n* candidates by confidence."""
        return self.candidates[:n]

    def _render_refinement_hint(self, hint: RefinementHint) -> str | None:
        """Delegate to explain.result_html.render_refinement_hint."""
        from resolvekit.core.explain.result_html import render_refinement_hint

        return render_refinement_hint(self, hint)

    def _did_you_mean_lines(self) -> str | None:
        """Delegate to explain.result_html.did_you_mean_lines."""
        from resolvekit.core.explain.result_html import did_you_mean_lines

        return did_you_mean_lines(self)

    def _refinement_hint(self) -> str | None:
        """Delegate to explain.result_html.refinement_hint."""
        from resolvekit.core.explain.result_html import refinement_hint

        return refinement_hint(self)

    def _disambiguate_hint(self) -> str | None:
        """Delegate to explain.result_html.disambiguate_hint."""
        from resolvekit.core.explain.result_html import disambiguate_hint

        return disambiguate_hint(self)

    def _repr_html_(self) -> str:
        """Rich HTML rendering for Jupyter notebooks — delegates to explain.result_html."""
        from resolvekit.core.explain.result_html import result_repr_html

        return result_repr_html(self)

    def __repr__(self) -> str:  # explicit by design
        from resolvekit.core.explain.result_html import (
            disambiguate_hint,
            refinement_hint,
        )

        s = self.status.value
        if self.status == ResolutionStatus.RESOLVED:
            return (
                f"ResolutionResult(status='{s}', entity_id='{self.entity_id}', "
                f"confidence={self.confidence}, pack_id='{self.pack_id}')"
            )
        if self.status == ResolutionStatus.AMBIGUOUS:
            hint = disambiguate_hint(self)
            if hint is not None:
                return f"AMBIGUOUS — try:\n  {hint}"
            n = len(self.candidates)
            return (
                f"ResolutionResult(status='{s}', candidates={n}, "
                f"hint='use .candidates or resolve_id() to surface ambiguity')"
            )
        if self.status == ResolutionStatus.NO_MATCH:
            hint = refinement_hint(self)
            if hint is not None:
                return f"NO_MATCH — try:\n  {hint}"
            return (
                f"ResolutionResult(status='{s}', "
                f"reasons={[r.value for r in self.reasons]})"
            )
        return f"ResolutionResult(status='{s}')"


class ResolutionResultList(list):
    """List of ResolutionResult with Jupyter-friendly display."""

    def __repr__(self) -> str:  # explicit by design
        n = len(self)
        resolved = sum(1 for r in self if r.status == ResolutionStatus.RESOLVED)
        return f"ResolutionResultList({n} results, {resolved} resolved)"

    def _repr_html_(self) -> str:  # explicit by design
        """Rich HTML rendering for Jupyter notebooks — delegates to explain.result_html."""
        from resolvekit.core.explain.result_html import result_list_repr_html

        return result_list_repr_html(self)

    @property
    def resolved(self) -> ResolutionResultList:
        return ResolutionResultList(
            r for r in self if r.status == ResolutionStatus.RESOLVED
        )

    @property
    def entity_ids(self) -> list[str | None]:
        return [r.entity_id for r in self]

    @property
    def statuses(self) -> list[ResolutionStatus]:
        return [r.status for r in self]
