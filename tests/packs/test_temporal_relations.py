"""Unit tests for RelationRecord temporal fields and temporal store methods.

Tests:
- RelationRecord round-trip for valid_from/valid_until (str | None)
- SQLiteEntityStore.get_relations_as_of boundary cases (left-closed, half-open right)
- GeoMembershipConstraint dispatches to get_relations_as_of vs get_relations
"""

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from resolvekit.core.model.entity import RelationRecord

# ---------------------------------------------------------------------------
# RelationRecord field tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_relation_record_temporal_fields() -> None:
    """Temporal fields round-trip as ISO-8601 strings."""
    r = RelationRecord(
        relation_type="member_of",
        target_id="g/X",
        valid_from="2020-01-01",
        valid_until="2024-12-31",
    )
    assert r.valid_from == "2020-01-01"
    assert r.valid_until == "2024-12-31"


@pytest.mark.unit
def test_relation_record_null_temporal_fields() -> None:
    """Null temporal fields default to None."""
    r = RelationRecord(relation_type="member_of", target_id="g/X")
    assert r.valid_from is None
    assert r.valid_until is None


# ---------------------------------------------------------------------------
# Helpers: minimal SQLite DB for store tests
# ---------------------------------------------------------------------------

_MINIMAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    entity_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    canonical_name_norm TEXT NOT NULL,
    valid_from TEXT,
    valid_until TEXT,
    attrs_json TEXT
);
CREATE TABLE IF NOT EXISTS names (
    entity_id TEXT NOT NULL,
    name_kind TEXT NOT NULL,
    value TEXT NOT NULL,
    value_norm TEXT NOT NULL,
    lang TEXT NOT NULL DEFAULT '',
    script TEXT NOT NULL DEFAULT '',
    is_preferred INTEGER DEFAULT 0,
    PRIMARY KEY (entity_id, name_kind, value_norm, lang, script)
);
CREATE TABLE IF NOT EXISTS codes (
    entity_id TEXT NOT NULL,
    system TEXT NOT NULL,
    value TEXT NOT NULL,
    value_norm TEXT NOT NULL,
    PRIMARY KEY (entity_id, system)
);
CREATE TABLE IF NOT EXISTS relations (
    entity_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    valid_from TEXT,
    valid_until TEXT,
    PRIMARY KEY (entity_id, relation_type, target_id)
);
CREATE VIRTUAL TABLE IF NOT EXISTS names_fts
    USING fts5(entity_id, value_norm);
