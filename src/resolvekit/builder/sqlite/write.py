"""SQLite schema and write-path helpers for builder artifacts."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from resolvekit.builder.sqlite.context import connect_sqlite, transaction
from resolvekit.builder.sqlite.specs import insert_prefix
from resolvekit.core.store.sqlite_helpers import (
    ensure_sqlite_schema,
    rebuild_fts,
)

__all__ = [
    "apply_name_rows",
    "connect_sqlite",
    "count_entities",
    "count_missing_relation_targets",
    "ensure_sqlite_schema",
    "insert_normalized_payload",
    "list_missing_relation_targets",
    "rebuild_fts",
    "staging_db_path",
    "transaction",
]


def staging_db_path(staging_dir: Path, domain: str) -> Path:
    """Return staging SQLite path for a domain."""
    return staging_dir / f"{domain}.sqlite"


def apply_name_rows(
    *,
    conn: sqlite3.Connection,
    rows: list[tuple[str, str, str, str, str, str, int]],
) -> int:
    """INSERT OR IGNORE the 7-column names rows and return the net delta.

    The caller owns the transaction — this function does the count+executemany
    only and does not open or commit. ``rows`` items must be
    ``(entity_id, name_kind, value, value_norm, lang, script, is_preferred)``.
    """
    before = int(conn.execute("SELECT COUNT(*) FROM names").fetchone()[0])
    conn.executemany(
        """
        INSERT OR IGNORE INTO names(
            entity_id, name_kind, value, value_norm, lang, script, is_preferred
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    after = int(conn.execute("SELECT COUNT(*) FROM names").fetchone()[0])
    return after - before


def insert_normalized_payload(
    db_path: Path,
    payload: dict[str, list[dict[str, Any]]],
) -> None:
    """Insert normalized row payload into SQLite tables."""
    entities = payload.get("entities", [])
    names = payload.get("names", [])
    codes = payload.get("codes", [])
    relations = payload.get("relations", [])

    dedup_names: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for row in names:
        dedup_names[_name_dedup_key(row)] = row

    dedup_relations = {_relation_dedup_key(row): row for row in relations}

    with connect_sqlite(db_path, busy_timeout_ms=30000) as conn, transaction(conn):
        conn.executemany(
            insert_prefix("entities") + " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    row["entity_id"],
                    row["entity_type"],
                    row["canonical_name"],
                    row["canonical_name_norm"],
                    row.get("valid_from"),
                    row.get("valid_until"),
                    json.dumps(row.get("attrs_json", {})),
                )
                for row in entities
            ],
        )
        conn.executemany(
            insert_prefix("names") + " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    row["entity_id"],
                    row["name_kind"],
                    row["value"],
                    row["value_norm"],
                    str(row.get("lang") or ""),
                    str(row.get("script") or ""),
                    int(row.get("is_preferred", 0)),
                )
                for row in dedup_names.values()
            ],
        )
        conn.executemany(
            insert_prefix("codes") + " VALUES (?, ?, ?, ?)",
            [
                (
                    row["entity_id"],
                    row["system"],
                    row["value"],
                    row["value_norm"],
                )
                for row in codes
            ],
        )
        conn.executemany(
            insert_prefix("relations") + " VALUES (?, ?, ?, ?, ?)",
            [
                (
                    row["entity_id"],
                    row["relation_type"],
                    row["target_id"],
                    row.get("valid_from"),
                    row.get("valid_until"),
                )
                for row in dedup_relations.values()
            ],
        )


def count_entities(db_path: Path) -> int:
    """Return total entity row count for a domain DB."""
    with connect_sqlite(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0])


def count_missing_relation_targets(
    db_path: Path,
    *,
    relation_types: list[str],
) -> tuple[int, int]:
    """Count relation rows and distinct targets whose target entity is missing."""
    where_sql, params = _missing_target_where_clause(relation_types)
    with connect_sqlite(db_path) as conn:
        row = conn.execute(
            f"""
            SELECT COUNT(*), COUNT(DISTINCT r.target_id)
            FROM relations r
            INNER JOIN entities src ON src.entity_id = r.entity_id
            LEFT JOIN entities tgt ON tgt.entity_id = r.target_id
            {where_sql}
            """,
            params,
        ).fetchone()
        return int(row[0]), int(row[1])


def list_missing_relation_targets(
    db_path: Path,
    *,
    relation_types: list[str],
    limit: int | None = None,
) -> list[str]:
    """List distinct missing relation targets eligible for reconciliation."""
    where_sql, params = _missing_target_where_clause(relation_types)
    limit_sql = ""
    limit_params: tuple[Any, ...] = ()
    if limit is not None:
        limit_sql = " LIMIT ?"
        limit_params = (int(limit),)

    with connect_sqlite(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT r.target_id
            FROM relations r
            INNER JOIN entities src ON src.entity_id = r.entity_id
            LEFT JOIN entities tgt ON tgt.entity_id = r.target_id
            {where_sql}
            ORDER BY r.target_id
            {limit_sql}
            """,
            (*params, *limit_params),
        ).fetchall()
    return [str(row[0]) for row in rows]


def _missing_target_where_clause(
    relation_types: list[str],
) -> tuple[str, tuple[Any, ...]]:
    relation_types_deduped = [value for value in dict.fromkeys(relation_types) if value]
    if not relation_types_deduped:
        return "WHERE tgt.entity_id IS NULL", ()
    placeholders = ",".join("?" for _ in relation_types_deduped)
    return (
        f"WHERE tgt.entity_id IS NULL AND r.relation_type IN ({placeholders})",
        tuple(relation_types_deduped),
    )


def _name_dedup_key(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("entity_id")),
        str(row.get("name_kind")),
        str(row.get("value_norm")),
        str(row.get("lang") or ""),
        str(row.get("script") or ""),
    )


def _relation_dedup_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("entity_id")),
        str(row.get("relation_type")),
        str(row.get("target_id")),
    )
