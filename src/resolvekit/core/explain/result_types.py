"""Explained-resolution result type.

Canonical home for ``ExplainedResolution``.  ``api/resolver.py`` re-exports it
from here for backward compatibility with existing importers.
"""

from typing import NamedTuple

from resolvekit.core.explain.scorecard import Scorecard
from resolvekit.core.model.result import ResolutionResult


class ExplainedResolution(NamedTuple):
    """Resolution result paired with its explanatory scorecard."""

    result: ResolutionResult
    scorecard: Scorecard

    def __repr__(self) -> str:  # explicit by design
        status = self.result.status.value
        entity = self.result.entity_id or "(no match)"
        conf_str = (
            f", conf={self.result.confidence:.2f}" if self.result.confidence else ""
        )
        alts = len(self.scorecard.alternatives)
        return (
            f"ExplainedResolution(status={status!r}, entity={entity!r}"
            f"{conf_str}, alternatives={alts})"
        )