"""


def _build_test_db(
    tmp_path: Path,
    valid_from: str | None,
    valid_until: str | None,
) -> Path:
    """Build a minimal SQLite DB with one entity and one timed relation."""
    db_path = tmp_path / "test.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(_MINIMAL_SCHEMA)
    conn.execute(
        "INSERT INTO entities VALUES (?, ?, ?, ?, NULL, NULL, NULL)",
        ("country/SRC", "geo.country", "Source", "source"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO relations VALUES (?, ?, ?, ?, ?)",
        ("country/SRC", "member_of", "group/TARGET", valid_from, valid_until),
    )
    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# get_relations_as_of boundary tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_relations_as_of_in_range(tmp_path: Path) -> None:
    """Date inside [valid_from, valid_until) returns the target."""
    from resolvekit.core.store.sqlite import SQLiteEntityStore

    db_path = _build_test_db(tmp_path, "2020-01-01", "2025-01-01")
    store = SQLiteEntityStore(db_path)
    try:
        result = store.get_relations_as_of("country/SRC", "member_of", date(2022, 6, 1))
        assert "group/TARGET" in result
    finally:
        store.close()


@pytest.mark.unit
def test_get_relations_as_of_at_valid_from(tmp_path: Path) -> None:
    """Boundary: as_of == valid_from returns target (left-closed)."""
    from resolvekit.core.store.sqlite import SQLiteEntityStore

    db_path = _build_test_db(tmp_path, "2020-01-01", "2025-01-01")
    store = SQLiteEntityStore(db_path)
    try:
        result = store.get_relations_as_of("country/SRC", "member_of", date(2020, 1, 1))
        assert "group/TARGET" in result
    finally:
        store.close()


@pytest.mark.unit
def test_get_relations_as_of_before_valid_from(tmp_path: Path) -> None:
    """Date before valid_from returns empty list."""
    from resolvekit.core.store.sqlite import SQLiteEntityStore

    db_path = _build_test_db(tmp_path, "2020-01-01", "2025-01-01")
    store = SQLiteEntityStore(db_path)
    try:
        result = store.get_relations_as_of(
            "country/SRC", "member_of", date(2019, 12, 31)
        )
        assert result == []
    finally:
        store.close()


@pytest.mark.unit
def test_get_relations_as_of_at_valid_until(tmp_path: Path) -> None:
    """Boundary: as_of == valid_until returns empty (half-open right)."""
    from resolvekit.core.store.sqlite import SQLiteEntityStore

    db_path = _build_test_db(tmp_path, "2020-01-01", "2025-01-01")
    store = SQLiteEntityStore(db_path)
    try:
        # valid_until > ? is False when as_of == valid_until
        result = store.get_relations_as_of("country/SRC", "member_of", date(2025, 1, 1))
        assert result == []
    finally:
        store.close()


@pytest.mark.unit
def test_get_relations_as_of_after_valid_until(tmp_path: Path) -> None:
    """Date after valid_until returns empty list."""
    from resolvekit.core.store.sqlite import SQLiteEntityStore

    db_path = _build_test_db(tmp_path, "2020-01-01", "2025-01-01")
    store = SQLiteEntityStore(db_path)
    try:
        result = store.get_relations_as_of("country/SRC", "member_of", date(2026, 1, 1))
        assert result == []
    finally:
        store.close()


@pytest.mark.unit
def test_get_relations_as_of_null_bounds(tmp_path: Path) -> None:
    """Null valid_from and valid_until means always-valid: any as_of returns target."""
    from resolvekit.core.store.sqlite import SQLiteEntityStore

    db_path = _build_test_db(tmp_path, None, None)
    store = SQLiteEntityStore(db_path)
    try:
        for check_date in [date(1900, 1, 1), date(2022, 6, 1), date(2099, 12, 31)]:
            result = store.get_relations_as_of("country/SRC", "member_of", check_date)
            assert "group/TARGET" in result, f"Expected target for as_of={check_date}"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# GeoMembershipConstraint dispatch tests
# ---------------------------------------------------------------------------


def _make_candidate(entity_id: str):  # type: ignore[no-untyped-def]
    from resolvekit.core.model import (
        Candidate,
        CandidateEvidence,
        RetrievalSummary,
        ScoreSummary,
    )

    return Candidate(
        entity_id=entity_id,
        sources=[
            CandidateEvidence(entity_id=entity_id, source_name="test", raw_score=1.0)
        ],
        retrieval=RetrievalSummary(best_source="test"),
        scores=ScoreSummary(raw_score=0.9, calibrated_score=0.9),
    )


@pytest.mark.unit
def test_geo_membership_constraint_temporal() -> None:
    """With context.as_of set, constraint calls get_relations_as_of."""
    from unittest.mock import MagicMock

    from resolvekit.core.explain import NullTraceSink
    from resolvekit.core.model import ResolutionContext
    from resolvekit.core.store import EntityStore
    from resolvekit.packs.geo.constraints.membership import GeoMembershipConstraint

    store = MagicMock(spec=EntityStore)
    store.get_relations_as_of.return_value = ["group/EU"]
    store.get_relations.return_value = []

    constraint = GeoMembershipConstraint()
    context = ResolutionContext(
        as_of=date(2018, 6, 1),
        attributes={"membership_org": "group/EU"},
    )

    from resolvekit.core.model import NormalizedText, Query

    query = Query(
        raw_text="Germany",
        normalized=NormalizedText(original="Germany", normalized="germany"),
    )
    candidates = [_make_candidate("country/DEU")]
    constraint.apply(query, context, candidates, store, NullTraceSink())

    store.get_relations_as_of.assert_called_once_with(
        "country/DEU", "member_of", date(2018, 6, 1)
    )
    store.get_relations.assert_not_called()


@pytest.mark.unit
def test_geo_membership_constraint_no_as_of() -> None:
    """Without context.as_of, constraint calls plain get_relations."""
    from unittest.mock import MagicMock

    from resolvekit.core.explain import NullTraceSink
    from resolvekit.core.model import NormalizedText, Query, ResolutionContext
    from resolvekit.core.store import EntityStore
    from resolvekit.packs.geo.constraints.membership import GeoMembershipConstraint

    store = MagicMock(spec=EntityStore)
    store.get_relations.return_value = ["group/EU"]

    constraint = GeoMembershipConstraint()
    context = ResolutionContext(attributes={"membership_org": "group/EU"})
    query = Query(
        raw_text="Germany",
        normalized=NormalizedText(original="Germany", normalized="germany"),
    )
    candidates = [_make_candidate("country/DEU")]
    constraint.apply(query, context, candidates, store, NullTraceSink())

    store.get_relations.assert_called_once_with("country/DEU", "member_of")
    store.get_relations_as_of.assert_not_called()
