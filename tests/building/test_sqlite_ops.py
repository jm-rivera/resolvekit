"""Unit tests for sqlite filter and validation helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from resolvekit.builder.models import EntityFilter
from resolvekit.builder.sqlite import (
    compute_selected_ids,
    copy_subset_to_datapack,
    count_missing_relation_targets,
    ensure_sqlite_schema,
    insert_normalized_payload,
    list_missing_relation_targets,
    validate_domain_db,
)


def build_source_db(path: Path) -> Path:
    """Create a source SQLite DB with geo entities and relations."""
    db_path = path / "source.sqlite"
    ensure_sqlite_schema(db_path)

    insert_normalized_payload(
        db_path,
        {
            "entities": [
                {
                    "entity_id": "region/NAM",
                    "entity_type": "geo.region",
                    "canonical_name": "North America",
                    "canonical_name_norm": "north america",
                    "valid_from": None,
                    "valid_until": None,
                    "attrs_json": {},
                },
                {
                    "entity_id": "country/USA",
                    "entity_type": "geo.country",
                    "canonical_name": "United States",
                    "canonical_name_norm": "united states",
                    "valid_from": None,
                    "valid_until": None,
                    "attrs_json": {},
                },
                {
                    "entity_id": "country/CAN",
                    "entity_type": "geo.country",
                    "canonical_name": "Canada",
                    "canonical_name_norm": "canada",
                    "valid_from": None,
                    "valid_until": None,
                    "attrs_json": {},
                },
                {
                    "entity_id": "city/Toronto",
                    "entity_type": "geo.city",
                    "canonical_name": "Toronto",
                    "canonical_name_norm": "toronto",
                    "valid_from": None,
                    "valid_until": None,
                    "attrs_json": {},
                },
            ],
            "names": [
                {
                    "entity_id": "country/USA",
                    "name_kind": "canonical",
                    "value": "United States",
                    "value_norm": "united states",
                    "lang": "en",
                    "script": None,
                    "is_preferred": 1,
                },
                {
                    "entity_id": "country/CAN",
                    "name_kind": "canonical",
                    "value": "Canada",
                    "value_norm": "canada",
                    "lang": "en",
                    "script": None,
                    "is_preferred": 1,
                },
                {
                    "entity_id": "city/Toronto",
                    "name_kind": "canonical",
                    "value": "Toronto",
                    "value_norm": "toronto",
                    "lang": "en",
                    "script": None,
                    "is_preferred": 1,
                },
            ],
            "codes": [
                {
                    "entity_id": "country/USA",
                    "system": "iso2",
                    "value": "US",
                    "value_norm": "us",
                },
                {
                    "entity_id": "country/CAN",
                    "system": "iso2",
                    "value": "CA",
                    "value_norm": "ca",
                },
            ],
            "relations": [
                {
                    "entity_id": "country/USA",
                    "relation_type": "contained_in",
                    "target_id": "region/NAM",
                },
                {
                    "entity_id": "country/CAN",
                    "relation_type": "contained_in",
                    "target_id": "region/NAM",
                },
                {
                    "entity_id": "city/Toronto",
                    "relation_type": "contained_in",
                    "target_id": "country/CAN",
                },
            ],
        },
    )
    return db_path


def test_recipe_filter_countries_only(tmp_path: Path) -> None:
    source_db = build_source_db(tmp_path)
    selected = compute_selected_ids(
        source_db,
        EntityFilter(
            include_entity_types=["geo.country"],
            include_relation_targets=False,
        ),
    )
    assert selected == {"country/USA", "country/CAN"}


def test_recipe_filter_regions_and_countries(tmp_path: Path) -> None:
    source_db = build_source_db(tmp_path)
    selected = compute_selected_ids(
        source_db,
        EntityFilter(
            include_entity_types=["geo.region", "geo.country"],
            include_relation_targets=False,
        ),
    )
    assert selected == {"region/NAM", "country/USA", "country/CAN"}


def test_recipe_filter_geo_all_default(tmp_path: Path) -> None:
    source_db = build_source_db(tmp_path)
    selected = compute_selected_ids(source_db, EntityFilter())
    assert selected == {"region/NAM", "country/USA", "country/CAN", "city/Toronto"}


def test_recipe_filter_relation_target_expansion(tmp_path: Path) -> None:
    source_db = build_source_db(tmp_path)
    selected = compute_selected_ids(
        source_db,
        EntityFilter(
            include_entity_ids=["city/Toronto"],
            include_relation_targets=True,
            include_relation_types=["contained_in"],
        ),
    )
    assert selected == {"city/Toronto", "country/CAN"}


def _packed_relations(target_db: Path) -> set[tuple[str, str]]:
    with sqlite3.connect(target_db) as conn:
        return {
            (entity_id, target_id)
            for entity_id, target_id in conn.execute(
                "SELECT entity_id, target_id FROM relations"
            )
        }


def test_copy_subset_keeps_all_edges_without_allowed_targets(tmp_path: Path) -> None:
    source_db = build_source_db(tmp_path)
    target_db = tmp_path / "pack.sqlite"
    # Countries pack: edges point at region/NAM, which is not in the pack.
    copy_subset_to_datapack(source_db, target_db, {"country/USA", "country/CAN"})
    assert _packed_relations(target_db) == {
        ("country/USA", "region/NAM"),
        ("country/CAN", "region/NAM"),
    }


def test_copy_subset_drops_edges_to_unshipped_targets(tmp_path: Path) -> None:
    source_db = build_source_db(tmp_path)
    target_db = tmp_path / "pack.sqlite"
    # region/NAM ships nowhere → its inbound contained_in edges are dropped.
    copy_subset_to_datapack(
        source_db,
        target_db,
        {"country/USA", "country/CAN"},
        allowed_targets={"country/USA", "country/CAN"},
    )
    assert _packed_relations(target_db) == set()


def test_copy_subset_keeps_cross_pack_edges_in_allowed_targets(tmp_path: Path) -> None:
    source_db = build_source_db(tmp_path)
    target_db = tmp_path / "pack.sqlite"
    # region/NAM ships in another pack → cross-pack edges survive.
    copy_subset_to_datapack(
        source_db,
        target_db,
        {"country/USA", "country/CAN"},
        allowed_targets={"country/USA", "country/CAN", "region/NAM"},
    )
    assert _packed_relations(target_db) == {
        ("country/USA", "region/NAM"),
        ("country/CAN", "region/NAM"),
    }


def test_validate_domain_db_detects_required_field_issues(tmp_path: Path) -> None:
    db_path = tmp_path / "broken.sqlite"
    ensure_sqlite_schema(db_path)
    insert_normalized_payload(
        db_path,
        {
            "entities": [
                {
                    "entity_id": "country/USA",
                    "entity_type": "",
                    "canonical_name": "United States",
                    "canonical_name_norm": "united states",
                    "valid_from": None,
                    "valid_until": None,
                    "attrs_json": {},
                }
            ],
            "names": [
                {
                    "entity_id": "country/USA",
                    "name_kind": "",
                    "value": "",
                    "value_norm": "",
                    "lang": "en",
                    "script": None,
                    "is_preferred": 1,
                }
            ],
            "codes": [
                {
                    "entity_id": "country/USA",
                    "system": "",
                    "value": "",
                    "value_norm": "",
                }
            ],
            "relations": [
                {
                    "entity_id": "country/USA",
                    "relation_type": "",
                    "target_id": "",
                }
            ],
        },
    )

    _metrics, issues = validate_domain_db(db_path)

    assert any("entities with empty entity_type" in issue for issue in issues)
    assert any("names with empty required fields" in issue for issue in issues)
    assert any("codes with empty required fields" in issue for issue in issues)
    assert any("relations with empty required fields" in issue for issue in issues)


def test_missing_relation_target_helpers_scope_by_relation_type(tmp_path: Path) -> None:
    db_path = tmp_path / "missing_targets.sqlite"
    ensure_sqlite_schema(db_path)
    insert_normalized_payload(
        db_path,
        {
            "entities": [
                {
                    "entity_id": "country/USA",
                    "entity_type": "geo.country",
                    "canonical_name": "United States",
                    "canonical_name_norm": "united states",
                    "valid_from": None,
                    "valid_until": None,
                    "attrs_json": {},
                }
            ],
            "names": [],
            "codes": [],
            "relations": [
                {
                    "entity_id": "country/USA",
                    "relation_type": "contained_in",
                    "target_id": "region/NAM",
                },
                {
                    "entity_id": "country/USA",
                    "relation_type": "member_of",
                    "target_id": "org/UN",
                },
            ],
        },
    )

    assert count_missing_relation_targets(
        db_path,
        relation_types=["contained_in"],
    ) == (1, 1)
    assert count_missing_relation_targets(
        db_path,
        relation_types=["contained_in", "member_of"],
    ) == (2, 2)
    assert list_missing_relation_targets(
        db_path,
        relation_types=["contained_in", "member_of"],
    ) == ["org/UN", "region/NAM"]


def test_ensure_sqlite_schema_repairs_partial_existing_db(tmp_path: Path) -> None:
    db_path = tmp_path / "partial.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE sentinel(id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()

    ensure_sqlite_schema(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
        }
    finally:
        conn.close()

    assert {"entities", "names", "codes", "relations", "names_fts"} <= tables


def test_insert_normalized_payload_dedupes_duplicate_names_and_relations(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "dedupe.sqlite"
    ensure_sqlite_schema(db_path)

    payload = {
        "entities": [
            {
                "entity_id": "country/USA",
                "entity_type": "geo.country",
                "canonical_name": "United States",
                "canonical_name_norm": "united states",
                "valid_from": None,
                "valid_until": None,
                "attrs_json": {},
            }
        ],
        "names": [
            {
                "entity_id": "country/USA",
                "name_kind": "canonical",
                "value": "United States",
                "value_norm": "united states",
                "lang": "en",
                "script": "",
                "is_preferred": 1,
            }
        ],
        "codes": [],
        "relations": [
            {
                "entity_id": "country/USA",
                "relation_type": "contained_in",
                "target_id": "region/NAM",
            }
        ],
    }

    insert_normalized_payload(db_path, payload)
    insert_normalized_payload(db_path, payload)

    conn = sqlite3.connect(db_path)
    try:
        names_count = int(conn.execute("SELECT COUNT(*) FROM names").fetchone()[0])
        relations_count = int(
            conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
        )
    finally:
        conn.close()

    assert names_count == 1
    assert relations_count == 1


def test_copy_subset_to_datapack_rolls_back_on_mid_copy_failure(tmp_path: Path) -> None:
    source_db = tmp_path / "source_missing_relations.sqlite"
    target_db = tmp_path / "target.sqlite"

    conn = sqlite3.connect(source_db)
    try:
        conn.executescript(
            """
            CREATE TABLE entities(
                entity_id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                canonical_name TEXT NOT NULL,
                canonical_name_norm TEXT NOT NULL,
                valid_from TEXT,
                valid_until TEXT,
                attrs_json TEXT
            );
            CREATE TABLE names(
                entity_id TEXT NOT NULL,
                name_kind TEXT NOT NULL,
                value TEXT NOT NULL,
                value_norm TEXT NOT NULL,
                lang TEXT NOT NULL DEFAULT '',
                script TEXT NOT NULL DEFAULT '',
                is_preferred INTEGER DEFAULT 0
            );
            CREATE TABLE codes(
                entity_id TEXT NOT NULL,
                system TEXT NOT NULL,
                value TEXT NOT NULL,
                value_norm TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO entities(
                entity_id, entity_type, canonical_name, canonical_name_norm,
                valid_from, valid_until, attrs_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "country/USA",
                "geo.country",
                "United States",
                "united states",
                None,
                None,
                "{}",
            ),
        )
        conn.execute(
            """
            INSERT INTO names(
                entity_id, name_kind, value, value_norm, lang, script, is_preferred
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("country/USA", "canonical", "United States", "united states", "en", "", 1),
        )
        conn.execute(
            """
            INSERT INTO codes(entity_id, system, value, value_norm)
            VALUES (?, ?, ?, ?)
            """,
            ("country/USA", "iso2", "US", "us"),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        copy_subset_to_datapack(source_db, target_db, {"country/USA"})
        raise AssertionError(
            "copy_subset_to_datapack should fail without src.relations table"
        )
    except sqlite3.OperationalError as exc:
        assert "relations" in str(exc).lower()

    conn = sqlite3.connect(target_db)
    try:
        entities = int(conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0])
        names = int(conn.execute("SELECT COUNT(*) FROM names").fetchone()[0])
        codes = int(conn.execute("SELECT COUNT(*) FROM codes").fetchone()[0])
    finally:
        conn.close()

    assert entities == 0
    assert names == 0
    assert codes == 0
