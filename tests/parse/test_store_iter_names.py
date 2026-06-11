"""Tests for EntityStore.iter_names() — the name-enumeration seam for the parser.

These tests use a hand-built SQLiteEntityStore fixture (no loaded packs, no
network) so they are fast and offline-safe.
"""

from __future__ import annotations

import inspect
import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest

from resolvekit.core.store.interface import EntityStore
from resolvekit.core.store.sqlite import SQLiteEntityStore


def _build_store(tmp_path: Path) -> SQLiteEntityStore:
    """Build a minimal SQLite store with countries and an admin1 region.

    Entities:
      country/KEN  geo.country  Kenya
      country/GEO  geo.country  Georgia  ← same surface as admin1/GEO-TB
      admin1/GEO-TB  geo.admin1  Georgia  ← real collision (Georgia the region)
      admin1/KEN-001  geo.admin1  Nairobi County

    Names:
      "kenya"       → country/KEN
      "georgia"     → country/GEO  (collision)
      "georgia"     → admin1/GEO-TB  (collision)
      "nairobi county" → admin1/KEN-001
    """
    db_path = tmp_path / "entities.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE entities (
            entity_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            canonical_name_norm TEXT NOT NULL,
            valid_from TEXT,
            valid_until TEXT
        );
        CREATE TABLE names (
            entity_id TEXT NOT NULL,
            name_kind TEXT NOT NULL,
            value TEXT NOT NULL,
            value_norm TEXT NOT NULL,
            lang TEXT,
            script TEXT,
            is_preferred INTEGER DEFAULT 0
        );
        CREATE TABLE codes (
            entity_id TEXT NOT NULL,
            system TEXT NOT NULL,
            value TEXT NOT NULL,
            value_norm TEXT NOT NULL,
            PRIMARY KEY (entity_id, system)
        );
        CREATE TABLE relations (
            entity_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            target_id TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE names_fts USING fts5(entity_id, value_norm);

        INSERT INTO entities VALUES
            ('country/KEN', 'geo.country', 'Kenya', 'kenya', NULL, NULL),
            ('country/GEO', 'geo.country', 'Georgia', 'georgia', NULL, NULL),
            ('admin1/GEO-TB', 'geo.admin1', 'Georgia', 'georgia', NULL, NULL),
            ('admin1/KEN-001', 'geo.admin1', 'Nairobi County', 'nairobi county', NULL, NULL);

        INSERT INTO names VALUES
            ('country/KEN', 'canonical', 'Kenya', 'kenya', 'en', NULL, 1),
            ('country/GEO', 'canonical', 'Georgia', 'georgia', 'en', NULL, 1),
            ('admin1/GEO-TB', 'canonical', 'Georgia', 'georgia', 'en', NULL, 1),
            ('admin1/KEN-001', 'canonical', 'Nairobi County', 'nairobi county', 'en', NULL, 1);
        """
    )
    conn.commit()
    conn.close()
    return SQLiteEntityStore(db_path)


def _build_store_with_aliases(tmp_path: Path) -> SQLiteEntityStore:
    """Build a store that includes alias rows with uppercase codes.

    Entities:
      country/AND  geo.country  Andorra
      country/KEN  geo.country  Kenya

    Names:
      "andorra"  canonical  → country/AND
      "and"      alias (value='AND', cased code)  → country/AND
      "kenya"    canonical  → country/KEN
    """
    db_path = tmp_path / "aliases.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE entities (
            entity_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            canonical_name_norm TEXT NOT NULL,
            valid_from TEXT,
            valid_until TEXT
        );
        CREATE TABLE names (
            entity_id TEXT NOT NULL,
            name_kind TEXT NOT NULL,
            value TEXT NOT NULL,
            value_norm TEXT NOT NULL,
            lang TEXT,
            script TEXT,
            is_preferred INTEGER DEFAULT 0
        );
        CREATE TABLE codes (
            entity_id TEXT NOT NULL,
            system TEXT NOT NULL,
            value TEXT NOT NULL,
            value_norm TEXT NOT NULL,
            PRIMARY KEY (entity_id, system)
        );
        CREATE TABLE relations (
            entity_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            target_id TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE names_fts USING fts5(entity_id, value_norm);

        INSERT INTO entities VALUES
            ('country/AND', 'geo.country', 'Andorra', 'andorra', NULL, NULL),
            ('country/KEN', 'geo.country', 'Kenya', 'kenya', NULL, NULL);

        INSERT INTO names VALUES
            ('country/AND', 'canonical', 'Andorra', 'andorra', 'en', NULL, 1),
            ('country/AND', 'alias',     'AND',     'and',     NULL, NULL, 0),
            ('country/KEN', 'canonical', 'Kenya',   'kenya',   'en', NULL, 1);
        """
    )
    conn.commit()
    conn.close()
    return SQLiteEntityStore(db_path)


