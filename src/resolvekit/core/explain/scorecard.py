"""Scorecard data models and builder for explainability.

This module provides human-readable explanation capabilities for resolution results.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from resolvekit.core.explain.events import EventType
from resolvekit.core.explain.feature_text import describe_features
from resolvekit.core.model import (
    Candidate,
    CandidateSummary,
    MatchTier,
    Query,
    ReasonCode,
    RefinementHint,
    ResolutionResult,
    ResolutionStatus,
)

if TYPE_CHECKING:
    from resolvekit.core.explain.events import TraceEvent


class Verbosity(StrEnum):
    """Verbosity levels for scorecard output."""

    MINIMAL = "minimal"  # Status + entity_id + confidence
    STANDARD = "standard"  # + sources, features, alternatives
    FULL = "full"  # + trace events, timing

    @classmethod
    def coerce(cls, value: Verbosity | str) -> Verbosity:
        """Coerce a string or Verbosity to a Verbosity member.

        Args:
            value: A :class:`Verbosity` instance or a case-insensitive string
                (``"minimal"``, ``"standard"``, ``"full"``).

        Returns:
            The corresponding :class:`Verbosity` member.

        Raises:
            ValueError: If the string does not match any member.
        """
        if isinstance(value, cls):
            return value
        try:
            return cls(value.lower())
        except ValueError:
            valid = ", ".join(f'"{v}"' for v in cls)
            raise ValueError(
                f"Invalid verbosity {value!r}; expected one of {valid}"
            ) from None


class SourceContribution(BaseModel):
    """How a source contributed to a candidate match.

    Attributes:
        name: Source name (e.g., "geo_exact_name", "fts")
        matched_field: Field that matched (e.g., "name.canonical")
        matched_value: The value that was matched (e.g., the FTS query term or alias)
        score: Source-specific score
        signals: Additional signals from this source
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., min_length=1)
    matched_field: str | None = Field(default=None)
    matched_value: str | None = Field(default=None)
    score: float | None = Field(default=None)
    signals: dict[str, float] = Field(default_factory=dict)


