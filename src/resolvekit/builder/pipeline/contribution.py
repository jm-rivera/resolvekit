"""Typed enricher→pipeline contract and the single SQLite writer for it.

Enrichers are pure ``(db_path) -> GraphContribution`` functions: they read inputs
and compute the rows to add (and entity ids to remove), but never touch the DB.
``apply_contribution`` is the only sink — it performs every INSERT/DELETE inside one
transaction with INSERT OR IGNORE semantics (idempotent re-runs), so the
deferred-FTS-rebuild invariant is structural: no enricher can rebuild FTS because no
enricher writes.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from resolvekit.builder.sqlite.specs import insert_prefix
from resolvekit.builder.sqlite.write import apply_name_rows


@dataclass
class GraphContribution:
    """Rows an enricher contributes to the staging entity graph.

    All fields are flat row-dicts matching the SQLite table columns (the same shape
    ``insert_normalized_payload`` consumes). ``entity_ids_to_delete`` carries the
    filter/DELETE path. Constructed kwargs-only at call sites.
    """

    entities: list[dict[str, Any]] = field(default_factory=list)
    names: list[dict[str, Any]] = field(default_factory=list)
    codes: list[dict[str, Any]] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    entity_ids_to_delete: list[str] = field(default_factory=list)
    entity_attrs: list[dict[str, Any]] = field(default_factory=list)
    entity_validity_updates: list[dict[str, Any]] = field(default_factory=list)


def apply_contribution(
    *, conn: sqlite3.Connection, contribution: GraphContribution
) -> dict[str, int]:
    """Write a contribution to ``conn`` and return per-table net row deltas.

    Kwargs-only. Uses INSERT OR IGNORE for every table (entities/names/codes/relations)
    — NOT OR REPLACE — so enricher writes never overwrite existing rows and re-runs
    are idempotent. Removals cascade across names/codes/relations (by entity_id and
    by target_id) then entities, mirroring ``_build_region_filter_contribution``.

    The caller owns the transaction: open ``connect_sqlite(db, busy_timeout_ms=30000)``
    and wrap in ``transaction(conn)`` before calling.
    """
    before = _count_tables(conn)

    # INSERT OR IGNORE — not OR REPLACE — for all tables.
    conn.executemany(
        insert_prefix("entities", conflict="IGNORE") + " VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                row["entity_id"],
                row["entity_type"],
                row["canonical_name"],
                row["canonical_name_norm"],
                row.get("valid_from"),
                row.get("valid_until"),
                _serialize_attrs(row.get("attrs_json")),
            )
            for row in contribution.entities
        ],
    )

    apply_name_rows(
        conn=conn,
        rows=[_name_tuple(n) for n in contribution.names],
    )

    conn.executemany(
        insert_prefix("codes", conflict="IGNORE") + " VALUES (?, ?, ?, ?)",
        [
            (
                row["entity_id"],
                row["system"],
                row["value"],
                row["value_norm"],
            )
            for row in contribution.codes
        ],
    )

    conn.executemany(
        insert_prefix("relations", conflict="IGNORE") + " VALUES (?, ?, ?, ?, ?)",
        [
            (
                row["entity_id"],
                row["relation_type"],
                row["target_id"],
                row.get("valid_from"),
                row.get("valid_until"),
            )
            for row in contribution.relations
        ],
    )

    if contribution.entity_ids_to_delete:
        ids = contribution.entity_ids_to_delete
        placeholders = ",".join("?" for _ in ids)
        for table in ("names", "codes", "relations"):
            conn.execute(
                f"DELETE FROM {table} WHERE entity_id IN ({placeholders})",
                ids,
            )
        conn.execute(
            f"DELETE FROM relations WHERE target_id IN ({placeholders})",
            ids,
        )
        conn.execute(
            f"DELETE FROM entities WHERE entity_id IN ({placeholders})",
            ids,
        )

    # TODO: batch this for large packs
    for row in contribution.entity_attrs:
        entity_id = str(row["entity_id"])
        patch = dict(row["attrs"])
        existing = conn.execute(
            "SELECT attrs_json FROM entities WHERE entity_id = ?", (entity_id,)
        ).fetchone()
        if existing is None:
            continue
        merged = json.loads(existing[0]) if existing[0] else {}
        merged.update(patch)
        conn.execute(
            "UPDATE entities SET attrs_json = ? WHERE entity_id = ?",
            (json.dumps(merged, sort_keys=True), entity_id),
        )

    for row in contribution.entity_validity_updates:
        conn.execute(
            "UPDATE entities SET valid_from = ?, valid_until = ? WHERE entity_id = ?",
            (row.get("valid_from"), row.get("valid_until"), str(row["entity_id"])),
        )

    after = _count_tables(conn)
    return {k: after[k] - before[k] for k in after}


def _count_tables(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in ("entities", "names", "codes", "relations")
    }


def _serialize_attrs(attrs: Any) -> str:
    """Serialize attrs_json to a string; accepts str or dict."""
    if isinstance(attrs, str):
        return attrs
    return json.dumps(attrs or {})


def _name_tuple(row: dict[str, Any]) -> tuple[str, str, str, str, str, str, int]:
    """Convert a names dict to the 7-tuple expected by apply_name_rows."""
    return (
        str(row["entity_id"]),
        str(row["name_kind"]),
        str(row["value"]),
        str(row["value_norm"]),
        str(row.get("lang") or ""),
        str(row.get("script") or ""),
        int(row.get("is_preferred", 0)),
    )
