"""Tests for suggest-mode store methods: iter_suggest_names, search_token_infix, and prefix search."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_fts_db(db_path: Path) -> None:
    """Minimal FTS5-enabled DB with a diacritic name and a two-token name."""
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

        -- FTS5 virtual table
        CREATE VIRTUAL TABLE names_fts USING fts5(
            entity_id,
            value_norm,
            content='names',
            content_rowid='rowid'
        );

        -- Côte d'Ivoire — tests diacritic fold
        INSERT INTO entities VALUES
            ('country/CIV', 'geo.country', "Côte d'Ivoire", 'cote d''ivoire',
             NULL, NULL, NULL);
        INSERT INTO names VALUES
            ('country/CIV', 'canonical', "Côte d'Ivoire", 'cote d''ivoire',
             'en', 1);
        INSERT INTO names_fts(entity_id, value_norm) VALUES
            ('country/CIV', 'cote d''ivoire');

        -- New York — tests token-infix ("york")
        INSERT INTO entities VALUES
            ('region/NewYork', 'geo.admin1', 'New York', 'new york',
             NULL, NULL, NULL);
        INSERT INTO names VALUES
            ('region/NewYork', 'canonical', 'New York', 'new york', 'en', 1),
            ('region/NewYork', 'alias', 'NY', 'ny', 'en', 0);
        INSERT INTO names_fts(entity_id, value_norm) VALUES
            ('region/NewYork', 'new york'),
            ('region/NewYork', 'ny');

        -- São Paulo — tests diacritic fold on LIKE fallback and iter_suggest_names
        INSERT INTO entities VALUES
            ('city/SaoPaulo', 'geo.city', 'São Paulo', 'são paulo',
             NULL, NULL, NULL);
        INSERT INTO names VALUES
            ('city/SaoPaulo', 'canonical', 'São Paulo', 'são paulo', 'pt', 1);
        INSERT INTO names_fts(entity_id, value_norm) VALUES
            ('city/SaoPaulo', 'são paulo');
        """
    )
    conn.commit()
    conn.close()


