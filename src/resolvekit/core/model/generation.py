"""Generation context for candidate sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resolvekit.core.explain import TraceSink
    from resolvekit.core.model.candidate import Candidate
    from resolvekit.core.model.query import Query, ResolutionContext
    from resolvekit.core.store import EntityStore


@dataclass
class GenerationContext:
    """Bundled context for candidate generation.

    Groups the parameters that are always passed together to
    CandidateSource.generate() methods. This reduces parameter
    passing boilerplate and makes the API easier to extend.

    Attributes:
        query: The resolution query
        context: Resolution context (hints, filters)
        store: Entity data store
        budget: Maximum candidates to return
        trace: Trace sink for events
        existing_candidates: Existing candidates (for rerankers)
        deadline: Absolute monotonic deadline for cooperative cancellation
            (``time.monotonic()`` value); ``None`` means no limit.
    """

    query: Query
    context: ResolutionContext
    store: EntityStore
    budget: int
    trace: TraceSink
    existing_candidates: list[Candidate] = field(default_factory=list)
    deadline: float | None = None

    @property
    def text_norm(self) -> str:
        """Convenience accessor for normalized query text."""
        return self.query.normalized.normalized
