"""Scorecard renderers for different output formats.

This module provides renderers to convert Scorecard objects into
human-readable text, markdown, or JSON formats.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from resolvekit.core.model import ResolutionStatus

if TYPE_CHECKING:
    from resolvekit.core.explain.scorecard import CandidateScorecard, Scorecard


class ScorecardRenderer(ABC):
    """Abstract base for scorecard renderers."""

    @abstractmethod
    def render(self, scorecard: Scorecard) -> str:
        """Render a scorecard to string output.

        Args:
            scorecard: The scorecard to render

        Returns:
            Formatted string representation
        """
        ...


class TextRenderer(ScorecardRenderer):
    """Plain text renderer for terminal/logging output."""

    def render(self, scorecard: Scorecard) -> str:
        """Render scorecard as plain text."""
        lines: list[str] = []

        # Header
        lines.append("Resolution Scorecard")
        lines.append("=" * 60)

        # Query info
        lines.append(f'Query: "{scorecard.query_text}"')
        if scorecard.normalized_text != scorecard.query_text:
            lines.append(f'Normalized: "{scorecard.normalized_text}"')

        # Status
        lines.append(f"Status: {scorecard.status.value.upper()}")

        # Result info (if resolved)
        self._render_resolved_info(scorecard, lines)

        # Pack ID if available
        if scorecard.pack_id:
            lines.append(f"Pack: {scorecard.pack_id}")
        if scorecard.match_tier:
            lines.append(f"Match Tier: {scorecard.match_tier.value}")
        if scorecard.refinement_hints:
            hints = ", ".join(hint.value for hint in scorecard.refinement_hints)
            lines.append(f"Refinement Hints: {hints}")

        # Winner details
        if scorecard.winner:
            lines.append("")
            lines.append("Match Details:")
            lines.append("-" * 40)
            self._render_candidate_details(scorecard.winner, lines, indent=2)

        # Alternatives
        self._render_alternatives(scorecard, lines)

        # Trace events (FULL verbosity)
        self._render_trace_events(scorecard, lines)

        # Timing (FULL verbosity)
        self._render_timing(scorecard, lines)

        return "\n".join(lines)

    def _render_resolved_info(self, scorecard: Scorecard, lines: list[str]) -> None:
        """Render info for resolved status."""
        if scorecard.status != ResolutionStatus.RESOLVED:
            return
        lines.append(f"Entity: {scorecard.entity_id}")
        if scorecard.confidence is not None:
            lines.append(f"Confidence: {scorecard.confidence * 100:.1f}%")
        if scorecard.reasons:
            lines.append(f"Reasons: {', '.join(str(r) for r in scorecard.reasons)}")

    def _render_alternatives(self, scorecard: Scorecard, lines: list[str]) -> None:
        """Render alternatives section."""
        if not scorecard.alternatives:
            return
        lines.append("")
        lines.append(f"Alternatives ({len(scorecard.alternatives)}):")
        lines.append("-" * 40)
        for alt in scorecard.alternatives:
            conf_str = (
                f" (confidence: {alt.confidence * 100:.1f}%)"
                if alt.confidence is not None
                else ""
            )
            lines.append(f"  {alt.rank}. {alt.entity_id}{conf_str}")

    def _render_trace_events(self, scorecard: Scorecard, lines: list[str]) -> None:
        """Render trace events section."""
        if not scorecard.trace_events:
            return
        lines.append("")
        lines.append(f"Trace Events ({len(scorecard.trace_events)}):")
        lines.append("-" * 40)
        for event in scorecard.trace_events:
            source_str = f" [{event.get('source')}]" if event.get("source") else ""
            lines.append(f"  - {event.get('event_type')}{source_str}")

    def _render_timing(self, scorecard: Scorecard, lines: list[str]) -> None:
        """Render timing section."""
        if not scorecard.timing or scorecard.timing.total_ms is None:
            return
        lines.append("")
        lines.append("Timing:")
        lines.append("-" * 40)
        timing = scorecard.timing
        if timing.generation_ms is not None:
            lines.append(f"  Generation: {timing.generation_ms:.2f}ms")
        if timing.constraints_ms is not None:
            lines.append(f"  Constraints: {timing.constraints_ms:.2f}ms")
        if timing.features_ms is not None:
            lines.append(f"  Features: {timing.features_ms:.2f}ms")
        if timing.scoring_ms is not None:
            lines.append(f"  Scoring: {timing.scoring_ms:.2f}ms")
        if timing.decision_ms is not None:
            lines.append(f"  Decision: {timing.decision_ms:.2f}ms")
        lines.append(f"  Total: {timing.total_ms:.2f}ms")

    def _render_candidate_details(
        self, candidate: CandidateScorecard, lines: list[str], indent: int = 0
    ) -> None:
        """Render detailed candidate information."""
        prefix = " " * indent

        # Primary source
        if candidate.sources:
            lines.append(f"{prefix}Primary Source: {candidate.sources[0].name}")

        # All sources
        if candidate.sources:
            lines.append(f"{prefix}Sources:")
            for src in candidate.sources:
                field_str = f" on {src.matched_field}" if src.matched_field else ""
                score_str = (
                    f" (score: {src.score:.3f})" if src.score is not None else ""
                )
                lines.append(f"{prefix}  - {src.name}{field_str}{score_str}")
                if src.matched_value:
                    lines.append(f'{prefix}    matched "{src.matched_value}"')

        # Key features
        if candidate.key_features:
            lines.append(f"{prefix}Key Features:")
            for key, value in candidate.key_features.items():
                if isinstance(value, bool):
                    display_value = "Yes" if value else "No"
                elif isinstance(value, float):
                    display_value = f"{value:.3f}"
                else:
                    display_value = str(value)
                lines.append(f"{prefix}  {key}: {display_value}")

        # Evidence text
        if candidate.evidence_text:
            lines.append(f"{prefix}Why this match:")
            for evidence in candidate.evidence_text:
                lines.append(f"{prefix}  - {evidence}")

        # Constraints
        if candidate.constraints:
            lines.append(f"{prefix}Constraints:")
            for con in candidate.constraints:
                status = "PASS" if con.passed else "FAIL"
                reason_str = f" - {con.reason}" if con.reason and not con.passed else ""
                lines.append(f"{prefix}  {con.name}: {status}{reason_str}")


class MarkdownRenderer(ScorecardRenderer):
    """Markdown renderer for documentation/reports."""

    def render(self, scorecard: Scorecard) -> str:
        """Render scorecard as Markdown."""
        lines: list[str] = []

        # Header
        lines.append("# Resolution Scorecard")
        lines.append("")

        # Query info
        lines.append(f'**Query:** "{scorecard.query_text}"')
        if scorecard.normalized_text != scorecard.query_text:
            lines.append(f'**Normalized:** "{scorecard.normalized_text}"')
        lines.append("")

        # Status with badge-like formatting
        status_emoji = {
            ResolutionStatus.RESOLVED: ":white_check_mark:",
            ResolutionStatus.AMBIGUOUS: ":warning:",
            ResolutionStatus.NO_MATCH: ":x:",
            ResolutionStatus.ERROR: ":boom:",
        }
        emoji = status_emoji.get(scorecard.status, "")
        lines.append(f"**Status:** {emoji} {scorecard.status.value.upper()}")

        # Result info
        if scorecard.status == ResolutionStatus.RESOLVED:
            lines.append(f"**Entity:** `{scorecard.entity_id}`")
            if scorecard.confidence is not None:
                lines.append(f"**Confidence:** {scorecard.confidence * 100:.1f}%")
            if scorecard.reasons:
                reasons_str = ", ".join(f"`{r}`" for r in scorecard.reasons)
                lines.append(f"**Reasons:** {reasons_str}")

        if scorecard.pack_id:
            lines.append(f"**Pack:** `{scorecard.pack_id}`")
        if scorecard.match_tier:
            lines.append(f"**Match Tier:** `{scorecard.match_tier.value}`")
        if scorecard.refinement_hints:
            hints_str = ", ".join(
                f"`{hint.value}`" for hint in scorecard.refinement_hints
            )
            lines.append(f"**Refinement Hints:** {hints_str}")

        lines.append("")

        # Winner details
        if scorecard.winner:
            lines.append("## Match Details")
            lines.append("")
            self._render_candidate_markdown(scorecard.winner, lines)

        # Alternatives
        if scorecard.alternatives:
            lines.append(f"## Alternatives ({len(scorecard.alternatives)})")
            lines.append("")
            lines.append("| Rank | Entity | Confidence |")
            lines.append("|------|--------|------------|")
            for alt in scorecard.alternatives:
                conf_str = (
                    f"{alt.confidence * 100:.1f}%"
                    if alt.confidence is not None
                    else "-"
                )
                lines.append(f"| {alt.rank} | `{alt.entity_id}` | {conf_str} |")
            lines.append("")

        # Trace events
        if scorecard.trace_events:
            lines.append(f"## Trace Events ({len(scorecard.trace_events)})")
            lines.append("")
            for event in scorecard.trace_events:
                source_str = (
                    f" (`{event.get('source')}`)" if event.get("source") else ""
                )
                lines.append(f"- **{event.get('event_type')}**{source_str}")
            lines.append("")

        return "\n".join(lines)

    def _render_candidate_markdown(
        self, candidate: CandidateScorecard, lines: list[str]
    ) -> None:
        """Render candidate details as Markdown."""
        if candidate.sources:
            lines.append(f"**Primary Source:** `{candidate.sources[0].name}`")
            lines.append("")

        if candidate.sources:
            lines.append("### Sources")
            lines.append("")
            for src in candidate.sources:
                field_str = f" on `{src.matched_field}`" if src.matched_field else ""
                score_str = (
                    f" (score: {src.score:.3f})" if src.score is not None else ""
                )
                value_str = (
                    f' matched "{src.matched_value}"' if src.matched_value else ""
                )
                lines.append(f"- `{src.name}`{field_str}{score_str}{value_str}")
            lines.append("")

        if candidate.key_features:
            lines.append("### Key Features")
            lines.append("")
            lines.append("| Feature | Value |")
            lines.append("|---------|-------|")
            for key, value in candidate.key_features.items():
                if isinstance(value, bool):
                    display_value = ":white_check_mark:" if value else ":x:"
                elif isinstance(value, float):
                    display_value = f"{value:.3f}"
                else:
                    display_value = str(value)
                lines.append(f"| `{key}` | {display_value} |")
            lines.append("")

        if candidate.evidence_text:
            lines.append("### Why this match")
            lines.append("")
            for evidence in candidate.evidence_text:
                lines.append(f"- {evidence}")
            lines.append("")

        if candidate.constraints:
            lines.append("### Constraints")
            lines.append("")
            lines.append("| Constraint | Status | Notes |")
            lines.append("|------------|--------|-------|")
            for con in candidate.constraints:
                status = ":white_check_mark: PASS" if con.passed else ":x: FAIL"
                reason = con.reason or "-"
                lines.append(f"| `{con.name}` | {status} | {reason} |")
            lines.append("")


class JSONRenderer(ScorecardRenderer):
    """JSON renderer for programmatic consumption."""

    def __init__(self, indent: int | None = 2) -> None:
        """Initialize JSON renderer.

        Args:
            indent: JSON indentation (None for compact)
        """
        self._indent = indent

    def render(self, scorecard: Scorecard) -> str:
        """Render scorecard as JSON."""
        data = scorecard.model_dump(mode="json")
        return json.dumps(data, indent=self._indent)


def get_renderer(format: str = "text") -> ScorecardRenderer:
    """Factory function to get a renderer by format name.

    Args:
        format: Output format ("text", "markdown", "json")

    Returns:
        Appropriate renderer instance

    Raises:
        ValueError: If format is unknown
    """
    renderers: dict[str, type[ScorecardRenderer]] = {
        "text": TextRenderer,
        "markdown": MarkdownRenderer,
        "md": MarkdownRenderer,
        "json": JSONRenderer,
    }

    renderer_class = renderers.get(format.lower())
    if renderer_class is None:
        valid = ", ".join(sorted(renderers.keys()))
        raise ValueError(f"Unknown format '{format}'. Valid formats: {valid}")

    return renderer_class()
