"""Unit tests for the DC relation-target canonicalization pass.

Each test builds a tiny SQLite fixture via the schema helper and
``insert_normalized_payload``, then exercises one branch of
``canonicalize_relation_targets``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from resolvekit.builder.sources.datacommons.canonicalize import (
    RESOLVABLE_PREFIXES,
    CanonicalizationReport,
    canonicalize_relation_targets,
)
from resolvekit.builder.sqlite import (
    ensure_sqlite_schema,
    insert_normalized_payload,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_db(tmp_path: Path, *, name: str = "test.sqlite") -> Path:
    db_path = tmp_path / name
    ensure_sqlite_schema(db_path)
    return db_path


def _seed(
    db_path: Path,
    *,
    entities: list[dict] | None = None,
    codes: list[dict] | None = None,
    relations: list[dict] | None = None,
) -> None:
    """Insert rows into a fixture DB."""
    insert_normalized_payload(
        db_path,
        {
            "entities": entities or [],
            "names": [],
            "codes": codes or [],
            "relations": relations or [],
        },
    )


def _fetch_target_ids(db_path: Path, *, entity_id: str) -> list[str]:
    from resolvekit.builder.sqlite.context import connect_sqlite

    with connect_sqlite(db_path) as conn:
        rows = conn.execute(
            "SELECT target_id FROM relations WHERE entity_id = ? ORDER BY target_id",
            (entity_id,),
        ).fetchall()
    return [str(r[0]) for r in rows]


def _count_relations(db_path: Path) -> int:
    from resolvekit.builder.sqlite.context import connect_sqlite

    with connect_sqlite(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_lookup_hit_rewrites_target_id(tmp_path: Path) -> None:
    """A target whose raw dcid maps to a known entity_id is rewritten."""
    db_path = _make_db(tmp_path)

    # The canonical target entity; its dcid code maps raw "country/US" → "country/USA".
    _seed(
        db_path,
        entities=[
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
        codes=[
            {
                "entity_id": "country/USA",
                "system": "dcid",
                "value": "country/US",  # raw dcid that DC emits as parent target
                "value_norm": "country/us",
            }
        ],
    )

    # A child entity whose relation points at the raw dcid "country/US".
    # The canonical entity_id is "country/USA" — the pass should rewrite it.
    _seed(
        db_path,
        entities=[
            {
                "entity_id": "geoId/06",
                "entity_type": "geo.admin1",
                "canonical_name": "California",
                "canonical_name_norm": "california",
                "valid_from": None,
                "valid_until": None,
                "attrs_json": {},
            }
        ],
        relations=[
            {
                "entity_id": "geoId/06",
                "relation_type": "contained_in",
                "target_id": "country/US",  # raw dcid — must be rewritten
                "valid_from": None,
                "valid_until": None,
            }
        ],
    )

    report = canonicalize_relation_targets(db_path=db_path)

    targets = _fetch_target_ids(db_path, entity_id="geoId/06")
    assert "country/US" not in targets, "raw dcid must be rewritten"
    assert "country/USA" in targets, "rewritten to canonical entity_id"
    assert report.rewritten == 1
    assert isinstance(report, CanonicalizationReport)


def test_already_canonical_unchanged(tmp_path: Path) -> None:
    """A target already present in entities is left untouched."""
    db_path = _make_db(tmp_path)

    _seed(
        db_path,
        entities=[
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
        ],
        codes=[
            {
                "entity_id": "country/CAN",
                "system": "dcid",
                "value": "country/CAN",
                "value_norm": "country/can",
            },
        ],
        relations=[
            {
                "entity_id": "country/CAN",
                "relation_type": "contained_in",
                "target_id": "country/USA",  # already a valid entity_id
                "valid_from": None,
                "valid_until": None,
            }
        ],
    )

    report = canonicalize_relation_targets(db_path=db_path)

    targets = _fetch_target_ids(db_path, entity_id="country/CAN")
    assert targets == ["country/USA"], "already-canonical target must not be touched"
    assert report.rewritten == 0


def test_resolvable_prefix_miss_kept(tmp_path: Path) -> None:
    """A target with a resolvable prefix and no map hit is kept verbatim."""
    db_path = _make_db(tmp_path)

    _seed(
        db_path,
        entities=[
            {
                "entity_id": "country/CAN",
                "entity_type": "geo.country",
                "canonical_name": "Canada",
                "canonical_name_norm": "canada",
                "valid_from": None,
                "valid_until": None,
                "attrs_json": {},
            }
        ],
        codes=[
            {
                "entity_id": "country/CAN",
                "system": "dcid",
                "value": "country/CAN",
                "value_norm": "country/can",
            }
        ],
        relations=[
            {
                "entity_id": "country/CAN",
                "relation_type": "contained_in",
                # geoId/9999 has a resolvable prefix but no map hit — keep for reconcile.
                "target_id": "geoId/9999",
                "valid_from": None,
                "valid_until": None,
            }
        ],
    )

    report = canonicalize_relation_targets(db_path=db_path)

    targets = _fetch_target_ids(db_path, entity_id="country/CAN")
    assert "geoId/9999" in targets, "resolvable-prefix miss must be kept for reconcile"
    assert report.rewritten == 0
    assert "geoId" not in report.dropped_by_prefix


def test_unmodeled_prefix_dropped_with_metric(tmp_path: Path) -> None:
    """A target with an unmodeled prefix is deleted and counted in the report."""
    db_path = _make_db(tmp_path)

    _seed(
        db_path,
        entities=[
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
        codes=[
            {
                "entity_id": "country/USA",
                "system": "dcid",
                "value": "country/USA",
                "value_norm": "country/usa",
            }
        ],
        relations=[
            {
                "entity_id": "country/USA",
                "relation_type": "contained_in",
                "target_id": "zip/94103",  # unmodeled prefix — must be dropped
                "valid_from": None,
                "valid_until": None,
            }
        ],
    )

    before = _count_relations(db_path)
    assert before == 1

    report = canonicalize_relation_targets(db_path=db_path)

    after = _count_relations(db_path)
    assert after == 0, "unmodeled-prefix row must be deleted"
    assert report.dropped_by_prefix.get("zip") == 1
    assert report.rewritten == 0


def test_mixed_targets_classified_correctly(tmp_path: Path) -> None:
    """Multiple target types are handled in one pass without per-edge round-trips."""
    db_path = _make_db(tmp_path)

    # Canonical target entity
    _seed(
        db_path,
        entities=[
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
        ],
        codes=[
            # country/USA's raw dcid is "country/US"; the map resolves it to
            # the canonical entity_id "country/USA".
            {
                "entity_id": "country/USA",
                "system": "dcid",
                "value": "country/US",
                "value_norm": "country/us",
            },
        ],
    )

    from resolvekit.builder.sqlite.context import connect_sqlite

    with connect_sqlite(db_path) as conn:
        # Entity with four different relation target shapes in one pass
        conn.execute(
            "INSERT OR IGNORE INTO entities"
            "(entity_id, entity_type, canonical_name, canonical_name_norm) "
            "VALUES (?, ?, ?, ?)",
            ("geoId/06", "geo.admin1", "California", "california"),
        )
        rows = [
            ("geoId/06", "contained_in", "country/US"),  # dcid hit → rewrite
            ("geoId/06", "contained_in", "region/NAM"),  # already canonical → keep
            ("geoId/06", "contained_in", "geoId/9999"),  # resolvable miss → keep
            ("geoId/06", "contained_in", "zip/94103"),  # unmodeled → drop
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO relations(entity_id, relation_type, target_id) "
            "VALUES (?, ?, ?)",
            rows,
        )
        conn.commit()

    report = canonicalize_relation_targets(db_path=db_path)

    targets = set(_fetch_target_ids(db_path, entity_id="geoId/06"))
    assert "country/USA" in targets, "dcid hit must be rewritten to canonical"
    assert "country/US" not in targets, "raw dcid must not remain after rewrite"
    assert "region/NAM" in targets, "already-canonical must be kept"
    assert "geoId/9999" in targets, "resolvable-prefix miss must be kept"
    assert "zip/94103" not in targets, "unmodeled prefix must be dropped"

    assert report.rewritten == 1
    assert report.kept == 1  # geoId/9999
    assert report.dropped_by_prefix.get("zip") == 1


def test_report_is_frozen_dataclass() -> None:
    """CanonicalizationReport is a frozen dataclass (immutable)."""
    r = CanonicalizationReport(rewritten=5, kept=3, dropped_by_prefix={"zip": 2})
    assert r.rewritten == 5
    assert r.kept == 3
    assert r.dropped_by_prefix == {"zip": 2}
    with pytest.raises((AttributeError, TypeError)):
        r.rewritten = 0  # type: ignore[misc]


def test_idempotent_rerun(tmp_path: Path) -> None:
    """Running canonicalize twice on the same DB produces the same result."""
    db_path = _make_db(tmp_path)

    _seed(
        db_path,
        entities=[
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
        codes=[
            {
                "entity_id": "country/USA",
                "system": "dcid",
                "value": "country/US",
                "value_norm": "country/us",
            }
        ],
        relations=[
            {
                "entity_id": "country/USA",
                "relation_type": "contained_in",
                "target_id": "country/US",
                "valid_from": None,
                "valid_until": None,
            }
        ],
    )

    report1 = canonicalize_relation_targets(db_path=db_path)
    report2 = canonicalize_relation_targets(db_path=db_path)

    assert report1.rewritten == 1
    # Second run: target is already canonical; NOT EXISTS guard skips it.
    assert report2.rewritten == 0
    assert report2.kept == 0
    assert report2.dropped_by_prefix == {}


def test_resolvable_prefixes_allowlist() -> None:
    """RESOLVABLE_PREFIXES is a frozenset and contains the expected values."""
    assert isinstance(RESOLVABLE_PREFIXES, frozenset)
    for prefix in ("country", "continent", "region", "geoId", "wikidataId", "org"):
        assert prefix in RESOLVABLE_PREFIXES
    # Unmodeled prefixes must NOT be in the allowlist
    for prefix in ("zip", "county", "tract"):
        assert prefix not in RESOLVABLE_PREFIXES
