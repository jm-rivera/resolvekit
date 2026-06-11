"""SQLite validation helpers for staged and packaged domain artifacts."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from resolvekit.builder.sqlite.context import connect_sqlite

REQUIRED_TABLES = {"entities", "names", "codes", "relations", "names_fts"}


@dataclass(frozen=True, slots=True, kw_only=True)
class IntegrityCheck:
    """One named domain-count integrity check."""

    message_template: str
    query: str


_DOMAIN_COUNT_CHECKS: tuple[IntegrityCheck, ...] = (
    IntegrityCheck(
        message_template="Found {count} entities with empty canonical_name",
        query="""
        SELECT COUNT(*) FROM entities
        WHERE canonical_name IS NULL OR TRIM(canonical_name) = ''
        """,
    ),
    IntegrityCheck(
        message_template="Found {count} entities with empty entity_type",
        query="""
        SELECT COUNT(*) FROM entities
        WHERE entity_type IS NULL OR TRIM(entity_type) = ''
        """,
    ),
    IntegrityCheck(
        message_template="Found {count} names referencing missing entities",
        query="""
        SELECT COUNT(*) FROM names n
        LEFT JOIN entities e ON n.entity_id = e.entity_id
        WHERE e.entity_id IS NULL
        """,
    ),
    IntegrityCheck(
        message_template="Found {count} names with empty required fields",
        query="""
        SELECT COUNT(*) FROM names
        WHERE entity_id IS NULL OR TRIM(entity_id) = ''
          OR name_kind IS NULL OR TRIM(name_kind) = ''
          OR value IS NULL OR TRIM(value) = ''
          OR value_norm IS NULL OR TRIM(value_norm) = ''
        """,
    ),
    IntegrityCheck(
        message_template="Found {count} codes referencing missing entities",
        query="""
        SELECT COUNT(*) FROM codes c
        LEFT JOIN entities e ON c.entity_id = e.entity_id
        WHERE e.entity_id IS NULL
        """,
    ),
    IntegrityCheck(
        message_template="Found {count} codes with empty required fields",
        query="""
        SELECT COUNT(*) FROM codes
        WHERE entity_id IS NULL OR TRIM(entity_id) = ''
          OR system IS NULL OR TRIM(system) = ''
          OR value IS NULL OR TRIM(value) = ''
          OR value_norm IS NULL OR TRIM(value_norm) = ''
        """,
    ),
    IntegrityCheck(
        message_template="Found {count} relations with empty required fields",
        query="""
        SELECT COUNT(*) FROM relations
        WHERE entity_id IS NULL OR TRIM(entity_id) = ''
          OR relation_type IS NULL OR TRIM(relation_type) = ''
          OR target_id IS NULL OR TRIM(target_id) = ''
        """,
    ),
)


def validate_domain_db(
    db_path: Path,
    *,
    allow_external_relation_targets: bool = False,
) -> tuple[dict[str, float | int], list[str]]:
    """Run structural and coverage checks for a domain database."""
    with connect_sqlite(db_path, row_factory=sqlite3.Row) as conn:
        issues = _collect_domain_issues(
            conn,
            allow_external_relation_targets=allow_external_relation_targets,
        )

        entity_count = _count(conn, "SELECT COUNT(*) FROM entities")
        names_count = _count(conn, "SELECT COUNT(*) FROM names")
        codes_count = _count(conn, "SELECT COUNT(*) FROM codes")
        relations_count = _count(conn, "SELECT COUNT(*) FROM relations")
        entities_with_names = _count(
            conn, "SELECT COUNT(DISTINCT entity_id) FROM names"
        )
        entities_with_codes = _count(
            conn, "SELECT COUNT(DISTINCT entity_id) FROM codes"
        )

    metrics = {
        "entity_count": entity_count,
        "names_count": names_count,
        "codes_count": codes_count,
        "relations_count": relations_count,
        "names_coverage": entities_with_names / entity_count if entity_count else 0.0,
        "codes_coverage": entities_with_codes / entity_count if entity_count else 0.0,
        "relations_density": relations_count / entity_count if entity_count else 0.0,
    }
    return metrics, issues


def _collect_domain_issues(
    conn: sqlite3.Connection,
    *,
    allow_external_relation_targets: bool,
) -> list[str]:
    issues: list[str] = []
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        ).fetchall()
    }
    missing = REQUIRED_TABLES - tables
    if missing:
        issues.append(f"Missing tables: {sorted(missing)}")

    for check in _DOMAIN_COUNT_CHECKS:
        count = _count(conn, check.query)
        if count > 0:
            issues.append(check.message_template.format(count=count))

    relation_query = (
        """
        SELECT COUNT(*) FROM relations r
        LEFT JOIN entities e1 ON r.entity_id = e1.entity_id
        WHERE e1.entity_id IS NULL
        """
        if allow_external_relation_targets
        else """
        SELECT COUNT(*) FROM relations r
        LEFT JOIN entities e1 ON r.entity_id = e1.entity_id
        LEFT JOIN entities e2 ON r.target_id = e2.entity_id
        WHERE e1.entity_id IS NULL OR e2.entity_id IS NULL
        """
    )
    relation_count = _count(conn, relation_query)
    if relation_count > 0:
        issues.append(
            (
                "Found {count} relations referencing missing source entities"
                if allow_external_relation_targets
                else "Found {count} relations referencing missing entities"
            ).format(count=relation_count)
        )

    if "names_fts" in tables:
        fts_count = _count(conn, "SELECT COUNT(*) FROM names_fts")
        names_count = _count(conn, "SELECT COUNT(*) FROM names")
        if fts_count != names_count:
            issues.append(f"FTS mismatch: names_fts={fts_count}, names={names_count}")

    return issues


def _count(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> int:
    return int(conn.execute(query, params).fetchone()[0])
