from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from resolvekit.builder.sqlite import (
    count_entities,
    count_missing_relation_targets,
    insert_normalized_payload,
    list_missing_relation_targets,
)
from resolvekit.builder.utils import chunk_list

if TYPE_CHECKING:
    from resolvekit.builder.pipeline.core import BuildContext

from resolvekit.builder.pipeline.types import BuildExecutionError


def _reconcile_domain_targets(
    *,
    context: BuildContext,
    domain: str,
    relation_types: list[str],
    db_path: Path,
) -> dict[str, Any]:
    max_rounds = context.options.reconcile_max_rounds
    max_entities = context.options.reconcile_max_entities
    batch_size = context.options.reconcile_batch_size
    adapter = context.adapters[domain]

    # When reconcile already targets the shared store, relation targets are
    # present — no cross-DB copy needed.
    geo_cache_ready = (
        domain == "geo"
        and context.geo_shared.db_path.exists()
        and bool(context.geo_shared.ready_units())
        and db_path != context.geo_shared.db_path  # reconcile writes shared directly
    )

    hydrated_entities_total = 0
    rounds: list[dict[str, int]] = []
    stop_reason = "max_rounds_reached"
    last_missing_rows = 0
    last_missing_targets = 0

    for round_index in range(max_rounds):
        missing_rows_before, missing_targets_before = count_missing_relation_targets(
            db_path,
            relation_types=relation_types,
        )
        if missing_targets_before == 0:
            stop_reason = "closed"
            last_missing_rows, last_missing_targets = (
                missing_rows_before,
                missing_targets_before,
            )
            break

        remaining_budget = max_entities - hydrated_entities_total
        if remaining_budget <= 0:
            stop_reason = "entity_budget_exhausted"
            last_missing_rows, last_missing_targets = (
                missing_rows_before,
                missing_targets_before,
            )
            break

        target_ids = list_missing_relation_targets(
            db_path,
            relation_types=relation_types,
            limit=remaining_budget,
        )
        if not target_ids:
            stop_reason = "no_targets_returned"
            last_missing_rows, last_missing_targets = (
                missing_rows_before,
                missing_targets_before,
            )
            break

        entities_before = count_entities(db_path)

        remaining_target_ids = list(target_ids)
        if geo_cache_ready:
            try:
                copied = context.geo_shared.copy_entities_to_db(
                    set(remaining_target_ids), db_path
                )
                if copied:
                    remaining_target_ids = [
                        eid for eid in remaining_target_ids if eid not in copied
                    ]
            except (OSError, sqlite3.Error):
                pass  # Fall through to API fetch on any cache error.
        for batch_ids in chunk_list(remaining_target_ids, batch_size):
            raw_payload = adapter.fetch_raw_chunk(domain, batch_ids)
            normalized = adapter.normalize_raw_chunk(domain, raw_payload)
            match normalized:
                case BaseModel():
                    normalized_payload = normalized.model_dump(mode="python")
                case _:
                    normalized_payload = normalized
            insert_normalized_payload(
                db_path,
                _filter_payload_by_entity_ids(normalized_payload, set(batch_ids)),
            )

        entities_after = count_entities(db_path)
        hydrated_this_round = max(entities_after - entities_before, 0)
        hydrated_entities_total += hydrated_this_round

        last_missing_rows, last_missing_targets = count_missing_relation_targets(
            db_path,
            relation_types=relation_types,
        )
        rounds.append(
            {
                "round": round_index + 1,
                "requested_targets": len(target_ids),
                "hydrated_entities": hydrated_this_round,
                "missing_rows_before": missing_rows_before,
                "missing_rows_after": last_missing_rows,
                "missing_targets_before": missing_targets_before,
                "missing_targets_after": last_missing_targets,
            }
        )

        if last_missing_targets == 0:
            stop_reason = "closed"
            break
        if hydrated_this_round == 0:
            stop_reason = "no_progress"
            break

    report = {
        "relation_types": relation_types,
        "max_rounds": max_rounds,
        "max_entities": max_entities,
        "hydrated_entities": hydrated_entities_total,
        "remaining_missing_rows": last_missing_rows,
        "remaining_missing_targets": last_missing_targets,
        "rounds": rounds,
        "stop_reason": stop_reason,
    }

    if last_missing_targets > 0:
        raise BuildExecutionError(
            "Reconcile stage could not close missing relation targets for "
            f"domain '{domain}': remaining_targets={last_missing_targets}, "
            f"remaining_rows={last_missing_rows}, relation_types={relation_types}, "
            f"hydrated_entities={hydrated_entities_total}, max_rounds={max_rounds}, "
            f"max_entities={max_entities}."
        )
    return report


def _filter_payload_by_entity_ids(
    payload: dict[str, list[dict[str, Any]]],
    allowed_entity_ids: set[str],
) -> dict[str, list[dict[str, Any]]]:
    return {
        "entities": [
            row
            for row in payload.get("entities", [])
            if str(row.get("entity_id")) in allowed_entity_ids
        ],
        "names": [
            row
            for row in payload.get("names", [])
            if str(row.get("entity_id")) in allowed_entity_ids
        ],
        "codes": [
            row
            for row in payload.get("codes", [])
            if str(row.get("entity_id")) in allowed_entity_ids
        ],
        "relations": [
            row
            for row in payload.get("relations", [])
            if str(row.get("entity_id")) in allowed_entity_ids
        ],
    }
