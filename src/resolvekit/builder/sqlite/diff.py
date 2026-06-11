"""SQL-based diff helpers for release changelog artifacts."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from resolvekit.builder.sqlite.constants import SQLITE_IDENTIFIER_RE
from resolvekit.builder.sqlite.context import attached_db, connect_sqlite
from resolvekit.builder.utils import json_write

TABLE_DIFF_SPECS: dict[str, dict[str, list[str]]] = {
    "entities": {
        "pk": ["entity_id"],
        "compare": [
            "entity_type",
            "canonical_name",
            "canonical_name_norm",
            "valid_from",
            "valid_until",
            "attrs_json",
        ],
    },
    "names": {
        "pk": ["entity_id", "name_kind", "value_norm", "lang", "script"],
        "compare": ["value", "is_preferred"],
    },
    "codes": {
        "pk": ["entity_id", "system"],
        "compare": ["value", "value_norm"],
    },
    "relations": {
        "pk": ["entity_id", "relation_type", "target_id"],
        "compare": ["valid_from", "valid_until"],
    },
}


def write_domain_diffs(
    *,
    current_db: Path,
    previous_db: Path | None,
    report_dir: Path,
    max_samples: int = 1000,
) -> dict[str, dict[str, Any]]:
    """Write per-table machine diff files and return diff payloads."""
    diffs: dict[str, dict[str, Any]] = {}
    for table, spec in TABLE_DIFF_SPECS.items():
        diff = compute_table_diff(
            current_db=current_db,
            previous_db=previous_db,
            table=table,
            pk_cols=spec["pk"],
            compare_cols=spec["compare"],
            max_samples=max_samples,
        )
        diffs[table] = diff
        json_write(report_dir / f"diff_{table}.json", diff)
    return diffs


def compute_table_diff(
    *,
    current_db: Path,
    previous_db: Path | None,
    table: str,
    pk_cols: list[str],
    compare_cols: list[str],
    max_samples: int,
) -> dict[str, Any]:
    """Compute added/removed/changed counts and sampled keys for one table."""
    safe_table = quote_identifier(table)
    safe_pk_cols = [quote_identifier(column) for column in pk_cols]
    # Validate (and quote) every compare identifier eagerly — a SQL-injection
    # guard that must run regardless of which branch executes below.
    safe_compare_by_name = {column: quote_identifier(column) for column in compare_cols}

    if previous_db is None or not previous_db.exists():
        count = table_count(current_db, table)
        return {
            "table": table,
            "counts": {"added": count, "removed": 0, "changed": 0},
            "samples": {
                "added": sample_keys(current_db, table, pk_cols, max_samples),
                "removed": [],
                "changed": [],
            },
            "truncated": {
                "added": count > max_samples,
                "removed": False,
                "changed": False,
            },
        }

    with (
        connect_sqlite(current_db, row_factory=sqlite3.Row) as conn,
        attached_db(conn, alias="prev", db_path=previous_db),
    ):
        # Compare only columns present in BOTH tables. A previous pack built
        # under an older schema may lack a column the current build added
        # (e.g. relations.valid_from); diffing it would reference a non-existent
        # ``p.<col>``. Schema additions are not row changes, so dropping such
        # columns from the comparison is the correct changelog behaviour.
        shared_cols = _table_columns(conn, table=table) & _table_columns(
            conn, table=table, schema="prev"
        )
        safe_compare_cols = [
            safe_compare_by_name[column]
            for column in compare_cols
            if column in shared_cols
        ]
        join_cond = " AND ".join([f"c.{col}=p.{col}" for col in safe_pk_cols])
        diff_specs = _diff_query_specs(
            table=safe_table,
            pk_cols=pk_cols,
            compare_cols=safe_compare_cols,
            join_cond=join_cond,
        )

        counts = {"added": 0, "removed": 0, "changed": 0}
        samples: dict[str, list[dict[str, Any]]] = {
            "added": [],
            "removed": [],
            "changed": [],
        }
        for diff_name, queries in diff_specs.items():
            count, sample = _count_and_sample(
                conn=conn,
                count_query=queries["count"],
                sample_query=queries["sample"],
                pk_cols=pk_cols,
                limit=max_samples,
            )
            counts[diff_name] = count
            samples[diff_name] = sample

    return {
        "table": table,
        "counts": counts,
        "samples": samples,
        "truncated": {
            diff_name: counts[diff_name] > max_samples
            for diff_name in ("added", "removed", "changed")
        },
    }


def _diff_query_specs(
    *,
    table: str,
    pk_cols: list[str],
    compare_cols: list[str],
    join_cond: str,
) -> dict[str, dict[str, str]]:
    select_pk_from_current = select_pk_columns("c", pk_cols)
    select_pk_from_previous = select_pk_columns("p", pk_cols)
    missing_prev_cond = f"p.{quote_identifier(pk_cols[0])} IS NULL"
    missing_cur_cond = f"c.{quote_identifier(pk_cols[0])} IS NULL"

    specs = {
        "added": {
            "count": f"""
                SELECT COUNT(*) FROM {table} c
                LEFT JOIN prev.{table} p ON {join_cond}
                WHERE {missing_prev_cond}
            """,
            "sample": f"""
                SELECT {select_pk_from_current}
                FROM {table} c
                LEFT JOIN prev.{table} p ON {join_cond}
                WHERE {missing_prev_cond}
                LIMIT ?
            """,
        },
        "removed": {
            "count": f"""
                SELECT COUNT(*) FROM prev.{table} p
                LEFT JOIN {table} c ON {join_cond}
                WHERE {missing_cur_cond}
            """,
            "sample": f"""
                SELECT {select_pk_from_previous}
                FROM prev.{table} p
                LEFT JOIN {table} c ON {join_cond}
                WHERE {missing_cur_cond}
                LIMIT ?
            """,
        },
    }

    if compare_cols:
        changed_where = " OR ".join(
            [
                f"IFNULL(c.{column}, '') != IFNULL(p.{column}, '')"
                for column in compare_cols
            ]
        )
        specs["changed"] = {
            "count": f"""
                SELECT COUNT(*) FROM {table} c
                INNER JOIN prev.{table} p ON {join_cond}
                WHERE {changed_where}
            """,
            "sample": f"""
                SELECT {select_pk_from_current}
                FROM {table} c
                INNER JOIN prev.{table} p ON {join_cond}
                WHERE {changed_where}
                LIMIT ?
            """,
        }

    return specs


def _count_and_sample(
    *,
    conn: sqlite3.Connection,
    count_query: str,
    sample_query: str,
    pk_cols: list[str],
    limit: int,
) -> tuple[int, list[dict[str, Any]]]:
    count = int(conn.execute(count_query).fetchone()[0])
    samples = sample_diff_keys(
        conn=conn, query=sample_query, pk_cols=pk_cols, limit=limit
    )
    return count, samples


def sample_diff_keys(
    *,
    conn: sqlite3.Connection,
    query: str,
    pk_cols: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Sample primary-key dictionaries for a diff query."""
    rows = conn.execute(query, (limit,)).fetchall()
    return [{column: row[column] for column in pk_cols} for row in rows]


