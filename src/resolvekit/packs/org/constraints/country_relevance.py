"""Country relevance soft constraint for org entities."""

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


class CountryRelevanceConstraint(Constraint):
    """Soft constraint boosting orgs matching hint country.

    Unlike GeoPack containment (hard), org country relevance is
    a soft signal - orgs can operate globally.

    Example: Searching "Red Cross" with country_hint="CH" should
    boost "ICRC" but not exclude "American Red Cross".
    """

    @property
    def name(self) -> str:
        return "org_country_relevance"

    def apply(
        self,
        query: Query,
        context: ResolutionContext,
        candidates: list[Candidate],
        store: EntityStore,
        trace: TraceSink,
    ) -> list[Candidate]:
        if not context.country:
            return candidates

        hint_countries = {context.country.upper()}
        entity_ids = [c.entity_id for c in candidates]
        entities = store.bulk_get_entities(entity_ids)

        for candidate in candidates:
            entity = entities.get(candidate.entity_id)

            matched = False
            if entity:
                country_value = entity.attributes.get("country_code")
                if country_value:
                    org_countries = {str(country_value).upper()}
                    matched = bool(org_countries & hint_countries)

            candidate.constraint_outcomes.append(
                ConstraintOutcome(
                    constraint_name=self.name,
                    passed=matched,
                    severity=Severity.SOFT,
                    reason=None if matched else "Country mismatch",
                    role=ConstraintRole.COUNTRY_SCOPE,
                )
            )

        emit_constraint_applied(
            trace,
            self.name,
            checked=len(candidates),
            hint_countries=list(hint_countries),
        )

        return candidates  # Soft constraint - never filters