@pytest.fixture
def alias_store(tmp_path: Path) -> Generator[SQLiteEntityStore, None, None]:
    store = _build_store_with_aliases(tmp_path)
    yield store
    store.close()


@pytest.fixture
def small_store(tmp_path: Path) -> Generator[SQLiteEntityStore, None, None]:
    store = _build_store(tmp_path)
    yield store
    store.close()


# ---------------------------------------------------------------------------
# yields known pairs
# ---------------------------------------------------------------------------


def test_iter_names_yields_known_pair(small_store: SQLiteEntityStore) -> None:
    """iter_names() must yield the (value_norm, entity_id) pair for Kenya."""
    pairs = list(small_store.iter_names())
    assert ("kenya", "country/KEN") in pairs


# ---------------------------------------------------------------------------
# many-to-one: same value_norm maps to multiple entity_ids
# ---------------------------------------------------------------------------


def test_iter_names_many_to_one_collision(small_store: SQLiteEntityStore) -> None:
    """One surface form ("georgia") appears with ≥2 distinct entity_ids."""
    pairs = list(small_store.iter_names())
    georgia_ids = {
        entity_id for value_norm, entity_id in pairs if value_norm == "georgia"
    }
    assert len(georgia_ids) >= 2, (
        f"Expected ≥2 entities for 'georgia', got {georgia_ids}"
    )
    assert "country/GEO" in georgia_ids
    assert "admin1/GEO-TB" in georgia_ids


# ---------------------------------------------------------------------------
# prefix gating
# ---------------------------------------------------------------------------


def test_iter_names_prefix_gating_country_only(small_store: SQLiteEntityStore) -> None:
    """Filtering to geo.country must exclude admin1 names."""
    pairs = list(
        small_store.iter_names(entity_type_prefixes=frozenset({"geo.country"}))
    )
    entity_ids = {entity_id for _, entity_id in pairs}

    # Countries are present.
    assert "country/KEN" in entity_ids
    assert "country/GEO" in entity_ids

    # Admin1 entities are absent.
    assert "admin1/GEO-TB" not in entity_ids
    assert "admin1/KEN-001" not in entity_ids


def test_iter_names_prefix_gating_admin1_only(small_store: SQLiteEntityStore) -> None:
    """Filtering to geo.admin1 must exclude country names."""
    pairs = list(small_store.iter_names(entity_type_prefixes=frozenset({"geo.admin1"})))
    entity_ids = {entity_id for _, entity_id in pairs}

    assert "admin1/GEO-TB" in entity_ids
    assert "admin1/KEN-001" in entity_ids

    assert "country/KEN" not in entity_ids
    assert "country/GEO" not in entity_ids


def test_iter_names_prefix_gating_both(small_store: SQLiteEntityStore) -> None:
    """Passing both prefixes returns the full set."""
    all_pairs = set(small_store.iter_names())
    filtered_pairs = set(
        small_store.iter_names(
            entity_type_prefixes=frozenset({"geo.country", "geo.admin1"})
        )
    )
    assert all_pairs == filtered_pairs


# ---------------------------------------------------------------------------
# streaming / laziness
# ---------------------------------------------------------------------------


def test_iter_names_returns_iterator_not_list(small_store: SQLiteEntityStore) -> None:
    """iter_names() must return an iterator, not a materialised list."""
    result = small_store.iter_names()
    # Either a generator or any other iterator (iter(x) is x).
    assert inspect.isgenerator(result) or iter(result) is result, (
        "iter_names() must return an iterator, not a list"
    )


