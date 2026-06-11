"""Tests for SQLiteTuning dataclass and SQLiteEntityStore tuning integration."""

import sqlite3
from pathlib import Path

import pytest

from resolvekit.core.store.sqlite import SQLiteEntityStore, SQLiteTuning

# ---------------------------------------------------------------------------
# SQLiteTuning dataclass
# ---------------------------------------------------------------------------


def test_sqlite_tuning_default_values() -> None:
    """SQLiteTuning() must expose the expected default field values."""
    t = SQLiteTuning()
    assert t.pool_size == 2
    assert t.cache_size_mb == 64
    assert t.mmap_size_mb == 128


def test_sqlite_tuning_validates_pool_size() -> None:
    """pool_size=0 must raise ValueError."""
    with pytest.raises(ValueError, match="pool_size"):
        SQLiteTuning(pool_size=0)


def test_sqlite_tuning_validates_cache_size() -> None:
    """cache_size_mb=0 must raise ValueError."""
    with pytest.raises(ValueError, match="cache_size_mb"):
        SQLiteTuning(cache_size_mb=0)


def test_sqlite_tuning_validates_mmap_size() -> None:
    """mmap_size_mb=-1 must raise ValueError."""
    with pytest.raises(ValueError, match="mmap_size_mb"):
        SQLiteTuning(mmap_size_mb=-1)


def test_sqlite_tuning_mmap_zero_allowed() -> None:
    """mmap_size_mb=0 is valid (disables mmap, relies on page cache only)."""
    t = SQLiteTuning(mmap_size_mb=0)
    assert t.mmap_size_mb == 0


def test_sqlite_tuning_is_frozen() -> None:
    """SQLiteTuning must be immutable (frozen=True)."""
    t = SQLiteTuning()
    with pytest.raises((AttributeError, TypeError)):
        t.pool_size = 3  # type: ignore[misc]  # testing that frozen raises at runtime


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_minimal_db(db_path: Path) -> None:
    """Write a minimal but valid SQLite datapack schema to db_path."""
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE entities (
            entity_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            canonical_name_norm TEXT NOT NULL,
            valid_from TEXT,
            valid_until TEXT,
            attrs_json TEXT
        );
        CREATE TABLE names (
            entity_id TEXT NOT NULL,
            name_kind TEXT NOT NULL,
            value TEXT NOT NULL,
            value_norm TEXT NOT NULL,
            lang TEXT,
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
            target_id TEXT NOT NULL,
            valid_from TEXT,
            valid_until TEXT
        );
        INSERT INTO entities VALUES
            ('country/TEST', 'geo.country', 'Testland', 'testland', NULL, NULL, NULL);
        INSERT INTO codes VALUES
            ('country/TEST', 'iso2', 'TT', 'tt');
        INSERT INTO names VALUES
            ('country/TEST', 'canonical', 'Testland', 'testland', 'en', 1);
        """
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# SQLiteEntityStore integration
# ---------------------------------------------------------------------------


def test_sqlite_entity_store_accepts_tuning(tmp_path: Path) -> None:
    """SQLiteEntityStore opens successfully with a custom SQLiteTuning."""
    db_path = tmp_path / "entities.sqlite"
    _make_minimal_db(db_path)

    tuning = SQLiteTuning(pool_size=1, cache_size_mb=8, mmap_size_mb=0)
    store = SQLiteEntityStore(db_path, tuning=tuning)
    try:
        result = store.lookup_code("iso2", "tt")
        assert result == ["country/TEST"]
    finally:
        store.close()


def test_sqlite_entity_store_default_tuning_unchanged(
    tmp_path: Path,
) -> None:
    """Default SQLiteEntityStore (no explicit tuning) uses pool_size=2."""
    db_path = tmp_path / "entities.sqlite"
    _make_minimal_db(db_path)

    store = SQLiteEntityStore(db_path)
    try:
        assert store._pool_size == 2
        # Sanity: basic lookup still works.
        result = store.lookup_code("iso2", "tt")
        assert result == ["country/TEST"]
    finally:
        store.close()
