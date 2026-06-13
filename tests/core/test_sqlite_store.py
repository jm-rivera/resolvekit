"""Tests for SQLiteEntityStore."""

import os
import sqlite3
import stat

import pytest


@pytest.fixture
def test_db(tmp_path):
    """Create a test SQLite database with sample data."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)

    # Create schema
    conn.executescript("""
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
            is_preferred INTEGER DEFAULT 0,
            FOREIGN KEY (entity_id) REFERENCES entities(entity_id)
        );

        CREATE TABLE codes (
            entity_id TEXT NOT NULL,
            system TEXT NOT NULL,
            value TEXT NOT NULL,
            value_norm TEXT NOT NULL,
            PRIMARY KEY (entity_id, system),
            FOREIGN KEY (entity_id) REFERENCES entities(entity_id)
        );

        CREATE TABLE relations (
            entity_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            FOREIGN KEY (entity_id) REFERENCES entities(entity_id)
        );

        CREATE INDEX idx_codes_lookup ON codes(system, value_norm);
        CREATE INDEX idx_names_lookup ON names(value_norm, name_kind);

        -- FTS table
        CREATE VIRTUAL TABLE names_fts USING fts5(
            entity_id,
            value_norm,
            content='names',
            content_rowid='rowid'
        );
    """)

    # Insert test data
    conn.execute("""
        INSERT INTO entities VALUES
        ('country/USA', 'geo.country', 'United States of America', 'united states of america', NULL, NULL, NULL)
    """)
    conn.execute("""
        INSERT INTO codes VALUES
        ('country/USA', 'iso2', 'US', 'us'),
        ('country/USA', 'iso3', 'USA', 'usa')
    """)
    conn.execute("""
        INSERT INTO names VALUES
        ('country/USA', 'canonical', 'United States of America', 'united states of america', 'en', 1),
        ('country/USA', 'alias', 'USA', 'usa', 'en', 0),
        ('country/USA', 'alias', 'America', 'america', 'en', 0)
    """)
    conn.execute("""
        INSERT INTO names_fts(entity_id, value_norm) VALUES
        ('country/USA', 'united states of america'),
        ('country/USA', 'usa'),
        ('country/USA', 'america')
    """)

    conn.commit()
    conn.close()

    return db_path


class TestSQLiteEntityStore:
    """Tests for SQLiteEntityStore."""

    def test_get_entity(self, test_db):
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store = SQLiteEntityStore(test_db)
        entity = store.get_entity("country/USA")

        assert entity is not None
        assert entity.entity_id == "country/USA"
        assert entity.entity_type == "geo.country"
        assert entity.canonical_name == "United States of America"

    def test_get_entity_not_found(self, test_db):
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store = SQLiteEntityStore(test_db)
        entity = store.get_entity("country/NONEXISTENT")

        assert entity is None

    def test_lookup_code(self, test_db):
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store = SQLiteEntityStore(test_db)

        ids = store.lookup_code("iso2", "us")
        assert ids == ["country/USA"]

        ids = store.lookup_code("iso3", "usa")
        assert ids == ["country/USA"]

        ids = store.lookup_code("iso2", "xx")
        assert ids == []

    def test_lookup_name_exact(self, test_db):
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store = SQLiteEntityStore(test_db)

        ids = store.lookup_name_exact("united states of america")
        assert "country/USA" in ids

        ids = store.lookup_name_exact("usa")
        assert "country/USA" in ids

        ids = store.lookup_name_exact("usa", name_kinds={"canonical"})
        assert ids == []  # USA is an alias, not canonical

    def test_search_fulltext(self, test_db):
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store = SQLiteEntityStore(test_db)

        results = store.search_fulltext("united states")
        assert len(results) >= 1
        assert results[0][0] == "country/USA"  # entity_id

    def test_bulk_get_entities(self, test_db):
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store = SQLiteEntityStore(test_db)

        entities = store.bulk_get_entities(["country/USA", "country/NONEXISTENT"])
        assert "country/USA" in entities
        assert "country/NONEXISTENT" not in entities

    def test_get_entity_loads_attrs_json(self, test_db):
        """Test that attrs_json is parsed and loaded into EntityRecord.attributes."""
        import json

        from resolvekit.core.store.sqlite import SQLiteEntityStore

        # Insert an entity with attrs_json
        conn = sqlite3.connect(test_db)
        attrs = {"country_code": "DE", "population": 83000000, "is_eu_member": True}
        conn.execute(
            """
            INSERT INTO entities (entity_id, entity_type, canonical_name, canonical_name_norm, attrs_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "country/DEU",
                "geo.country",
                "Germany",
                "germany",
                json.dumps(attrs),
            ),
        )
        conn.commit()
        conn.close()

        store = SQLiteEntityStore(test_db)
        entity = store.get_entity("country/DEU")

        assert entity is not None
        assert entity.attributes["country_code"] == "DE"
        assert entity.attributes["population"] == 83000000
        assert entity.attributes["is_eu_member"] is True

    def test_get_entity_handles_null_attrs_json(self, test_db):
        """Test that NULL attrs_json results in empty attributes dict."""
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        # USA entity already has NULL attrs_json from fixture
        store = SQLiteEntityStore(test_db)
        entity = store.get_entity("country/USA")

        assert entity is not None
        assert entity.attributes == {}

    def test_get_entity_handles_invalid_attrs_json(self, test_db):
        """Test that invalid JSON in attrs_json results in empty attributes dict."""
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        # Insert an entity with invalid JSON
        conn = sqlite3.connect(test_db)
        conn.execute(
            """
            INSERT INTO entities (entity_id, entity_type, canonical_name, canonical_name_norm, attrs_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "country/INVALID",
                "geo.country",
                "Invalid",
                "invalid",
                "{not valid json",
            ),
        )
        conn.commit()
        conn.close()

        store = SQLiteEntityStore(test_db)
        entity = store.get_entity("country/INVALID")

        assert entity is not None
        assert entity.attributes == {}

    def test_pool_size_zero_raises(self, test_db):
        """Test that pool_size=0 raises ValueError."""
        from resolvekit.core.store.sqlite import SQLiteTuning

        with pytest.raises(ValueError, match="pool_size must be >= 1"):
            SQLiteTuning(pool_size=0)

    def test_pool_size_negative_raises(self, test_db):
        """Test that negative pool_size raises ValueError."""
        from resolvekit.core.store.sqlite import SQLiteTuning

        with pytest.raises(ValueError, match="pool_size must be >= 1"):
            SQLiteTuning(pool_size=-1)

    def test_pool_size_valid(self, test_db):
        """Test that valid pool_size works correctly."""
        from resolvekit.core.store.sqlite import SQLiteEntityStore, SQLiteTuning

        store = SQLiteEntityStore(test_db, tuning=SQLiteTuning(pool_size=1))
        entity = store.get_entity("country/USA")
        assert entity is not None

    def test_read_only_datapack_opens_without_wal(self, tmp_path):
        """Read-only datapacks should remain readable."""
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        db_path = tmp_path / "readonly.db"
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
            ('country/USA', 'geo.country', 'United States', 'united states', NULL, NULL);
            """
        )
        conn.commit()
        conn.close()

        original_mode = stat.S_IMODE(os.stat(tmp_path).st_mode)
        os.chmod(tmp_path, stat.S_IREAD | stat.S_IEXEC)
        try:
            store = SQLiteEntityStore(db_path)
            entity = store.get_entity("country/USA")
            store.close()
        finally:
            os.chmod(tmp_path, original_mode)

        assert entity is not None
        assert entity.entity_id == "country/USA"

    def test_operations_after_close_raise(self, test_db):
        """Closed stores should fail fast instead of blocking."""
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store = SQLiteEntityStore(test_db)
        store.close()

        with pytest.raises(RuntimeError, match="closed"):
            store.get_entity("country/USA")

    def test_search_fulltext_token_and_fallback(self, tmp_path):
        """Word-reordered query should match via AND-token fallback."""
        import sqlite3

        from resolvekit.core.store.sqlite import SQLiteEntityStore

        db_path = tmp_path / "and_fallback.db"
        conn = sqlite3.connect(db_path)
        conn.executescript("""
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
        """)
        conn.execute(
            "INSERT INTO entities VALUES ('country/USA', 'geo.country', 'United States', 'united states', NULL, NULL)"
        )
        conn.execute(
            "INSERT INTO names VALUES ('country/USA', 'canonical', 'United States', 'united states', 'en', 1)"
        )
        conn.execute(
            "INSERT INTO names_fts(entity_id, value_norm) VALUES ('country/USA', 'united states')"
        )
        conn.commit()
        conn.close()

        store = SQLiteEntityStore(db_path)
        # "states united" is a word-reordered form — phrase match fails, AND fallback finds it
        results = store.search_fulltext("states united")
        assert len(results) >= 1
        assert results[0][0] == "country/USA"

    def test_search_fulltext_partial_no_false_positive(self, tmp_path):
        """Partial-match query should NOT resolve — only one token overlaps."""
        import sqlite3

        from resolvekit.core.store.sqlite import SQLiteEntityStore

        db_path = tmp_path / "partial_match.db"
        conn = sqlite3.connect(db_path)
        conn.executescript("""
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
        """)
        conn.execute(
            "INSERT INTO entities VALUES ('country/USA', 'geo.country', 'United States', 'united states', NULL, NULL)"
        )
        conn.execute(
            "INSERT INTO names VALUES ('country/USA', 'canonical', 'United States', 'united states', 'en', 1)"
        )
        conn.execute(
            "INSERT INTO names_fts(entity_id, value_norm) VALUES ('country/USA', 'united states')"
        )
        conn.commit()
        conn.close()

        store = SQLiteEntityStore(db_path)
        # "united foobar": only one token matches — should NOT return results
        # (AND fallback requires ALL tokens present)
        results = store.search_fulltext("united foobar")
        assert results == []

    def test_search_fulltext_single_word_no_extra_fallback(self, tmp_path):
        """Single-word query that misses should return empty — no unnecessary fallback."""
        import sqlite3

        from resolvekit.core.store.sqlite import SQLiteEntityStore

        db_path = tmp_path / "single_word.db"
        conn = sqlite3.connect(db_path)
        conn.executescript("""
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
        """)
        conn.execute(
            "INSERT INTO entities VALUES ('country/USA', 'geo.country', 'United States', 'united states', NULL, NULL)"
        )
        conn.execute(
            "INSERT INTO names VALUES ('country/USA', 'canonical', 'United States', 'united states', 'en', 1)"
        )
        conn.execute(
            "INSERT INTO names_fts(entity_id, value_norm) VALUES ('country/USA', 'united states')"
        )
        conn.commit()
        conn.close()

        store = SQLiteEntityStore(db_path)
        # Single word that doesn't exist at all — no fallback should inflate results
        results = store.search_fulltext("zzznomatch")
        assert results == []

    def test_relation_types_returns_distinct_set(self, tmp_path):
        """relation_types() returns the frozenset of DISTINCT relation_type values present."""
        import sqlite3

        from resolvekit.core.store.sqlite import SQLiteEntityStore

        db_path = tmp_path / "rel_types.db"
        conn = sqlite3.connect(db_path)
        conn.executescript("""
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
                ('country/A', 'geo.country', 'A', 'a', NULL, NULL),
                ('country/B', 'geo.country', 'B', 'b', NULL, NULL),
                ('region/R', 'geo.region', 'R', 'r', NULL, NULL);
        """)
        conn.executemany(
            "INSERT INTO relations (entity_id, relation_type, target_id) VALUES (?, ?, ?)",
            [
                ("country/A", "contained_in", "region/R"),
                ("country/B", "contained_in", "region/R"),
                ("country/A", "member_of", "region/R"),
            ],
        )
        conn.commit()
        conn.close()

        store = SQLiteEntityStore(db_path)
        result = store.relation_types()
        assert isinstance(result, frozenset)
        assert result == frozenset({"contained_in", "member_of"})

    def test_relation_types_returns_empty_frozenset_when_table_absent(self, tmp_path):
        """relation_types() returns frozenset() for a DB with no relations table."""
        import sqlite3

        from resolvekit.core.store.sqlite import SQLiteEntityStore

        db_path = tmp_path / "no_relations.db"
        conn = sqlite3.connect(db_path)
        # Minimal schema without a relations table; migration will fail gracefully
        # because the DB is written before SQLiteEntityStore opens it.
        conn.executescript("""
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
                is_preferred INTEGER DEFAULT 0
            );
            CREATE TABLE codes (
                entity_id TEXT NOT NULL,
                system TEXT NOT NULL,
                value TEXT NOT NULL,
                value_norm TEXT NOT NULL,
                PRIMARY KEY (entity_id, system)
            );
            CREATE VIRTUAL TABLE names_fts USING fts5(entity_id, value_norm);
            INSERT INTO entities VALUES
                ('country/USA', 'geo.country', 'United States', 'united states', NULL, NULL);
        """)
        conn.commit()
        conn.close()

        store = SQLiteEntityStore(db_path)
        result = store.relation_types()
        assert result == frozenset()
