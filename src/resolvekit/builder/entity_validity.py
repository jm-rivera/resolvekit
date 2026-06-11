"""Entity-validity enricher: apply valid_from / valid_until to existing entities.

Reads ``builder/data/entity_validity.yaml`` and produces UPDATE records for
entities that already exist in the staging DB. Each entry carries ``entity_id``,
``valid_from``, and ``valid_until`` (ISO date strings or None).

Registered as an enricher under COUNTRY_ENTITY_TYPE in pipeline/enrich.py.
Idempotent: fixed-value UPDATEs produce zero net change on re-run.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from resolvekit.builder.pipeline.contribution import GraphContribution
from resolvekit.builder.sqlite.context import connect_sqlite

try:
    import yaml as _yaml
except ImportError:  # pragma: no cover - optional dep
    _yaml = None  # ty: ignore[invalid-assignment]  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_ENTITY_VALIDITY_YAML_PATH = Path(__file__).parent / "data" / "entity_validity.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    if _yaml is None:
        raise ImportError(
            "entity_validity enricher requires pyyaml. "
            "Install with: pip install 'resolvekit[data]'"
        )
    with path.open("r", encoding="utf-8") as fh:
        return _yaml.safe_load(fh)


def build_entity_validity_contribution(db_path: Path) -> GraphContribution:
    """Compute valid_from / valid_until UPDATE records for existing entities (pure read).

    Returns a ``GraphContribution`` with ``entity_validity_updates`` populated.
    The caller (pipeline) writes them via ``apply_contribution``. Idempotent on
    re-run (fixed-value UPDATE).

    Entries whose ``entity_id`` is absent from the DB are counted and logged as
    warnings — a missing target is a curation issue, not a fatal error.
    """
    data = _load_yaml(_ENTITY_VALIDITY_YAML_PATH)
    entries = data.get("entities", [])
    if not entries:
        return GraphContribution()

    with connect_sqlite(db_path) as conn:
        present_ids: set[str] = {
            str(row[0])
            for row in conn.execute("SELECT entity_id FROM entities").fetchall()
        }

    updates: list[dict[str, Any]] = []
    missing_count = 0
    for entry in entries:
        entity_id = str(entry["entity_id"])
        if entity_id not in present_ids:
            missing_count += 1
            logger.warning(
                "entity_validity enricher: entity_id %r not found in DB — skipping",
                entity_id,
            )
            continue
        updates.append(
            {
                "entity_id": entity_id,
                "valid_from": entry.get("valid_from"),
                "valid_until": entry.get("valid_until"),
            }
        )

    if missing_count:
        logger.warning(
            "entity_validity enricher: %d entr%s had no matching entity in DB",
            missing_count,
            "y" if missing_count == 1 else "ies",
        )

    return GraphContribution(entity_validity_updates=updates)
