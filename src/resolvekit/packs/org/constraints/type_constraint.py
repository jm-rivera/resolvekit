"""Type constraint for org entities."""

from resolvekit.core.model import ConstraintRole
from resolvekit.shared import TypeConstraint


class OrgTypeConstraint(TypeConstraint):
    """Filter candidates by org type (IGO, NGO, foundation, etc.)."""

    def __init__(self) -> None:
        super().__init__(name="org_type_constraint", role=ConstraintRole.TYPE_SCOPE)
