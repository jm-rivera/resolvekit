"""geo_admin builder — admin1/admin2/admin3 rows sampled from the shipped store."""

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


_ADMIN_TYPES: tuple[str, ...] = ("geo.admin1", "geo.admin2", "geo.admin3")
# Per-entity-type sample sizes for the admin builder. These are builder-internal
# defaults and are not lifted to DatasetSpec.source_limits; they control how many
# entity IDs are sampled from the shared SQLite store before synthetic rows are
# generated. Tune here if you want a different admin1/admin2/admin3 mix in
# geo_admin.
_PER_TYPE_SAMPLE: dict[str, int] = {
    "geo.admin1": 500,
    "geo.admin2": 700,
    "geo.admin3": 300,
}


def build(
    *,
    store: EntityStore,
    limit: int | None = None,
    seed: int = 42,
) -> list[Query]:
    samples = sample_entity_ids(
        entity_types=_ADMIN_TYPES,
        per_type_limits=_PER_TYPE_SAMPLE,
        seed=seed,
        db_path=store_db_path(store),
    )
    if not samples:
        logger.info("geo_admin: no shared store samples available")
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
        "geo_admin: emitted %d rows from %d entities", len(rows), len(samples)
    )
    return rows
