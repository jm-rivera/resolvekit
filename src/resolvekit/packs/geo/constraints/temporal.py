"""Temporal validity constraint for geo entities."""

from resolvekit.core.model import ConstraintRole
from resolvekit.shared.constraints import TemporalConstraint


class GeoTemporalConstraint(TemporalConstraint):
    """Check temporal validity of candidates.

    Hard constraint: when ``context.as_of`` is set, candidates outside their
    ``[valid_from, valid_until)`` window are dropped. No-op when ``as_of`` is
    ``None``.
    """

    def __init__(self) -> None:
        super().__init__(
            name="geo_temporal_constraint",
            role=ConstraintRole.TEMPORAL_SCOPE,
        )