def table_count(db_path: Path, table: str) -> int:
    """Return table row count."""
    safe_table = quote_identifier(table)
    with connect_sqlite(db_path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {safe_table}").fetchone()[0])


def sample_keys(
    db_path: Path,
    table: str,
    pk_cols: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Sample key rows directly from one table."""
    safe_table = quote_identifier(table)
    safe_pk_cols = [quote_identifier(column) for column in pk_cols]
    with connect_sqlite(db_path, row_factory=sqlite3.Row) as conn:
        rows = conn.execute(
            f"""
            SELECT {", ".join(safe_pk_cols)}
            FROM {safe_table}
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [{column: row[column] for column in pk_cols} for row in rows]


def _table_columns(
    conn: sqlite3.Connection, *, table: str, schema: str | None = None
) -> set[str]:
    """Return the column names of *table* (optionally in attached *schema*)."""
    prefix = f"{quote_identifier(schema)}." if schema else ""
    rows = conn.execute(
        f"PRAGMA {prefix}table_info({quote_identifier(table)})"
    ).fetchall()
    return {row[1] for row in rows}


def quote_identifier(value: str) -> str:
    """Validate and quote one SQL identifier."""
    if SQLITE_IDENTIFIER_RE.fullmatch(value) is None:
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    return f'"{value}"'


def select_pk_columns(alias: str, pk_cols: list[str]) -> str:
    """Build ``SELECT`` expression with stable PK aliases."""
    return ", ".join(
        [f'{alias}.{quote_identifier(column)} AS "{column}"' for column in pk_cols]
    )
