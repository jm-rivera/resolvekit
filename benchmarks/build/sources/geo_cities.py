"""geo_cities builder — city rows sampled from the shipped store."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from benchmarks.build.sources._geo_common import (
    build_entity_rows,
    sample_entity_ids,
    store_db_path,
)
from benchmarks.core.kernel import Query

if TYPE_CHECKING:
    from resolvekit.core.store import EntityStore

logger = logging.getLogger(__name__)


_CITY_TYPES: tuple[str, ...] = ("geo.city",)
# Per-entity-type sample size for the cities builder. This is builder-internal
# and is not lifted to DatasetSpec.source_limits; it controls how many city
# entity IDs are sampled from the shared SQLite store before synthetic rows are
# generated. Tune here if you want more or fewer cities in geo_cities.
_PER_TYPE_SAMPLE: dict[str, int] = {"geo.city": 1200}


def build(
    *,
    store: EntityStore,
    limit: int | None = None,
    seed: int = 42,
) -> list[Query]:
    samples = sample_entity_ids(
        entity_types=_CITY_TYPES,
        per_type_limits=_PER_TYPE_SAMPLE,
        seed=seed,
        db_path=store_db_path(store),
    )
    if not samples:
        logger.info("geo_cities: no shared store samples available")
        return []

    rows = build_entity_rows(
        store=store,
        entity_samples=samples,
        seed=seed,
        typos_per_entity=1,
    )
    if limit is not None:
        rows = rows[:limit]
    logger.info(
        "geo_cities: emitted %d rows from %d entities", len(rows), len(samples)
    )
    return rows