def _make_no_fts_db(db_path: Path) -> None:
    """Non-FTS DB for testing _search_prefix_like diacritic fix."""
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

        -- São Paulo: value_norm stores the diacritic form (NFKC+lower)
        INSERT INTO entities VALUES
            ('city/SaoPaulo', 'geo.city', 'São Paulo', 'são paulo',
             NULL, NULL, NULL);
        INSERT INTO names VALUES
            ('city/SaoPaulo', 'canonical', 'São Paulo', 'são paulo', 'pt', 1);
        """
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def fts_db(tmp_path: Path) -> Path:
    p = tmp_path / "fts.db"
    _make_fts_db(p)
    return p


@pytest.fixture()
def no_fts_db(tmp_path: Path) -> Path:
    p = tmp_path / "no_fts.db"
    _make_no_fts_db(p)
    return p


# ---------------------------------------------------------------------------
# iter_suggest_names
# ---------------------------------------------------------------------------


class TestIterSuggestNames:
    def test_yields_5tuples(self, fts_db: Path) -> None:
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store = SQLiteEntityStore(fts_db)
        try:
            rows = list(store.iter_suggest_names())
        finally:
            store.close()

        assert len(rows) > 0
        for row in rows:
            assert len(row) == 5
            value_norm, entity_id, name_kind, is_preferred, value = row
            assert isinstance(value_norm, str)
            assert isinstance(entity_id, str)
            assert isinstance(name_kind, str)
            assert isinstance(is_preferred, bool)
            assert isinstance(value, str)

    def test_filter_by_entity_type_prefix(self, fts_db: Path) -> None:
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store = SQLiteEntityStore(fts_db)
        try:
            rows = list(
                store.iter_suggest_names(
                    entity_type_prefixes=frozenset({"geo.country"})
                )
            )
        finally:
            store.close()

        entity_ids = {r[1] for r in rows}
        assert "country/CIV" in entity_ids
        assert "region/NewYork" not in entity_ids
        assert "city/SaoPaulo" not in entity_ids

    def test_preferred_flag_set_correctly(self, fts_db: Path) -> None:
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store = SQLiteEntityStore(fts_db)
        try:
            rows = list(store.iter_suggest_names())
        finally:
            store.close()

        # All canonical names have is_preferred=1 in fixture.
        preferred_rows = [r for r in rows if r[2] == "canonical"]
        assert all(r[3] is True for r in preferred_rows)

        # Alias "NY" has is_preferred=0.
        alias_rows = [r for r in rows if r[0] == "ny"]
        assert len(alias_rows) == 1
        assert alias_rows[0][3] is False

    def test_no_entity_type_filter_returns_all(self, fts_db: Path) -> None:
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store = SQLiteEntityStore(fts_db)
        try:
            rows = list(store.iter_suggest_names())
        finally:
            store.close()

        entity_ids = {r[1] for r in rows}
        assert "country/CIV" in entity_ids
        assert "region/NewYork" in entity_ids
        assert "city/SaoPaulo" in entity_ids


# ---------------------------------------------------------------------------
# search_token_infix (FTS path)
# ---------------------------------------------------------------------------


class TestSearchTokenInfixFts:
    def test_york_finds_new_york(self, fts_db: Path) -> None:
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store = SQLiteEntityStore(fts_db)
        try:
            results = store.search_token_infix("york")
        finally:
            store.close()

        entity_ids = [r[0] for r in results]
        assert "region/NewYork" in entity_ids

    def test_returns_3tuples(self, fts_db: Path) -> None:
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store = SQLiteEntityStore(fts_db)
        try:
            results = store.search_token_infix("york")
        finally:
            store.close()

        for row in results:
            assert len(row) == 3
            entity_id, score, rank = row
            assert isinstance(entity_id, str)
            assert isinstance(score, float)
            assert isinstance(rank, int)

    def test_empty_query_returns_empty(self, fts_db: Path) -> None:
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store = SQLiteEntityStore(fts_db)
        try:
            results = store.search_token_infix("")
        finally:
            store.close()

        assert results == []

    def test_entity_type_prefix_filter(self, fts_db: Path) -> None:
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store = SQLiteEntityStore(fts_db)
        try:
            # "new" matches both "new york", but filtered to country type only.
            results = store.search_token_infix(
                "new",
                entity_type_prefixes=frozenset({"geo.country"}),
            )
        finally:
            store.close()

        entity_ids = [r[0] for r in results]
        # New York is geo.admin1, not geo.country — should be excluded.
        assert "region/NewYork" not in entity_ids

    def test_limit_respected(self, fts_db: Path) -> None:
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store = SQLiteEntityStore(fts_db)
        try:
            results = store.search_token_infix("cote", limit=1)
        finally:
            store.close()

        assert len(results) <= 1


# ---------------------------------------------------------------------------
# search_token_infix (non-FTS LIKE fallback)
# ---------------------------------------------------------------------------


class TestSearchTokenInfixLike:
    def test_like_fallback_finds_substring(self, no_fts_db: Path) -> None:
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store = SQLiteEntityStore(no_fts_db)
        assert not store._has_fts, "fixture must be non-FTS for this test"
        try:
            results = store.search_token_infix("paulo")
        finally:
            store.close()

        entity_ids = [r[0] for r in results]
        assert "city/SaoPaulo" in entity_ids

    def test_like_fallback_empty_query_returns_empty(self, no_fts_db: Path) -> None:
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store = SQLiteEntityStore(no_fts_db)
        assert not store._has_fts
        try:
            results = store.search_token_infix("")
        finally:
            store.close()

        assert results == []


# ---------------------------------------------------------------------------
# _search_prefix_like — diacritic-fold fix
# ---------------------------------------------------------------------------


class TestSearchPrefixLikeDiacriticFold:
    def test_sao_finds_sao_paulo(self, no_fts_db: Path) -> None:
        """'sao' (no diacritic) must match 'são paulo' via fold_for_match."""
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store = SQLiteEntityStore(no_fts_db)
        assert not store._has_fts, "fixture must be non-FTS for this test"
        try:
            results = store._search_prefix_like("sao", 10)
        finally:
            store.close()

        entity_ids = [r[0] for r in results]
        assert "city/SaoPaulo" in entity_ids, (
            "'sao' should find 'são paulo' after diacritic folding"
        )

    def test_exact_match_still_works(self, no_fts_db: Path) -> None:
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store = SQLiteEntityStore(no_fts_db)
        assert not store._has_fts
        try:
            results = store._search_prefix_like("são", 10)
        finally:
            store.close()

        entity_ids = [r[0] for r in results]
        assert "city/SaoPaulo" in entity_ids

    def test_no_false_positives(self, no_fts_db: Path) -> None:
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store = SQLiteEntityStore(no_fts_db)
        assert not store._has_fts
        try:
            results = store._search_prefix_like("xyz_no_match", 10)
        finally:
            store.close()

        assert results == []


# ---------------------------------------------------------------------------
# Existing search_prefix (FTS path) stays green
# ---------------------------------------------------------------------------


class TestSearchPrefixFtsUnchanged:
    def test_prefix_match_returns_results(self, fts_db: Path) -> None:
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store = SQLiteEntityStore(fts_db)
        try:
            results = store.search_prefix("new", "name", limit=5)
        finally:
            store.close()

        entity_ids = [r[0] for r in results]
        assert "region/NewYork" in entity_ids

    def test_wrong_field_returns_empty(self, fts_db: Path) -> None:
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store = SQLiteEntityStore(fts_db)
        try:
            results = store.search_prefix("new", "code", limit=5)
        finally:
            store.close()

        assert results == []


# ---------------------------------------------------------------------------
# CompositeStore — iter_suggest_names and search_token_infix
# ---------------------------------------------------------------------------


class TestCompositeStoreSuggest:
    def test_iter_suggest_names_deduped_by_entity_id(self, fts_db: Path) -> None:
        """First-store rows win: all name rows from the home store are yielded;
        later stores skip that entity entirely.

        When two identical stores are composed, each entity should appear the
        same number of times as it has name rows in the single store (not
        doubled), because store_b is skipped for any entity already seen in
        store_a.
        """
        from resolvekit.core.store.composite import CompositeStore
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        # Baseline: collect entity_id → row_count from a single store.
        single = SQLiteEntityStore(fts_db)
        try:
            single_rows = list(single.iter_suggest_names())
        finally:
            single.close()
        import collections

        single_counts: dict[str, int] = collections.Counter(r[1] for r in single_rows)

        # Composite with two identical stores: each entity must appear exactly
        # as many times as in the single store (home store yields all its rows;
        # duplicate store contributes nothing for already-seen entities).
        store_a = SQLiteEntityStore(fts_db)
        store_b = SQLiteEntityStore(fts_db)
        composite = CompositeStore([store_a, store_b])
        try:
            composite_rows = list(composite.iter_suggest_names())
        finally:
            store_a.close()
            store_b.close()

        composite_counts: dict[str, int] = collections.Counter(
            r[1] for r in composite_rows
        )
        assert composite_counts == single_counts, (
            "CompositeStore.iter_suggest_names yielded different row counts than "
            f"a single store. single={dict(single_counts)}, "
            f"composite={dict(composite_counts)}"
        )

    def test_search_token_infix_deduped(self, fts_db: Path) -> None:
        from resolvekit.core.store.composite import CompositeStore
        from resolvekit.core.store.sqlite import SQLiteEntityStore

        store_a = SQLiteEntityStore(fts_db)
        store_b = SQLiteEntityStore(fts_db)
        composite = CompositeStore([store_a, store_b])
        try:
            results = composite.search_token_infix("york")
        finally:
            store_a.close()
            store_b.close()

        entity_ids = [r[0] for r in results]
        assert entity_ids.count("region/NewYork") == 1

    def test_search_token_infix_default_empty(self) -> None:
        """Default EntityStore.search_token_infix returns []."""
        from resolvekit.core.model import EntityRecord
        from resolvekit.core.store.interface import EntityStore

        class MinimalStore(EntityStore):
            def get_entity(self, entity_id: str) -> EntityRecord | None:
                return None

            def lookup_code(self, system: str, value_norm: str) -> list[str]:
                return []

            def lookup_name_exact(
                self, value_norm: str, name_kinds: set[str] | None = None
            ) -> list[str]:
                return []

            def search_fulltext(
                self,
                query_norm: str,
                fields: set[str] | None = None,
                limit: int = 10,
            ) -> list[tuple[str, float, int]]:
                return []

            def bulk_get_entities(
                self, entity_ids: list[str]
            ) -> dict[str, EntityRecord]:
                return {}

        store = MinimalStore()
        assert store.search_token_infix("anything") == []
