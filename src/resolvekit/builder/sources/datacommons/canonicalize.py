"""Post-materialize canonicalization pass for DC-sourced relation targets.

Rewrites raw dcid values stored in the ``relations.target_id`` column to the
canonical ``entity_id`` values used by the rest of the system.  DC returns
targets as raw dcids (e.g. ``geoId/06``, ``zip/94103``); the entities table
stores canonical IDs (e.g. ``country/USA``).  Without this pass every
``contained_in``/``subsidiary_of`` edge produces a dangling reference that
``get_entity(target_id)`` cannot resolve.

Performance contract (required — O(1) statements, not O(edges)):
  1. Build a TEMPORARY TABLE ``_dcid_map`` keyed on the dcid value for O(log n)
     probes — avoids a full-scan of the ``system='dcid'`` codes per row.
  2. Bulk-UPDATE via a JOIN-style subquery; two EXISTS guards keep it idempotent.
  3. Classify the remaining non-canonical targets by prefix in Python over the
     small DISTINCT set.
  4. One bulk-DELETE for the unmodeled prefix set.
  All four steps share a single ``BEGIN IMMEDIATE … COMMIT`` transaction.

Lookup-miss policy:
  - Already canonical (entity_id present in entities) → keep.
  - Maps via dcid → entity_id → rewrite.
  - No map hit, resolvable prefix (``RESOLVABLE_PREFIXES``) → keep verbatim;
    the reconcile stage will hydrate these cross-pack referents.
  - No map hit, unmodeled prefix → DELETE; count recorded in the report.

``RESOLVABLE_PREFIXES`` is the explicit allowlist of prefixes whose targets are
expected to be hydrated at reconcile time or live in another pack.  Everything
else with no map hit is unmodeled (e.g. ``zip``, aggregated DC datasets) and
is dropped with a per-prefix metric.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Relation types that carry DC-sourced targets requiring canonicalization.
_RELATION_TYPES = ("contained_in", "subsidiary_of")

# Prefixes whose unresolved targets are kept for reconcile to hydrate.  The
# set is intentionally small and explicit — anything outside it with no dcid
# map hit is considered unmodeled and is dropped.
RESOLVABLE_PREFIXES: frozenset[str] = frozenset(
    {
        "country",
        "continent",
        "region",
        "geoId",
        "wikidataId",
        "org",
    }
)


def _target_prefix(target_id: str) -> str:
    """Return the prefix part of a target_id (the portion before the first '/')."""
    sep = target_id.find("/")
    return target_id[:sep] if sep != -1 else target_id


@dataclass(frozen=True)
class CanonicalizationReport:
    """Summary of one canonicalization pass over a staging DB."""

    rewritten: int
    kept: int
    dropped_by_prefix: dict[str, int] = field(default_factory=dict)


def canonicalize_relation_targets(*, db_path: Path) -> CanonicalizationReport:
    """Rewrite DC relation target_ids to canonical entity_ids in one staging DB.

    Builds the dcid->entity_id map once, bulk-rewrites resolvable targets,
    drops rows whose target maps to no modeled entity under an unmodeled
    prefix, and returns per-prefix counts. Reads and writes on its own
    connection.

    The pass is idempotent: already-canonical rows no longer match the NOT
    EXISTS guard; already-deleted rows are gone.  Safe to re-run after a
    mid-stage crash.
    """
    _placeholders = ",".join("?" for _ in _RELATION_TYPES)
    _relation_type_filter = f"relation_type IN ({_placeholders})"

    # isolation_level=None puts Python's sqlite3 in autocommit mode so it
    # never opens an implicit transaction that would conflict with our
    # explicit BEGIN IMMEDIATE below.
    conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    conn.execute(f"PRAGMA busy_timeout={30_000}")
    try:
        # Step 1 — Build the dcid→entity_id map in a temporary table keyed on
        # the lookup column so every JOIN probe is O(log n) via the PK index.
        # The temp table is connection-scoped and auto-dropped on close.
        conn.execute("""
            CREATE TEMPORARY TABLE _dcid_map (
                dcid_value TEXT PRIMARY KEY,
                entity_id  TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO _dcid_map (dcid_value, entity_id)
            SELECT value, entity_id FROM codes WHERE system = 'dcid'
        """)

        # Steps 2-4 run inside one write transaction so they are atomic and
        # the database is never in a partial state after a crash.
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Step 2 — Rewrite targets that have a dcid map hit and are not yet
            # canonical.  NOT EXISTS (not NOT IN) is NULL-safe and index-backed.
            cursor = conn.execute(
                f"""
                UPDATE relations
                   SET target_id = (
                       SELECT m.entity_id
                         FROM _dcid_map m
                        WHERE m.dcid_value = relations.target_id
                   )
                 WHERE {_relation_type_filter}
                   AND NOT EXISTS (
                       SELECT 1 FROM entities e
                        WHERE e.entity_id = relations.target_id
                   )
                   AND EXISTS (
                       SELECT 1 FROM _dcid_map m
                        WHERE m.dcid_value = relations.target_id
                   )
                """,
                _RELATION_TYPES,
            )
            rewritten = cursor.rowcount

            # Step 3 — Classify the still-non-canonical remainder by prefix.
            # Runs over the DISTINCT set (small) in Python; no per-edge loop.
            remaining_rows = conn.execute(
                f"""
                SELECT DISTINCT target_id
                  FROM relations
                 WHERE {_relation_type_filter}
                   AND NOT EXISTS (
                       SELECT 1 FROM entities e
                        WHERE e.entity_id = relations.target_id
                   )
                """,
                _RELATION_TYPES,
            ).fetchall()

            unmodeled: list[str] = []
            kept = 0
            for (target_id,) in remaining_rows:
                prefix = _target_prefix(target_id)
                if prefix in RESOLVABLE_PREFIXES:
                    kept += 1
                else:
                    unmodeled.append(target_id)

            # Step 4 — One bulk DELETE for the unmodeled set (not per-edge).
            dropped_by_prefix: dict[str, int] = {}
            if unmodeled:
                # Count per prefix before deletion for the report.
                for target_id in unmodeled:
                    prefix = _target_prefix(target_id)
                    dropped_by_prefix[prefix] = dropped_by_prefix.get(prefix, 0) + 1

                # Use a temp table join for the DELETE to avoid hitting SQLite's
                # SQLITE_MAX_VARIABLE_NUMBER limit on large unmodeled sets.
                conn.execute("""
                    CREATE TEMPORARY TABLE _unmodeled (
                        target_id TEXT PRIMARY KEY
                    )
                """)
                conn.executemany(
                    "INSERT OR IGNORE INTO _unmodeled (target_id) VALUES (?)",
                    [(t,) for t in unmodeled],
                )
                conn.execute(
                    f"""
                    DELETE FROM relations
                     WHERE {_relation_type_filter}
                       AND target_id IN (SELECT target_id FROM _unmodeled)
                    """,
                    _RELATION_TYPES,
                )
                conn.execute("DROP TABLE _unmodeled")

            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()

    return CanonicalizationReport(
        rewritten=rewritten,
        kept=kept,
        dropped_by_prefix=dropped_by_prefix,
    )


def _explain_update_query_plan(conn: sqlite3.Connection) -> list[str]:
    """Return EXPLAIN QUERY PLAN lines for the UPDATE statement (testing aid)."""
    _placeholders = ",".join("?" for _ in _RELATION_TYPES)
    _relation_type_filter = f"relation_type IN ({_placeholders})"
    rows = conn.execute(
        f"""
        EXPLAIN QUERY PLAN
        UPDATE relations
           SET target_id = (
               SELECT m.entity_id
                 FROM _dcid_map m
                WHERE m.dcid_value = relations.target_id
           )
         WHERE {_relation_type_filter}
           AND NOT EXISTS (
               SELECT 1 FROM entities e
                WHERE e.entity_id = relations.target_id
           )
           AND EXISTS (
               SELECT 1 FROM _dcid_map m
                WHERE m.dcid_value = relations.target_id
           )
        """,
        _RELATION_TYPES,
    ).fetchall()
    return [str(row) for row in rows]
