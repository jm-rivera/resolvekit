"""Geo entity-type specificity rankings for M9 candidate re-ordering."""

# Lower rank = more specific. Packs with higher specificity appear first
# when confidence scores are tied (rounded to 3 decimals).
_GEO_SPECIFICITY: dict[str, int] = {
    "geo.country": 0,
    "geo.admin1": 1,
    "geo.region": 2,
    "geo.subregion": 2,
    "geo.continental_union": 3,
    "geo.organization": 4,
}


def geo_candidate_ordering_key(entity_type: str) -> int | None:
    """Return specificity rank for a geo entity type, or None for unknown types.

    Lower rank means more specific (country=0 precedes region=2).
    Returns None only when the entity_type is not a recognized geo type,
    which callers should treat as "no opinion" (equivalent to 99 in the sort).
    """
    return _GEO_SPECIFICITY.get(entity_type)
