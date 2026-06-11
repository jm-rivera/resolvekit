"""Membership constraint for geo entities."""

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


class GeoMembershipConstraint(Constraint):
    """Check membership relations for geo entities.

    Soft constraint: marks candidates with membership info.
    Useful for entities like EU member states.
    """

    @property
    def name(self) -> str:
        return "geo_membership_constraint"

    def apply(
        self,
        query: Query,
        context: ResolutionContext,
        candidates: list[Candidate],
        store: EntityStore,
        trace: TraceSink,
    ) -> list[Candidate]:
        # Only apply if context has membership hints
        if not context.attributes.get("membership_org"):
            return candidates

        membership_org = context.attributes["membership_org"]

        for candidate in candidates:
            if context.as_of is not None:
                relations = store.get_relations_as_of(
                    candidate.entity_id, "member_of", context.as_of
                )
            else:
                relations = store.get_relations(candidate.entity_id, "member_of")
            is_member = membership_org in relations

            candidate.constraint_outcomes.append(
                ConstraintOutcome(
                    constraint_name=self.name,
                    passed=is_member,
                    severity=Severity.SOFT,
                    reason=None if is_member else f"Not a member of {membership_org}",
                    role=ConstraintRole.MEMBERSHIP_SCOPE,
                )
            )

        emit_constraint_applied(trace, self.name, checked=len(candidates))

        return candidates
