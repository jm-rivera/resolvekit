"""Containment constraint for geo entities."""

from resolvekit.core.engine import Constraint
from resolvekit.core.explain import TraceSink, emit_constraint_applied
from resolvekit.core.model import (
    Candidate,
    ConstraintOutcome,
    ConstraintRole,
    Query,
    ResolutionContext,
    Severity,
)
from resolvekit.core.store import EntityStore


class GeoContainmentConstraint(Constraint):
    """Check if candidates are contained within a parent entity.

    Hard constraint: filters candidates not contained in parent_ids.
    """

    def __init__(self, max_depth: int = 3):
        self._max_depth = max_depth

    @property
    def name(self) -> str:
        return "geo_containment_constraint"

    def apply(
        self,
        query: Query,
        context: ResolutionContext,
        candidates: list[Candidate],
        store: EntityStore,
        trace: TraceSink,
    ) -> list[Candidate]:
        parent_ids = self._resolve_parent_ids(context, store)
        if not parent_ids:
            return candidates

        result = []
        filtered_count = 0

        for candidate in candidates:
            # Check if candidate is contained in any parent
            contained, _ = self._check_containment(
                candidate.entity_id, parent_ids, store
            )

            candidate.constraint_outcomes.append(
                ConstraintOutcome(
                    constraint_name=self.name,
                    passed=contained,
                    severity=Severity.HARD,
                    reason=None if contained else "Not contained in specified parent",
                    role=ConstraintRole.CONTAINMENT_SCOPE,
                )
            )

            if contained:
                result.append(candidate)
            else:
                filtered_count += 1

        emit_constraint_applied(
            trace, self.name, filtered=filtered_count, remaining=len(result)
        )

        return result

    def _resolve_parent_ids(
        self, context: ResolutionContext, store: EntityStore
    ) -> set[str]:
        """Resolve effective parent IDs from explicit and country-hint context."""
        parent_ids = set(context.parent_ids or [])

        # Treat country hint as a shorthand containment parent.
        # Example: country="GT" -> add country entity IDs for iso2=gt.
        if context.country:
            iso2 = context.country.strip().lower()
            if iso2:
                parent_ids.update(store.lookup_code("iso2", iso2))

        return parent_ids

    def _check_containment(
        self, entity_id: str, parent_ids: set[str], store: EntityStore
    ) -> tuple[bool, int]:
        """Check if entity is contained in any parent, using BFS."""
        visited: set[str] = set()
        # Queue of (entity_id, depth)
        queue: list[tuple[str, int]] = [(entity_id, 0)]

        while queue:
            current, depth = queue.pop(0)

            if current in visited:
                continue
            visited.add(current)

            if depth >= self._max_depth:
                continue

            parents = store.get_relations(current, "contained_in")

            for parent in parents:
                if parent in parent_ids:
                    return True, depth + 1
                if parent not in visited:
                    queue.append((parent, depth + 1))

        return False, 0