class ConstraintSummary(BaseModel):
    """Summary of a constraint check.

    Attributes:
        name: Constraint name
        passed: Whether constraint passed
        severity: "hard" or "soft"
        reason: Explanation if failed
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., min_length=1)
    passed: bool | None = Field(default=None)
    severity: str = Field(default="soft")
    reason: str | None = Field(default=None)


class CandidateScorecard(BaseModel):
    """Per-candidate breakdown in the scorecard.

    Attributes:
        entity_id: Entity identifier
        confidence: Calibrated confidence score (0-1)
        rank: Ranking position (1-based)
        sources: How each source contributed
        constraints: Constraint check results
        key_features: Selected informative features
        evidence_text: Short human-readable strings explaining why this
            candidate matched (e.g. "matched canonical name exactly").
            At most 6 entries, ordered by informativeness.
    """

    model_config = ConfigDict(frozen=True)

    entity_id: str = Field(..., min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    rank: int = Field(..., ge=1)
    sources: list[SourceContribution] = Field(default_factory=list)
    constraints: list[ConstraintSummary] = Field(default_factory=list)
    key_features: dict[str, Any] = Field(default_factory=dict)
    evidence_text: list[str] = Field(default_factory=list, max_length=6)


class PipelineTiming(BaseModel):
    """Timing breakdown for pipeline stages.

    Attributes:
        generation_ms: Candidate generation time
        constraints_ms: Constraint application time
        features_ms: Feature extraction time
        scoring_ms: Scoring time
        decision_ms: Decision making time
        total_ms: Total pipeline time
    """

    model_config = ConfigDict(frozen=True)

    generation_ms: float | None = Field(default=None, ge=0.0)
    constraints_ms: float | None = Field(default=None, ge=0.0)
    features_ms: float | None = Field(default=None, ge=0.0)
    scoring_ms: float | None = Field(default=None, ge=0.0)
    decision_ms: float | None = Field(default=None, ge=0.0)
    total_ms: float | None = Field(default=None, ge=0.0)


class Scorecard(BaseModel):
    """Top-level scorecard for a resolution result.

    Provides a structured explanation of how resolution proceeded
    at different verbosity levels.

    Attributes:
        query_text: Original query text
        normalized_text: Normalized query text
        status: Resolution status
        entity_id: Resolved entity (if any)
        confidence: Confidence score (if resolved)
        reasons: Reason codes explaining the result
        primary_source: Best source for the match
        winner: Detailed scorecard for winning candidate
        alternatives: Scorecards for alternative candidates
        trace_events: Raw trace events (FULL verbosity only)
        timing: Pipeline timing breakdown (FULL verbosity only)
        pack_id: Domain pack that handled the query
    """

    model_config = ConfigDict(frozen=True)

    query_text: str = Field(...)
    normalized_text: str = Field(...)
    status: ResolutionStatus = Field(...)
    entity_id: str | None = Field(default=None)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    match_tier: MatchTier | None = Field(default=None)
    reasons: list[ReasonCode] = Field(default_factory=list)
    refinement_hints: list[RefinementHint] = Field(default_factory=list)
    primary_source: str | None = Field(default=None)
    winner: CandidateScorecard | None = Field(default=None)
    alternatives: list[CandidateScorecard] = Field(default_factory=list)
    trace_events: list[dict[str, Any]] = Field(default_factory=list)
    timing: PipelineTiming | None = Field(default=None)
    pack_id: str | None = Field(default=None)

    def as_text(self) -> str:
        """Render the scorecard as plain text."""
        from resolvekit.core.explain import get_renderer

        return get_renderer("text").render(self)

    def as_markdown(self) -> str:
        """Render the scorecard as Markdown."""
        from resolvekit.core.explain import get_renderer

        return get_renderer("markdown").render(self)

    def as_json(self) -> str:
        """Render the scorecard as JSON."""
        from resolvekit.core.explain import get_renderer

        return get_renderer("json").render(self)

    def _repr_html_(self) -> str:
        """Rich HTML rendering for Jupyter notebooks.

        All user-supplied strings (``query_text``, ``normalized_text``,
        ``entity_id``, ``primary_source``) are HTML-escaped before
        interpolation.  Wrapped in a per-instance ``rk-scorecard-N``
        container with scoped CSS, matching the other ``_repr_html_``
        renderers.
        """
        from resolvekit.core.explain.result_html import (
            status_badge_html as _status_badge_html,
        )
        from resolvekit.core.model._repr import escape, scoped_table

        badge = _status_badge_html(self.status)
        rows = [
            f"<tr><th>Query</th><td>{escape(self.query_text)}</td></tr>",
            f"<tr><th>Normalized</th><td>{escape(self.normalized_text)}</td></tr>",
            f"<tr><th>Status</th><td>{badge}</td></tr>",
        ]
        if self.entity_id:
            rows.append(
                f"<tr><th>Entity</th><td><code>{escape(self.entity_id)}</code></td></tr>"
            )
        if self.confidence is not None:
            rows.append(f"<tr><th>Confidence</th><td>{self.confidence:.3f}</td></tr>")
        if self.primary_source:
            rows.append(
                f"<tr><th>Source</th><td>{escape(self.primary_source)}</td></tr>"
            )
        rows_html = "\n".join(rows)
        return scoped_table(
            prefix="rk-scorecard", rows_html=rows_html, css_class="rk-scorecard"
        )

    def __repr__(self) -> str:
        parts: list[str] = [f"Scorecard(status='{self.status.value}'"]
        if self.entity_id:
            parts.append(f"entity_id='{self.entity_id}'")
        if self.confidence is not None:
            parts.append(f"confidence={self.confidence}")
        if self.pack_id:
            parts.append(f"pack_id='{self.pack_id}'")
        return ", ".join(parts) + ")"


class ScorecardBuilder:
    """Builds scorecards from resolution results.

    Extracts relevant information based on verbosity level.
    """

    def __init__(
        self,
        verbosity: Verbosity | str = Verbosity.STANDARD,
        max_alternatives: int = 5,
        max_features: int = 8,
    ) -> None:
        """Initialize the builder.

        Args:
            verbosity: Detail level for output — a :class:`Verbosity` member or
                a case-insensitive string (``"minimal"``, ``"standard"``, ``"full"``).
            max_alternatives: Maximum alternative candidates to include
            max_features: Maximum features to include per candidate
        """
        self._verbosity = Verbosity.coerce(verbosity)
        self._max_alternatives = max_alternatives
        self._max_features = max_features

    def build(
        self,
        query: Query,
        result: ResolutionResult,
        trace_events: list[TraceEvent] | None = None,
        candidates: list[Candidate] | None = None,
        pack_id: str | None = None,
    ) -> Scorecard:
        """Build a scorecard from resolution result.

        Args:
            query: The original query
            result: The resolution result
            trace_events: Optional trace events for FULL verbosity
            candidates: Optional full candidate list for detailed breakdown
            pack_id: Optional domain pack identifier

        Returns:
            Scorecard with appropriate detail level
        """
        winner = None
        alternatives: list[CandidateScorecard] = []
        primary_source = None
        timing = None
        events_data: list[dict[str, Any]] = []

        winner_candidate: Candidate | None = None
        if result.status == ResolutionStatus.RESOLVED and result.entity_id:
            winner_candidate = self._find_candidate(candidates, result.entity_id)
            winner = self._build_winner_scorecard(result, candidates, winner_candidate)
            primary_source = self._derive_primary_source(winner_candidate, winner)

        if self._verbosity in (Verbosity.STANDARD, Verbosity.FULL):
            alternatives = self._build_alternatives(result, candidates)

        if self._verbosity == Verbosity.FULL:
            if trace_events:
                events_data = [
                    {
                        "event_type": str(e.event_type),
                        "source": e.source,
                        "data": e.data,
                        "timestamp": e.timestamp.isoformat(),
                    }
                    for e in trace_events
                ]
            timing = self._extract_timing(trace_events)

        return Scorecard(
            query_text=query.raw_text,
            normalized_text=query.normalized.normalized,
            status=result.status,
            entity_id=result.entity_id,
            confidence=result.confidence,
            match_tier=result.match_tier,
            reasons=list(result.reasons),
            refinement_hints=list(result.refinement_hints),
            primary_source=primary_source,
            winner=winner,
            alternatives=alternatives,
            trace_events=events_data,
            timing=timing,
            pack_id=pack_id or result.pack_id,
        )

    def _build_winner_scorecard(
        self,
        result: ResolutionResult,
        candidates: list[Candidate] | None,
        full_candidate: Candidate | None = None,
    ) -> CandidateScorecard | None:
        """Build scorecard for the winning candidate."""
        if not result.entity_id:
            return None

        if full_candidate is None:
            full_candidate = self._find_candidate(candidates, result.entity_id)
        summary = self._find_summary(result.candidates, result.entity_id)
        sources, constraints, key_features, evidence_text = (
            self._extract_candidate_details(full_candidate, summary)
        )

        return CandidateScorecard(
            entity_id=result.entity_id,
            confidence=result.confidence,
            rank=1,
            sources=sources,
            constraints=constraints,
            key_features=key_features,
            evidence_text=evidence_text,
        )

    def _build_alternatives(
        self,
        result: ResolutionResult,
        candidates: list[Candidate] | None,
    ) -> list[CandidateScorecard]:
        """Build scorecards for alternative candidates."""
        candidate_lookup = {c.entity_id: c for c in (candidates or [])}
        alternatives: list[CandidateScorecard] = []

        for rank, summary in enumerate(result.candidates, start=1):
            if summary.entity_id == result.entity_id:
                continue
            if len(alternatives) >= self._max_alternatives:
                break

            full_candidate = candidate_lookup.get(summary.entity_id)
            sources, constraints, key_features, evidence_text = (
                self._extract_candidate_details(full_candidate, summary)
            )

            alternatives.append(
                CandidateScorecard(
                    entity_id=summary.entity_id,
                    confidence=summary.confidence,
                    rank=rank,
                    sources=sources,
                    constraints=constraints,
                    key_features=key_features,
                    evidence_text=evidence_text,
                )
            )

        return alternatives

    def _derive_primary_source(
        self,
        full_candidate: Candidate | None,
        winner: CandidateScorecard | None,
    ) -> str | None:
        """Derive primary source from best retrieval or winner's first source."""
        if full_candidate and full_candidate.retrieval:
            return full_candidate.retrieval.best_source
        if winner and winner.sources:
            return winner.sources[0].name
        return None

    def _find_candidate(
        self, candidates: list[Candidate] | None, entity_id: str
    ) -> Candidate | None:
        """Find a candidate by entity_id."""
        if not candidates:
            return None
        return next((c for c in candidates if c.entity_id == entity_id), None)

    def _find_summary(
        self, summaries: Sequence[CandidateSummary] | None, entity_id: str
    ) -> CandidateSummary | None:
        """Find a candidate summary by entity_id."""
        if not summaries:
            return None
        return next((s for s in summaries if s.entity_id == entity_id), None)

    def _extract_candidate_details(
        self,
        full_candidate: Candidate | None,
        summary: CandidateSummary | None,
    ) -> tuple[
        list[SourceContribution], list[ConstraintSummary], dict[str, Any], list[str]
    ]:
        """Extract source contributions, constraints, features, and evidence text.

        Prefers full candidate data when available, falls back to summary.

        Returns:
            4-tuple of (sources, constraints, key_features, evidence_text).
        """
        if full_candidate:
            sources = [
                SourceContribution(
                    name=ev.source_name,
                    matched_field=ev.matched_field,
                    matched_value=ev.matched_value,
                    score=ev.raw_score,
                    signals=dict(ev.signals),
                )
                for ev in full_candidate.sources
            ]
            constraints = [
                ConstraintSummary(
                    name=co.constraint_name,
                    passed=co.passed,
                    severity=str(co.severity),
                    reason=co.reason,
                )
                for co in full_candidate.constraint_outcomes
            ]
            features_dict = (
                full_candidate.features.to_dict() if full_candidate.features else {}
            )
            key_features = self._extract_key_features(features_dict)
            evidence_text = describe_features(features_dict)
            return sources, constraints, key_features, evidence_text

        if summary:
            sources = [
                SourceContribution(
                    name=ev.source_name,
                    matched_field=ev.matched_field,
                    matched_value=ev.matched_value,
                )
                for ev in summary.top_evidence
            ]
            features_dict = dict(summary.key_features)
            key_features = self._extract_key_features(features_dict)
            evidence_text = describe_features(features_dict)
            return sources, [], key_features, evidence_text

        return [], [], {}, []

    def _extract_key_features(self, features: dict[str, Any]) -> dict[str, Any]:
        """Extract the most informative features.

        Prioritizes:
        - Boolean features that are True
        - High-magnitude floats
        - Non-None values
        """
        if not features:
            return {}

        def informativeness_score(value: Any) -> float:
            if isinstance(value, bool):
                return 10.0 if value else 1.0
            if isinstance(value, int | float):
                return abs(float(value)) + 0.5
            return 0.1

        # Filter, score, and sort features by informativeness
        scored = [
            (key, value, informativeness_score(value))
            for key, value in features.items()
            if key != "schema_version" and value is not None
        ]
        scored.sort(key=lambda x: x[2], reverse=True)

        return {key: value for key, value, _ in scored[: self._max_features]}

    def _extract_timing(
        self, trace_events: list[TraceEvent] | None
    ) -> PipelineTiming | None:
        """Extract timing information from trace events.

        Calculates time spans between event types to build a timing breakdown.
        """
        if not trace_events or len(trace_events) < 2:
            return None

        sorted_events = sorted(trace_events, key=lambda e: e.timestamp)
        first_ts = sorted_events[0].timestamp
        last_ts = sorted_events[-1].timestamp
        total_ms = max(0.0, (last_ts - first_ts).total_seconds() * 1000)

        # Track phase boundaries: phase -> (first_ts, last_ts)
        phases: dict[str, list[datetime]] = {
            "generation": [],
            "constraint": [],
            "features": [],
            "scoring": [],
            "decision": [],
        }

        # Map event types to phases (generation events only track end time)
        event_to_phase = {
            EventType.CANDIDATES_GENERATED: "generation",
            EventType.CANDIDATES_MERGED: "generation",
            EventType.CONSTRAINT_APPLIED: "constraint",
            EventType.FEATURES_EXTRACTED: "features",
            EventType.SCORED: "scoring",
            EventType.DECIDED: "decision",
        }

        for event in sorted_events:
            if phase := event_to_phase.get(event.event_type):
                phases[phase].append(event.timestamp)

        def phase_duration_ms(phase_name: str) -> float | None:
            timestamps = phases[phase_name]
            if len(timestamps) < 2:
                return None
            return max(0.0, (timestamps[-1] - timestamps[0]).total_seconds() * 1000)

        # Generation is special: measured from pipeline start to last generation event
        generation_ms = None
        if phases["generation"]:
            generation_ms = max(
                0.0, (phases["generation"][-1] - first_ts).total_seconds() * 1000
            )

        # Decision is special: measured from end of last phase to decision.
        # Events from concurrent sources can interleave, so clamp to 0 to avoid
        # tiny negative values from defeating PipelineTiming's ge=0 validators.
        decision_ms = None
        if phases["decision"]:
            ref_ts = (
                phases["scoring"][-1:]
                or phases["features"][-1:]
                or phases["constraint"][-1:]
                or phases["generation"][-1:]
            )
            if ref_ts:
                decision_ms = max(
                    0.0, (phases["decision"][0] - ref_ts[0]).total_seconds() * 1000
                )

        return PipelineTiming(
            generation_ms=generation_ms,
            constraints_ms=phase_duration_ms("constraint"),
            features_ms=phase_duration_ms("features"),
            scoring_ms=phase_duration_ms("scoring"),
            decision_ms=decision_ms,
            total_ms=total_ms,
        )
