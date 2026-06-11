"""Parent organization constraint."""

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


class ParentOrgConstraint(Constraint):
    """Boost/filter by parent organization context.

    Soft constraint: boosts candidates matching parent org.
    Hard mode: filters candidates not under specified parent.
    """

    def __init__(self, hard_filter: bool = False):
        self._hard = hard_filter

    @property
    def name(self) -> str:
        return "org_parent_constraint"

    def apply(
        self,
        query: Query,
        context: ResolutionContext,
        candidates: list[Candidate],
        store: EntityStore,
        trace: TraceSink,
    ) -> list[Candidate]:
        if not context.parent_ids:
            return candidates

        parent_ids = set(context.parent_ids)
        result = []
        filtered_count = 0

        for candidate in candidates:
            relations = store.get_relations(candidate.entity_id, "subsidiary_of")
            relations.extend(store.get_relations(candidate.entity_id, "member_of"))

            matched = bool(set(relations) & parent_ids)

            candidate.constraint_outcomes.append(
                ConstraintOutcome(
                    constraint_name=self.name,
                    passed=matched,
                    severity=Severity.HARD if self._hard else Severity.SOFT,
                    reason=None if matched else "Parent org mismatch",
                    role=ConstraintRole.PARENT_SCOPE,
                )
            )

            if not self._hard or matched:
                result.append(candidate)
            else:
                filtered_count += 1

        emit_constraint_applied(
            trace, self.name, filtered=filtered_count, remaining=len(result)
        )

        return result
