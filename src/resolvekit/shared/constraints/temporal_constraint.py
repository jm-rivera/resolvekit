"""Shared temporal validity constraint implementation.

Checks if candidates are valid as of context.as_of date.
This is a HARD constraint: when context.as_of is set, candidates outside their
[valid_from, valid_until) window are dropped. With no as_of it is a no-op.
"""

from collections.abc import Callable
from datetime import date

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

# Type for message formatter functions
MessageFormatter = Callable[[date, date], str]


def _default_not_yet_valid(as_of: date, valid_from: date) -> str:
    """Default message for entities not yet valid."""
    return f"Entity not valid until {valid_from}"


def _default_no_longer_valid(as_of: date, valid_until: date) -> str:
    """Default message for expired entities."""
    return f"Entity expired on {valid_until}"


class TemporalConstraint(Constraint):
    """Check temporal validity of candidates.

    Hard constraint: when context.as_of is set, candidates outside their
    validity window are dropped from the returned list. Entities are invalid if:
    - as_of < valid_from (not yet valid)
    - as_of >= valid_until (no longer valid)

    Entities with no validity dates are always valid. Candidates whose entity is
    not in the store are kept (mirrors TypeConstraint). With no as_of, all
    candidates pass through unchanged.
    """

    def __init__(
        self,
        name: str,
        format_not_yet_valid: MessageFormatter | None = None,
        format_no_longer_valid: MessageFormatter | None = None,
        role: ConstraintRole | None = None,
    ):
        """Create a temporal constraint.

        Args:
            name: Unique name for this constraint
            format_not_yet_valid: Custom formatter for "not yet valid" messages.
                Receives (as_of, valid_from) dates. Default: "Entity not valid until {valid_from}"
            format_no_longer_valid: Custom formatter for "no longer valid" messages.
                Receives (as_of, valid_until) dates. Default: "Entity expired on {valid_until}"
            role: Semantic role to stamp on emitted ConstraintOutcome records.
        """
        self._name = name
        self._format_not_yet_valid = format_not_yet_valid or _default_not_yet_valid
        self._format_no_longer_valid = (
            format_no_longer_valid or _default_no_longer_valid
        )
        self._role = role

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
        if not context.as_of:
            return candidates

        as_of = context.as_of
        entity_ids = [c.entity_id for c in candidates]
        entities = store.bulk_get_entities(entity_ids)

        result: list[Candidate] = []
        filtered_count = 0

        for candidate in candidates:
            entity = entities.get(candidate.entity_id)
            if not entity:
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

            valid = True
            reason = None

            if entity.valid_from and as_of < entity.valid_from:
                valid = False
                reason = self._format_not_yet_valid(as_of, entity.valid_from)
            elif entity.valid_until and as_of >= entity.valid_until:
                valid = False
                reason = self._format_no_longer_valid(as_of, entity.valid_until)

            candidate.constraint_outcomes.append(
                ConstraintOutcome(
                    constraint_name=self.name,
                    passed=valid,
                    severity=Severity.HARD,
                    reason=reason,
                    role=self._role,
                )
            )

            if valid:
                result.append(candidate)
            else:
                filtered_count += 1

        emit_constraint_applied(
            trace, self.name, filtered=filtered_count, remaining=len(result)
        )

        return result


def temporal_constraint(
    name: str,
    format_not_yet_valid: MessageFormatter | None = None,
    format_no_longer_valid: MessageFormatter | None = None,
    role: ConstraintRole | None = None,
) -> Constraint:
    """Create a temporal constraint with the given configuration.

    This is a convenience factory for creating TemporalConstraint instances.

    Args:
        name: Unique name for the constraint
        format_not_yet_valid: Custom formatter for "not yet valid" messages
        format_no_longer_valid: Custom formatter for "no longer valid" messages
        role: Semantic role to stamp on emitted ConstraintOutcome records.

    Returns:
        Configured TemporalConstraint instance
    """
    return TemporalConstraint(
        name=name,
        format_not_yet_valid=format_not_yet_valid,
        format_no_longer_valid=format_no_longer_valid,
        role=role,
    )