# ---------------------------------------------------------------------------
# default base class raises NotImplementedError
# ---------------------------------------------------------------------------


def test_entity_store_default_raises_not_implemented() -> None:
    """A bare EntityStore subclass that doesn't override raises NotImplementedError."""

    class _MinimalStore(EntityStore):
        def get_entity(self, entity_id):  # type: ignore[override]
            return None

        def lookup_code(self, system, value_norm):  # type: ignore[override]
            return []

        def lookup_name_exact(self, value_norm, name_kinds=None):  # type: ignore[override]
            return []

        def search_fulltext(self, query_norm, fields=None, limit=10):  # type: ignore[override]
            return []

        def bulk_get_entities(self, entity_ids):  # type: ignore[override]
            return {}

    store = _MinimalStore()
    with pytest.raises(NotImplementedError):
        # Must raise on first next(), not just on construction.
        next(iter(store.iter_names()))


# ---------------------------------------------------------------------------
# with_name_meta=False — 2-tuple contract unchanged
# ---------------------------------------------------------------------------


def test_iter_names_default_yields_2_tuples(alias_store: SQLiteEntityStore) -> None:
    """Default (with_name_meta=False) still yields 2-tuples — contract unchanged."""
    rows = list(alias_store.iter_names())
    assert all(len(row) == 2 for row in rows), (
        "Default iter_names() must yield 2-tuples only"
    )
    assert ("andorra", "country/AND") in rows
    assert ("kenya", "country/KEN") in rows


# ---------------------------------------------------------------------------
# with_name_meta=True — 4-tuple with original casing
# ---------------------------------------------------------------------------


def test_iter_names_meta_yields_4_tuples(alias_store: SQLiteEntityStore) -> None:
    """with_name_meta=True yields (value_norm, entity_id, name_kind, value) 4-tuples."""
    rows = list(alias_store.iter_names(with_name_meta=True))
    assert all(len(row) == 4 for row in rows), (
        "with_name_meta=True must yield 4-tuples only"
    )


def test_iter_names_meta_preserves_original_casing(
    alias_store: SQLiteEntityStore,
) -> None:
    """The alias row for Andorra must carry value='AND' (uppercase original casing)."""
    rows = list(alias_store.iter_names(with_name_meta=True))
    # Find the alias row for country/AND whose value_norm is 'and'.
    alias_rows = [
        row
        for row in rows
        if row[0] == "and" and row[1] == "country/AND" and row[2] == "alias"
    ]
    assert alias_rows, (
        "Expected an alias row for (value_norm='and', entity_id='country/AND') "
        f"in the 4-tuple output; got rows: {rows}"
    )
    _value_norm, _entity_id, _name_kind, value = alias_rows[0]
    assert value == "AND", (
        f"Original-cased value must be 'AND' (uppercase), got {value!r}"
    )


def test_iter_names_meta_canonical_row(alias_store: SQLiteEntityStore) -> None:
    """Canonical name rows are also yielded with correct kind and original casing."""
    rows = list(alias_store.iter_names(with_name_meta=True))
    canonical_rows = [
        row
        for row in rows
        if row[0] == "andorra" and row[1] == "country/AND" and row[2] == "canonical"
    ]
    assert canonical_rows, "Expected a canonical row for country/AND"
    value = canonical_rows[0][3]
    assert value == "Andorra"


# ---------------------------------------------------------------------------
# with_name_meta=True composes with entity_type_prefixes
# ---------------------------------------------------------------------------


def test_iter_names_meta_with_prefix_filter(alias_store: SQLiteEntityStore) -> None:
    """with_name_meta=True composes correctly with entity_type_prefixes filtering."""
    rows = list(
        alias_store.iter_names(
            with_name_meta=True,
            entity_type_prefixes=frozenset({"geo.country"}),
        )
    )
    entity_ids = {row[1] for row in rows}
    # Both countries are present.
    assert "country/AND" in entity_ids
    assert "country/KEN" in entity_ids
    # All rows are 4-tuples.
    assert all(len(row) == 4 for row in rows)
