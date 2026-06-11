"""Prominence helpers.

The two raw signals are sourced from different services — population from Data
Commons (lives here), sitelink counts from Wikidata SPARQL (lives in
:mod:`resolvekit.builder.sources.wikidata.sitelinks`). ``compute_prominence``
is source-agnostic normalization math; it stays here because Data Commons
remains the bigger half of the contract for now.
"""

from __future__ import annotations

import math

from resolvekit.builder.sources.datacommons.client import DataCommons

# Region entity types that get containment-derived prominence.  The value for
# each type key is irrelevant; the set determines which buckets are treated as
# region tiers in ``compute_containment_prominence``.
REGION_TIER_TYPES: frozenset[str] = frozenset(
    {"geo.subregion", "geo.continental_union", "geo.region"}
)


def fetch_population(
    *,
    dc: DataCommons,
    entity_ids: list[str],
) -> dict[str, float]:
    """Return {entity_id: population} for entities with a Count_Person obs."""
    return dc.fetch_observations(entity_ids, variable_dcid="Count_Person")


def compute_prominence(
    *,
    sitelinks: dict[str, int],
    populations: dict[str, float],
) -> dict[str, float]:
    """Normalize raw signals to [0, 1] per pack and merge.

    For each entity: prefer sitelinks if present. Else use
    log10(population + 1). Normalize each bucket separately to
    [0, 1] over the entities that produced a raw value, then
    union (sitelink-derived wins on collision).

    Output is clipped to [0.0, 1.0]. Degenerate buckets (one entity
    or fewer with a raw value) emit 0.5 for that entity — the no-op
    centering point — rather than 0.0/1.0.
    """
    if not sitelinks and not populations:
        return {}

    out: dict[str, float] = {}
    _apply_bucket(out, {str(eid): float(v) for eid, v in sitelinks.items()})

    pop_bucket = {
        str(eid): math.log10(pv + 1)
        for eid, pv in populations.items()
        if str(eid) not in out
    }
    _apply_bucket(out, pop_bucket)

    return out


def _apply_bucket(out: dict[str, float], bucket: dict[str, float]) -> None:
    """Min-max normalize ``bucket`` into [0, 1] and write into ``out``.

    A single-entity bucket emits 0.5 (the no-op centering point).
    """
    if not bucket:
        return
    if len(bucket) <= 1:
        for entity_id in bucket:
            out[entity_id] = 0.5
        return
    lo = min(bucket.values())
    denom = max(max(bucket.values()) - lo, 1e-9)
    for entity_id, value in bucket.items():
        out[entity_id] = max(0.0, min(1.0, (value - lo) / denom))


def compute_containment_prominence(
    *,
    region_members: dict[str, list[str]],
    country_prominence: dict[str, float],
    region_types: dict[str, str],
) -> dict[str, float]:
    """Compute prominence for region-tier entities from their member countries.

    Each region's raw score is the **sum** of the already-computed prominence
    values of its direct and indirect ``geo.country`` members.  Summing rewards
    both the size of the membership and the individual weight of each member, so
    a larger or more prominent region naturally outranks a smaller, less
    prominent one.  Using the already-computed country prominence values means no
    additional network fetch is required.

    Normalization is applied **per entity-type bucket** (continents, subregions,
    geo.regions, and unions operate at different scales; normalizing them
    separately keeps each bucket's [0, 1] range meaningful within that scale).
    Regions with no country signal in ``country_prominence`` produce a raw score
    of 0.0 and are included in their bucket's normalization — they become the
    minimum end of the range when at least two regions have signal.

    ``region_members`` maps each region entity-id to the list of **all**
    member entity-ids (direct and indirect).  The caller is responsible for
    resolving transitive membership (e.g. a region whose direct members are
    sub-regions rather than countries) before calling this function.  Members
    that are not present in ``country_prominence`` are silently ignored.

    ``region_types`` maps each region entity-id to its entity-type string (e.g.
    ``"geo.subregion"``).  Regions absent from ``region_types`` are skipped.

    Args:
        region_members: Mapping from region entity-id → list of all member
            entity-ids (direct + transitive; may include non-country ids, which
            are ignored).
        country_prominence: Mapping from country entity-id → already-computed
            prominence in [0, 1].
        region_types: Mapping from region entity-id → entity-type string, used
            to group regions into per-type normalization buckets.

    Returns:
        ``{region_id: prominence}`` in [0, 1] for every region in
        ``region_members`` that also has an entry in ``region_types``.  Empty
        input produces an empty output.
    """
    if not region_members:
        return {}

    # Accumulate raw scores (sum of member country prominence values).
    raw: dict[str, float] = {}
    for region_id, members in region_members.items():
        if region_id not in region_types:
            continue
        raw[region_id] = sum(
            country_prominence[mid] for mid in members if mid in country_prominence
        )

    if not raw:
        return {}

    # Group regions by entity-type for per-bucket normalization.
    buckets: dict[str, dict[str, float]] = {}
    for region_id, score in raw.items():
        entity_type = region_types[region_id]
        buckets.setdefault(entity_type, {})[region_id] = score

    out: dict[str, float] = {}
    for bucket in buckets.values():
        _apply_bucket(out, bucket)

    return out
