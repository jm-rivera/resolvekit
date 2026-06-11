"""Populate per-entity prominence scores into the geo-shared staging store.

Fetches Wikidata sitelink counts (primary signal, queried straight from WDQS
via :mod:`resolvekit.builder.sources.wikidata.sitelinks`) and DC population
observations (fallback) for every entity in the shared geo store, then
normalizes per entity-type bucket to [0, 1] and writes
``attrs_json["prominence"]`` via the ``apply_contribution`` path.

Sitelinks comes from Wikidata directly because the ONE-hosted DC instance does
not import ``wikidataSitelinkCount``; the local ``codes`` table already stores
Wikidata QIDs for ~95% of geo entities, which is the mapping key.

Run this after an initial ``build_data`` run (which populates the shared store)
and before the re-packaging ``build_data`` run (which fans the enriched attrs
into per-module packs).

Run via::

    uv run python -m scripts.build.enrich_prominence

To customize, edit the kwargs in the ``__main__`` block at the bottom of the
file (or import ``run()`` and pass an ``EnrichProminenceSettings`` from a
notebook).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from resolvekit.builder.pipeline.contribution import (
    GraphContribution,
    apply_contribution,
)
from resolvekit.builder.pipeline.types import BuildExecutionError
from resolvekit.builder.sources.datacommons.client import DataCommons
from resolvekit.builder.sources.datacommons.constants import DEFAULT_DC_INSTANCE
from resolvekit.builder.sources.datacommons.geo.prominence import (
    REGION_TIER_TYPES,
    compute_containment_prominence,
    compute_prominence,
    fetch_population,
)
from resolvekit.builder.sources.wikidata import sitelinks as wd_sitelinks
from resolvekit.builder.sqlite.context import connect_sqlite, transaction

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_BUILD_ROOT = PROJECT_ROOT / "data" / "build"
_SHARED_GEO_ROOT = _BUILD_ROOT / "shared" / "geo"


@dataclass(frozen=True, slots=True, kw_only=True)
class EnrichProminenceSettings:
    """Settings for prominence enrichment.

    Edit these in the ``__main__`` block; there is no CLI parsing.
    """

    dc_instance: str = DEFAULT_DC_INSTANCE
    max_concurrent_requests: int = 4
    failure_threshold: float = 0.10
    shared_geo_root: Path = _SHARED_GEO_ROOT
    target: str = "shared_store"
    wikidata_user_agent: str = wd_sitelinks.USER_AGENT
    wikidata_batch_size: int = 1000
    wikidata_request_delay: float = 0.5
    # Resumable cache: per-bucket prominences are persisted here as each
    # bucket finishes so reruns after a WDQS hiccup don't re-fetch what
    # already succeeded. Delete this file to force a full refetch.
    prominence_cache_path: Path = _SHARED_GEO_ROOT / "prominence_cache.json"


def _fetch_bucket(
    *,
    dc: DataCommons,
    entity_type: str,
    entity_ids: list[str],
    entity_to_qid: dict[str, str],
    failure_threshold: float,
    wikidata_user_agent: str,
    wikidata_batch_size: int,
    wikidata_request_delay: float,
) -> dict[str, float]:
    """Fetch sitelinks + population for one entity-type bucket and compute prominences.

    Raises ``BuildExecutionError`` if >``failure_threshold`` of entities produce
    neither signal (network error / malformed payload on both fetches). Entities
    that legitimately have no sitelinks and no population data are missing, not
    failed — they produce no prominence key but do not count against the budget.
    """
    total = len(entity_ids)

    bucket_qids = {entity_to_qid[eid] for eid in entity_ids if eid in entity_to_qid}
    sitelinks_by_entity: dict[str, int] = {}
    if bucket_qids:
        try:
            sitelinks_by_qid = wd_sitelinks.fetch_sitelinks_by_qid(
                qids=bucket_qids,
                user_agent=wikidata_user_agent,
                batch_size=wikidata_batch_size,
                request_delay=wikidata_request_delay,
            )
        except Exception as exc:
            logger.warning(
                "bucket %s: sitelinks fetch failed (%s); falling back to population for all entities",
                entity_type,
                exc,
            )
        else:
            for eid in entity_ids:
                qid = entity_to_qid.get(eid)
                if qid is not None and qid in sitelinks_by_qid:
                    sitelinks_by_entity[eid] = sitelinks_by_qid[qid]

    missing_sitelinks = [eid for eid in entity_ids if eid not in sitelinks_by_entity]

    populations: dict[str, float] = {}
    if missing_sitelinks:
        try:
            populations = fetch_population(dc=dc, entity_ids=missing_sitelinks)
        except Exception as exc:
            logger.warning(
                "bucket %s: population fetch failed (%s); proceeding with sitelinks only",
                entity_type,
                exc,
            )

    missing_any = [
        eid
        for eid in entity_ids
        if eid not in sitelinks_by_entity and eid not in populations
    ]
    missing_pct = len(missing_any) / total if total > 0 else 0.0
    qid_rate = len(bucket_qids) / total if total > 0 else 0.0

    # The threshold guards against partial network failure (rate limits,
    # WDQS 502s, etc.). It only makes sense for buckets where (a) we expected
    # broad coverage to begin with — most entities must have a Wikidata QID
    # (sitelinks-eligible) — and (b) the bucket is large enough that the
    # missing-rate is statistically meaningful. A handful of entities will
    # naturally include a couple with no signal (e.g. ``geo.continent`` has
    # Antarctica with no Count_Person).
    min_qid_rate_for_threshold = 0.5
    min_bucket_size_for_threshold = 100
    if (
        total >= min_bucket_size_for_threshold
        and qid_rate >= min_qid_rate_for_threshold
        and 0 < missing_pct < 1.0
        and missing_pct > failure_threshold
    ):
        raise BuildExecutionError(
            f"bucket {entity_type!r}: {missing_pct:.1%} of entities produced neither "
            f"sitelinks nor population signal (exceeds {failure_threshold:.1%} failure "
            f"threshold). Check WDQS/DC connectivity and payload validity."
        )
    if missing_pct > 0 and (
        missing_pct >= 1.0
        or qid_rate < min_qid_rate_for_threshold
        or total < min_bucket_size_for_threshold
    ):
        logger.info(
            "bucket %s: low signal coverage (size=%d entities, %.0f%% with QIDs, %.0f%% missing both signals) — proceeding",
            entity_type,
            total,
            qid_rate * 100,
            missing_pct * 100,
        )

    pct_sitelinks = len(sitelinks_by_entity) / total if total > 0 else 0.0
    pct_population = len(populations) / total if total > 0 else 0.0
    logger.info(
        "bucket %s: total=%d sitelinks=%.0f%% population=%.0f%% missing=%.0f%%",
        entity_type,
        total,
        pct_sitelinks * 100,
        pct_population * 100,
        missing_pct * 100,
    )

    return compute_prominence(sitelinks=sitelinks_by_entity, populations=populations)


def _load_cache(path: Path) -> dict[str, dict[str, float]]:
    """Load the per-bucket prominence cache, or empty if absent / unreadable."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "Could not read prominence cache %s (%s); starting fresh", path, exc
        )
        return {}
    return {
        str(k): {str(eid): float(v) for eid, v in d.items()} for k, d in data.items()
    }


