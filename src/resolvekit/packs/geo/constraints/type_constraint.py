"""Type constraint for geo entities."""

from resolvekit.core.model import ConstraintRole
from resolvekit.shared.constraints import TypeConstraint

# Populated places are stored at whatever administrative level Data Commons
# assigned them — not necessarily as geo.city.  When a caller requests
# geo.city, we must also accept candidates stored as any admin level.
# geo.continental_union blocs (AU, ASEAN, G20 …) are stored as geo.organization
# in the geo pack, so that semantic type must be accepted too.
# geo.region accepts geo.organization for the same reason: UN development
# groupings (LDCs, SIDS, LLDCs) are country collections a caller would query as
# a "world region" but were built as geo.organization in continental_unions.
# geo.country is intentionally NOT widened: it must stay strict so that
# ambiguous names like "Georgia" resolve to the US state (geo.admin1) only
# when the caller hasn't asked for a country.
_GEO_TYPE_COMPATIBILITY: dict[str, frozenset[str]] = {
    "geo.city": frozenset(
        {
            "geo.city",
            "geo.admin1",
            "geo.admin2",
            "geo.admin3",
            "geo.admin4",
            "geo.admin5",
        }
    ),
    "geo.continental_union": frozenset({"geo.continental_union", "geo.organization"}),
    "geo.region": frozenset({"geo.region", "geo.organization"}),
    # geo.subregion is intentionally absent: pure geographic type, never stored as
    # geo.organization; absent entry means strict match only (no widening).
}


class GeoTypeConstraint(TypeConstraint):
    """Filter candidates by entity type.

    Hard constraint: removes candidates that don't match entity_types.

    Uses a geo-specific compatibility map so that semantic hints like
    geo.city also accept candidates stored at any admin level, and
    geo.continental_union also accepts candidates stored as geo.organization.
    geo.country remains strict.
    """

    def __init__(self) -> None:
        super().__init__(
            "geo_type_constraint",
            role=ConstraintRole.TYPE_SCOPE,
            compatibility=_GEO_TYPE_COMPATIBILITY,
        )
