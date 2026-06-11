"""SQLite datapack export and subset-selection helpers."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from resolvekit.builder.models import EntityFilter
from resolvekit.builder.sqlite.context import attached_db, connect_sqlite, transaction
from resolvekit.builder.sqlite.specs import insert_prefix
from resolvekit.builder.sqlite.write import ensure_sqlite_schema


def compute_selected_ids(source_db: Path, entity_filter: EntityFilter) -> set[str]:
    """Compute filtered entity IDs for datapack export."""
    with connect_sqlite(source_db, row_factory=sqlite3.Row) as conn:
        selected = _select_ids_by_filter(conn, entity_filter)
        return _expand_relation_targets(conn, selected, entity_filter)


def copy_subset_to_datapack(
    source_db: Path,
    target_db: Path,
    selected_ids: set[str],
    *,
    allowed_targets: set[str] | None = None,
) -> None:
    """Copy selected rows from staging DB into datapack DB.

    When *allowed_targets* is given, relation edges are copied only when their
    ``target_id`` is in that set — dropping edges that point at entities no
    pack ships (e.g. geo ``contained_in`` targets of unshipped place types, or
    OECD channel parents typed ``org.organization``). Pass the union of every
    shipped entity id across all packs (this build plus other domains already
    on disk) so cross-pack and cross-domain edges are preserved. ``None``
    copies every edge from a selected entity regardless of target.
    """
    # Ensure schema exists before opening the write transaction.
    # ``executescript`` autocommits, so schema bootstrap must happen outside.
    ensure_sqlite_schema(target_db)

    with (
        connect_sqlite(target_db, busy_timeout_ms=30000) as conn,
        transaction(conn),
        attached_db(conn, alias="src", db_path=source_db),
    ):
        conn.execute(
            "CREATE TEMP TABLE selected_ids(entity_id TEXT PRIMARY KEY NOT NULL)"
        )
        conn.executemany(
            "INSERT OR IGNORE INTO selected_ids(entity_id) VALUES (?)",
            [(entity_id,) for entity_id in sorted(selected_ids)],
        )
        if allowed_targets is not None:
            conn.execute(
                "CREATE TEMP TABLE allowed_targets(entity_id TEXT PRIMARY KEY NOT NULL)"
            )
            conn.executemany(
                "INSERT OR IGNORE INTO allowed_targets(entity_id) VALUES (?)",
                [(entity_id,) for entity_id in sorted(allowed_targets)],
            )
        conn.execute(
            insert_prefix("entities")
            + """
            SELECT
                e.entity_id, e.entity_type, e.canonical_name, e.canonical_name_norm,
                e.valid_from, e.valid_until, e.attrs_json
            FROM src.entities e
            INNER JOIN selected_ids s ON e.entity_id = s.entity_id
            """
        )
        conn.execute(
            insert_prefix("names")
            + """
            SELECT
                n.entity_id, n.name_kind, n.value, n.value_norm,
                n.lang, n.script, n.is_preferred
            FROM src.names n
            INNER JOIN selected_ids s ON n.entity_id = s.entity_id
            """
        )
        conn.execute(
            insert_prefix("codes")
            + """
            SELECT
                c.entity_id, c.system, c.value, c.value_norm
            FROM src.codes c
            INNER JOIN selected_ids s ON c.entity_id = s.entity_id
            """
        )
        target_filter = (
            "INNER JOIN allowed_targets a ON r.target_id = a.entity_id"
            if allowed_targets is not None
            else ""
        )
        conn.execute(
            insert_prefix("relations")
            + f"""
            SELECT
                r.entity_id, r.relation_type, r.target_id, r.valid_from, r.valid_until
            FROM src.relations r
            INNER JOIN selected_ids s1 ON r.entity_id = s1.entity_id
            {target_filter}
            """
        )
        conn.execute("INSERT INTO names_fts(names_fts) VALUES('rebuild')")


def build_symspell_dictionary(sqlite_path: Path, output_path: Path) -> None:
    """Build SymSpell frequency dictionary from names table."""
    with connect_sqlite(sqlite_path, row_factory=sqlite3.Row) as conn:
        rows = conn.execute(
            """
            SELECT value_norm AS term, COUNT(*) AS c
            FROM names
            GROUP BY value_norm
            ORDER BY c DESC, value_norm ASC
            """
        ).fetchall()
        # Build a single merged dictionary: compound phrases + individual
        # words (for lookup_compound support). Individual word frequencies
        # are summed from the multi-word phrases they appear in.
        all_terms: dict[str, int] = {}
        word_counts: dict[str, int] = defaultdict(int)

        for row in rows:
            term = str(row["term"]).strip()
            if not term:
                continue
            count = int(row["c"])
            all_terms[term] = count
            words = term.split()
            if len(words) >= 2:
                for word in words:
                    if len(word) >= 2:
                        word_counts[word] += count

        # Merge individual words, preferring the higher count when a
        # word already exists as a standalone compound term.
        for word, count in word_counts.items():
            all_terms[word] = max(all_terms.get(word, 0), count)

        with output_path.open("w", encoding="utf-8") as handle:
            for term in sorted(all_terms):
                handle.write(f"{term}\t{all_terms[term]}\n")


def _select_ids_by_filter(
    conn: sqlite3.Connection,
    entity_filter: EntityFilter,
) -> set[str]:
    where_parts: list[str] = ["1=1"]
    params: list[Any] = []

    if entity_filter.include_entity_types:
        placeholders = ",".join("?" for _ in entity_filter.include_entity_types)
        where_parts.append(f"entity_type IN ({placeholders})")
        params.extend(entity_filter.include_entity_types)

    if entity_filter.include_entity_ids:
        placeholders = ",".join("?" for _ in entity_filter.include_entity_ids)
        where_parts.append(f"entity_id IN ({placeholders})")
        params.extend(entity_filter.include_entity_ids)

    if entity_filter.exclude_entity_ids:
        placeholders = ",".join("?" for _ in entity_filter.exclude_entity_ids)
        where_parts.append(f"entity_id NOT IN ({placeholders})")
        params.extend(entity_filter.exclude_entity_ids)

    query = f"SELECT entity_id FROM entities WHERE {' AND '.join(where_parts)}"
    return {str(row["entity_id"]) for row in conn.execute(query, params).fetchall()}


def _expand_relation_targets(
    conn: sqlite3.Connection,
    selected: set[str],
    entity_filter: EntityFilter,
) -> set[str]:
    if not entity_filter.include_relation_targets or not selected:
        return selected

    conn.execute(
        "CREATE TEMP TABLE IF NOT EXISTS tmp_selected(entity_id TEXT PRIMARY KEY)"
    )
    conn.execute("DELETE FROM tmp_selected")
    conn.executemany(
        "INSERT OR IGNORE INTO tmp_selected(entity_id) VALUES (?)",
        [(entity_id,) for entity_id in selected],
    )

    relation_where = ""
    relation_params: list[Any] = []
    if entity_filter.include_relation_types:
        placeholders = ",".join("?" for _ in entity_filter.include_relation_types)
        relation_where = f"WHERE r.relation_type IN ({placeholders})"
        relation_params.extend(entity_filter.include_relation_types)

    rows = conn.execute(
        f"""
        SELECT DISTINCT r.target_id
        FROM relations r
        INNER JOIN tmp_selected s ON s.entity_id = r.entity_id
        {relation_where}
        """,
        relation_params,
    ).fetchall()
    for row in rows:
        selected.add(str(row["target_id"]))
    return selected
