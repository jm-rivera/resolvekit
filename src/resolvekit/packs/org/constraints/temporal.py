"""Temporal validity constraint for org entities."""

from datetime import date

from resolvekit.core.model import ConstraintRole
from resolvekit.shared import TemporalConstraint


def _format_not_yet_valid(as_of: date, valid_from: date) -> str:
    """Org-specific message for entities not yet valid."""
    return f"Not yet valid as of {as_of}"


def _format_no_longer_valid(as_of: date, valid_until: date) -> str:
    """Org-specific message for expired entities."""
    return f"No longer valid as of {as_of}"


class OrgTemporalConstraint(TemporalConstraint):
    """Check temporal validity for rebrands/defunct orgs."""

    def __init__(self) -> None:
        super().__init__(
            name="org_temporal_constraint",
            format_not_yet_valid=_format_not_yet_valid,
            format_no_longer_valid=_format_no_longer_valid,
            role=ConstraintRole.TEMPORAL_SCOPE,
        )
