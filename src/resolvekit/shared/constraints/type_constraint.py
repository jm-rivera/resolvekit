"""Shared type constraint implementation.

Filters candidates by entity type matching context.entity_types.
This is a HARD constraint - non-matching candidates are removed.
"""

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


class TypeConstraint(Constraint):
    """Filter candidates by entity type.

    Hard constraint: removes candidates whose entity_type is not in entity_types.
    If entity_types is empty, all candidates pass.

    When a compatibility map is supplied, each requested type is expanded to
    include the stored types listed for it.  Only the mapped types are widened;
    types absent from the map remain strict.  This lets packs express semantic
    equivalences (e.g. geo.city → geo.admin1…5) without globally softening the
    filter for types that must stay strict (e.g. geo.country).
    """

    def __init__(
        self,
        name: str,
        *,
        role: ConstraintRole | None = None,
        compatibility: dict[str, frozenset[str]] | None = None,
    ):
        """Create a type constraint.

        Args:
            name: Unique name for this constraint (e.g., "org_type_constraint")
            role: Semantic role to stamp on emitted ConstraintOutcome records.
            compatibility: Optional map from a requested entity_type to the set
                of stored entity_types that are considered compatible with it.
                Types not present in the map are matched strictly.  Defaults to
                None (pure strict matching for all types).
        """
        self._name = name
        self._role = role
        self._compatibility: dict[str, frozenset[str]] = compatibility or {}

    @property
    def name(self) -> str:
        return self._name

    def apply(
        self,
        query: Query,
        context: ResolutionContext,
        candidates: list[Candidate],
        store: EntityStore,
        trace: TraceSink,
    ) -> list[Candidate]:
        if not context.entity_types:
            return candidates

        # Expand each requested type with its compatible stored types.
        acceptable: set[str] = set(context.entity_types)
        for t in context.entity_types:
            acceptable |= self._compatibility.get(t, frozenset())

        entity_ids = [c.entity_id for c in candidates]
        entities = store.bulk_get_entities(entity_ids)

        result = []
        filtered_count = 0

        for candidate in candidates:
            entity = entities.get(candidate.entity_id)
            if not entity:
                # Can't verify - keep but mark as unknown
                candidate.constraint_outcomes.append(
                    ConstraintOutcome(
                        constraint_name=self.name,
                        passed=None,
                        severity=Severity.HARD,
                        reason="Entity not found",
                        role=self._role,
                    )
                )
                result.append(candidate)
                continue

            passed = entity.entity_type in acceptable

            candidate.constraint_outcomes.append(
                ConstraintOutcome(
                    constraint_name=self.name,
                    passed=passed,
                    severity=Severity.HARD,
                    reason=(
                        None
                        if passed
                        else f"Type {entity.entity_type} not in {context.entity_types}"
                    ),
                    role=self._role,
                )
            )

            if passed:
                result.append(candidate)
            else:
                filtered_count += 1

        emit_constraint_applied(
            trace, self.name, filtered=filtered_count, remaining=len(result)
        )

        return result


def type_constraint(
    name: str,
    *,
    role: ConstraintRole | None = None,
    compatibility: dict[str, frozenset[str]] | None = None,
) -> Constraint:
    """Create a type constraint with the given name.

    This is a convenience factory for creating TypeConstraint instances.

    Args:
        name: Unique name for the constraint
        role: Semantic role to stamp on emitted ConstraintOutcome records.
        compatibility: Optional map from requested entity_type to the set of
            stored entity_types considered compatible (see TypeConstraint).

    Returns:
        Configured TypeConstraint instance
    """
    return TypeConstraint(name, role=role, compatibility=compatibility)