def _save_cache(path: Path, cache: dict[str, dict[str, float]]) -> None:
    """Persist the cache atomically (write to tmp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cache), encoding="utf-8")
    tmp.replace(path)


def _load_region_members(
    conn: sqlite3.Connection,
    *,
    region_types: dict[str, str],
) -> dict[str, list[str]]:
    """Return a mapping from region entity-id to its transitive country members.

    Uses the ``contained_in`` relation for subregions/regions (where countries
    appear as direct or nested members) and the ``member_of`` relation for
    continental unions (where countries register via ``member_of``).

    For subregions whose direct members are other subregions rather than
    countries (e.g. ``m49/202`` Sub-Saharan Africa → leaf subregions →
    countries), the function resolves one additional level of containment so
    that country-level signal propagates up correctly.  Only ``geo.country``
    entities contribute to the signal — intermediate region nodes are ignored.

    The result maps every region in ``region_types`` to its (possibly empty)
    list of country entity-ids.
    """
    # All contained_in edges: child → parent.
    containment = conn.execute(
        "SELECT entity_id, target_id FROM relations WHERE relation_type = 'contained_in'"
    ).fetchall()
    # All member_of edges: country → group.
    membership = conn.execute(
        "SELECT entity_id, target_id FROM relations WHERE relation_type = 'member_of'"
    ).fetchall()
    # Entity types for all entities.
    entity_type_map: dict[str, str] = dict(
        conn.execute("SELECT entity_id, entity_type FROM entities").fetchall()
    )

    # Build an inverted index: parent_id → list of direct child entity-ids.
    children_of: dict[str, list[str]] = {}
    for child_id, parent_id in containment:
        children_of.setdefault(str(parent_id), []).append(str(child_id))
    # Continental unions use member_of (countries → union).
    for child_id, parent_id in membership:
        if entity_type_map.get(str(parent_id)) == "geo.continental_union":
            children_of.setdefault(str(parent_id), []).append(str(child_id))

    def _collect_countries(region_id: str, depth: int = 0) -> list[str]:
        """Recursively collect geo.country descendants, up to depth 4."""
        if depth > 4:
            # Guard against unexpected deep nesting; should never occur in the
            # current dataset but prevents an infinite loop if the graph were
            # ever malformed.
            return []
        result: list[str] = []
        for child_id in children_of.get(region_id, []):
            child_type = entity_type_map.get(child_id, "")
            if child_type == "geo.country":
                result.append(child_id)
            elif child_type in REGION_TIER_TYPES:
                # Recurse into nested region nodes (e.g. Sub-Saharan Africa →
                # its leaf subregions → countries).
                result.extend(_collect_countries(child_id, depth + 1))
        return result

    return {
        region_id: _collect_countries(region_id)
        for region_id in region_types
        if entity_type_map.get(region_id, "") in REGION_TIER_TYPES
    }


def run(*, settings: EnrichProminenceSettings) -> None:
    """Enrich the geo-shared store with prominence scores."""
    shared_db = settings.shared_geo_root / "entities.sqlite"
    if not shared_db.exists():
        raise BuildExecutionError(
            f"Shared geo store not found at {shared_db}. "
            "Run build_data first to populate the staging store."
        )

    dc = DataCommons(
        dc_instance=settings.dc_instance,
        max_concurrent_requests=settings.max_concurrent_requests,
    )

    with connect_sqlite(shared_db) as conn:
        rows = conn.execute("SELECT entity_id, entity_type FROM entities").fetchall()
        code_rows = conn.execute(
            "SELECT entity_id, value FROM codes WHERE system = 'wikidata'"
        ).fetchall()

    entity_to_qid = {str(eid): str(value).upper() for eid, value in code_rows}

    buckets: dict[str, list[str]] = {}
    for entity_id, entity_type in rows:
        buckets.setdefault(str(entity_type), []).append(str(entity_id))

    logger.info(
        "Enriching prominence for %d entity types (%d total entities; %d with Wikidata QIDs)",
        len(buckets),
        len(rows),
        len(entity_to_qid),
    )

    prominences_by_bucket = _load_cache(settings.prominence_cache_path)
    cache_lock = threading.Lock()

    pending = [
        (entity_type, entity_ids)
        for entity_type, entity_ids in buckets.items()
        if entity_type not in prominences_by_bucket
    ]
    if len(pending) < len(buckets):
        logger.info(
            "Resuming: %d/%d buckets already cached, %d to fetch",
            len(buckets) - len(pending),
            len(buckets),
            len(pending),
        )

    def _checkpoint(entity_type: str, result: dict[str, float]) -> None:
        with cache_lock:
            prominences_by_bucket[entity_type] = result
            _save_cache(settings.prominence_cache_path, prominences_by_bucket)

    worker_count = min(settings.max_concurrent_requests, max(len(pending), 1))

    if worker_count <= 1:
        for entity_type, entity_ids in pending:
            result = _fetch_bucket(
                dc=dc,
                entity_type=entity_type,
                entity_ids=entity_ids,
                entity_to_qid=entity_to_qid,
                failure_threshold=settings.failure_threshold,
                wikidata_user_agent=settings.wikidata_user_agent,
                wikidata_batch_size=settings.wikidata_batch_size,
                wikidata_request_delay=settings.wikidata_request_delay,
            )
            _checkpoint(entity_type, result)
    elif pending:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_type = {
                executor.submit(
                    _fetch_bucket,
                    dc=dc,
                    entity_type=entity_type,
                    entity_ids=entity_ids,
                    entity_to_qid=entity_to_qid,
                    failure_threshold=settings.failure_threshold,
                    wikidata_user_agent=settings.wikidata_user_agent,
                    wikidata_batch_size=settings.wikidata_batch_size,
                    wikidata_request_delay=settings.wikidata_request_delay,
                ): entity_type
                for entity_type, entity_ids in pending
            }
            for future in as_completed(future_to_type):
                entity_type = future_to_type[future]
                _checkpoint(entity_type, future.result())

    # -----------------------------------------------------------------------
    # Containment-derived prominence for region tiers
    #
    # Region-tier entities' prominence is derived from the sum of their
    # transitive geo.country members' prominence values, normalized per
    # entity-type bucket. Subregions and continental unions have no Wikidata
    # QIDs, so sitelink/population signals do not reach them; membership
    # aggregation is the sole data source for region prominence.
    #
    # Results are not cached separately — they are deterministic given the
    # country prominence values already in prominences_by_bucket, so they are
    # recomputed on every run.  This keeps the cache schema simple and avoids
    # stale containment data surviving a rebuild.
    # -----------------------------------------------------------------------
    country_prominence = prominences_by_bucket.get("geo.country", {})
    if country_prominence:
        # Build region_types: entity_id → entity_type for all region-tier entities.
        region_types_map: dict[str, str] = {
            str(eid): str(etype)
            for eid, etype in rows
            if str(etype) in REGION_TIER_TYPES
        }
        with connect_sqlite(shared_db) as conn:
            region_members = _load_region_members(conn, region_types=region_types_map)

        containment_prominences = compute_containment_prominence(
            region_members=region_members,
            country_prominence=country_prominence,
            region_types=region_types_map,
        )

        # Overwrite the (empty) per-bucket entries with containment-derived values
        # so that the apply loop below treats them uniformly.
        for region_id, prominence in containment_prominences.items():
            entity_type = region_types_map[region_id]
            prominences_by_bucket.setdefault(entity_type, {})[region_id] = prominence

        total_covered = len(containment_prominences)
        total_region = len(region_types_map)
        logger.info(
            "containment prominence: computed for %d/%d region-tier entities",
            total_covered,
            total_region,
        )
    else:
        logger.warning(
            "geo.country bucket has no prominence values; skipping containment prominence"
        )

    for entity_type, prominences in prominences_by_bucket.items():
        if not prominences:
            logger.info(
                "bucket %s: no prominences computed, skipping apply", entity_type
            )
            continue

        entity_attrs = [
            {"entity_id": eid, "attrs": {"prominence": p}}
            for eid, p in prominences.items()
        ]
        contribution = GraphContribution(entity_attrs=entity_attrs)

        with (
            connect_sqlite(shared_db, busy_timeout_ms=30000) as conn,
            transaction(conn),
        ):
            apply_contribution(conn=conn, contribution=contribution)

        logger.info(
            "bucket %s: applied prominence to %d entities",
            entity_type,
            len(prominences),
        )


def main() -> None:
    """Entry point for direct invocation; edit settings below to customize."""
    run(settings=EnrichProminenceSettings())


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(
            "enrich_prominence.py takes no CLI arguments. Edit "
            "EnrichProminenceSettings(...) in the __main__ block."
        )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    main()
