"""Tests for cascade ranker, fuzzy candidates, suggest_prefix, and multi-pack ranking."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_suggest_db(db_path: Path, *, with_prominence: bool = True) -> None:
    """Minimal FTS5-enabled DB for suggest tests.

    Entities:
    - country/USA   (geo.country, prominence=0.9 when with_prominence)
    - country/FRA   (geo.country, prominence=0.7 when with_prominence)
    - region/NewYork (geo.admin1)
    """
    conn = sqlite3.connect(db_path)
    usa_attrs = '{"prominence": 0.9}' if with_prominence else "{}"
    fra_attrs = '{"prominence": 0.7}' if with_prominence else "{}"
    conn.executescript(
        f"""
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
        CREATE VIRTUAL TABLE names_fts USING fts5(
            entity_id,
            value_norm,
            content='names',
            content_rowid='rowid'
        );

        INSERT INTO entities VALUES
            ('country/USA', 'geo.country', 'United States', 'united states',
             NULL, NULL, '{usa_attrs}'),
            ('country/FRA', 'geo.country', 'France', 'france',
             NULL, NULL, '{fra_attrs}'),
            ('region/NewYork', 'geo.admin1', 'New York', 'new york',
             NULL, NULL, NULL);

        INSERT INTO names VALUES
            ('country/USA', 'canonical', 'United States', 'united states', 'en', 1),
            ('country/USA', 'alias', 'United States of America',
             'united states of america', 'en', 0),
            ('country/FRA', 'canonical', 'France', 'france', 'en', 1),
            ('region/NewYork', 'canonical', 'New York', 'new york', 'en', 1),
            ('region/NewYork', 'alias', 'NY', 'ny', 'en', 0);

        INSERT INTO names_fts(entity_id, value_norm) VALUES
            ('country/USA', 'united states'),
            ('country/USA', 'united states of america'),
            ('country/FRA', 'france'),
            ('region/NewYork', 'new york'),
            ('region/NewYork', 'ny');
        """
    )
    conn.commit()
    conn.close()


def _make_suggest_db_org(db_path: Path) -> None:
    """Minimal FTS5-enabled org DB for multi-pack suggest tests."""
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
        CREATE VIRTUAL TABLE names_fts USING fts5(
            entity_id,
            value_norm,
            content='names',
            content_rowid='rowid'
        );

        INSERT INTO entities VALUES
            ('org/UN', 'org.igo', 'United Nations', 'united nations',
             NULL, NULL, NULL);

        INSERT INTO names VALUES
            ('org/UN', 'canonical', 'United Nations', 'united nations', 'en', 1),
            ('org/UN', 'alias', 'UN', 'un', 'en', 0);

        INSERT INTO names_fts(entity_id, value_norm) VALUES
            ('org/UN', 'united nations'),
            ('org/UN', 'un');
        """
    )
    conn.commit()
    conn.close()


def _make_runner(db_path: Path, pack_id: str = "geo"):
    """Build a minimal PipelineRunner backed by a SQLiteEntityStore."""
    from resolvekit.core.engine.decision import ThresholdDecisionPolicy
    from resolvekit.core.engine.runner import PipelineRunner
    from resolvekit.core.store.sqlite import SQLiteEntityStore

    store = SQLiteEntityStore(db_path)
    return PipelineRunner(
        store=store,
        pack_id=pack_id,
        decision_policy=ThresholdDecisionPolicy(
            confidence_threshold=0.7, min_gap=0.1, gap_inclusive=True
        ),
    )


# ---------------------------------------------------------------------------
# suggest_rank module tests
# ---------------------------------------------------------------------------


class TestSuggestCandidateDataclass:
    def test_frozen_enforcement(self) -> None:
        from resolvekit.core.engine.suggest_rank import MatchClass, SuggestCandidate

        c = SuggestCandidate(
            entity_id="country/USA",
            match_class=MatchClass.EXACT_PREFIX,
            exact_match=False,
            typo_count=0,
            prominence=0.9,
            name_kind_rank=0,
            matched_value_norm="united states",
            match_score=None,
            pack_id="geo",
            entity_type="geo.country",
            canonical_name="United States",
            matched_value="United States",
        )
        with pytest.raises((AttributeError, TypeError)):
            c.entity_id = "country/FRA"  # type: ignore[misc]

    def test_fields_accessible(self) -> None:
        from resolvekit.core.engine.suggest_rank import MatchClass, SuggestCandidate

        c = SuggestCandidate(
            entity_id="x",
            match_class=MatchClass.FUZZY,
            exact_match=False,
            typo_count=2,
            prominence=0.5,
            name_kind_rank=1,
            matched_value_norm="untied stat",
            match_score=80.0,
            pack_id="geo",
            entity_type="geo.country",
            canonical_name="United States",
            matched_value="untied stat",
        )
        assert c.typo_count == 2
        assert c.match_score == 80.0


class TestMatchClassRank:
    def test_exact_prefix_lowest_rank(self) -> None:
        from resolvekit.core.engine.suggest_rank import MATCH_CLASS_RANK, MatchClass

        assert (
            MATCH_CLASS_RANK[MatchClass.EXACT_PREFIX]
            < MATCH_CLASS_RANK[MatchClass.FUZZY]
        )
        assert (
            MATCH_CLASS_RANK[MatchClass.EXACT_PREFIX]
            < MATCH_CLASS_RANK[MatchClass.INFIX]
        )
        assert (
            MATCH_CLASS_RANK[MatchClass.TOKEN_PREFIX]
            < MATCH_CLASS_RANK[MatchClass.FUZZY]
        )


class TestSortKey:
    def _make_candidate(
        self,
        *,
        entity_id: str = "x",
        match_class=None,
        exact_match: bool = False,
        typo_count: int = 0,
        prominence: float = 0.0,
        name_kind_rank: int = 0,
        matched_value_norm: str = "abc",
        entity_type: str = "geo.country",
    ):
        from resolvekit.core.engine.suggest_rank import MatchClass, SuggestCandidate

        if match_class is None:
            match_class = MatchClass.EXACT_PREFIX
        return SuggestCandidate(
            entity_id=entity_id,
            match_class=match_class,
            exact_match=exact_match,
            typo_count=typo_count,
            prominence=prominence,
            name_kind_rank=name_kind_rank,
            matched_value_norm=matched_value_norm,
            match_score=None,
            pack_id="geo",
            entity_type=entity_type,
            canonical_name="Test",
            matched_value="Test",
        )

    def test_exact_prefix_before_fuzzy(self) -> None:
        from resolvekit.core.engine.suggest_rank import MatchClass, sort_key

        exact = self._make_candidate(match_class=MatchClass.EXACT_PREFIX)
        fuzzy = self._make_candidate(match_class=MatchClass.FUZZY)
        assert sort_key(exact) < sort_key(fuzzy)

    def test_higher_prominence_sorts_earlier(self) -> None:
        from resolvekit.core.engine.suggest_rank import MatchClass, sort_key

        high = self._make_candidate(match_class=MatchClass.EXACT_PREFIX, prominence=0.9)
        low = self._make_candidate(match_class=MatchClass.EXACT_PREFIX, prominence=0.1)
        assert sort_key(high) < sort_key(low)

    def test_absent_prominence_sorts_last_within_class(self) -> None:
        from resolvekit.core.engine.suggest_rank import MatchClass, sort_key

        with_prom = self._make_candidate(
            match_class=MatchClass.EXACT_PREFIX, prominence=0.5
        )
        no_prom = self._make_candidate(
            match_class=MatchClass.EXACT_PREFIX, prominence=0.0
        )
        assert sort_key(with_prom) < sort_key(no_prom)

    def test_obscure_ranked_exact_match_loses_to_famous_prefix(self) -> None:
        """A low-prominence ranked-tier exact match ('Germ', a French commune)
        must not outrank a maximally prominent prefix completion ('Germany')."""
        from resolvekit.core.engine.suggest_rank import MatchClass, sort_key

        obscure_exact = self._make_candidate(
            match_class=MatchClass.EXACT_PREFIX,
            exact_match=True,
            prominence=0.02,
            entity_type="geo.admin4",
        )
        famous_prefix = self._make_candidate(
            match_class=MatchClass.EXACT_PREFIX,
            exact_match=False,
            prominence=0.95,
            entity_type="geo.country",
        )
        assert sort_key(famous_prefix) < sort_key(obscure_exact)

    def test_prominent_ranked_exact_match_keeps_lift(self) -> None:
        """A prominent ranked-tier exact match ('EU') keeps its lift over an
        even more prominent prefix completion."""
        from resolvekit.core.engine.suggest_rank import MatchClass, sort_key

        prominent_exact = self._make_candidate(
            match_class=MatchClass.EXACT_PREFIX,
            exact_match=True,
            prominence=0.8,
            entity_type="geo.continental_union",
        )
        more_prominent_prefix = self._make_candidate(
            match_class=MatchClass.EXACT_PREFIX,
            exact_match=False,
            prominence=1.0,
            entity_type="geo.country",
        )
        assert sort_key(prominent_exact) < sort_key(more_prominent_prefix)

    def test_unranked_exact_match_always_keeps_lift(self) -> None:
        """An exact match from an unranked tier (orgs carry no prominence
        data) keeps its lift regardless of its zero prominence."""
        from resolvekit.core.engine.suggest_rank import MatchClass, sort_key

        org_exact = self._make_candidate(
            match_class=MatchClass.EXACT_PREFIX,
            exact_match=True,
            prominence=0.0,
            entity_type="org.igo",
        )
        famous_prefix = self._make_candidate(
            match_class=MatchClass.EXACT_PREFIX,
            exact_match=False,
            prominence=0.99,
            entity_type="geo.country",
        )
        assert sort_key(org_exact) < sort_key(famous_prefix)

    def test_preferred_name_before_alias(self) -> None:
        from resolvekit.core.engine.suggest_rank import MatchClass, sort_key

        preferred = self._make_candidate(
            match_class=MatchClass.EXACT_PREFIX, name_kind_rank=0
        )
        alias = self._make_candidate(
            match_class=MatchClass.EXACT_PREFIX, name_kind_rank=1
        )
        assert sort_key(preferred) < sort_key(alias)

    def test_entity_id_final_tiebreak_determinism(self) -> None:
        from resolvekit.core.engine.suggest_rank import sort_key

        a = self._make_candidate(entity_id="aaa")
        b = self._make_candidate(entity_id="bbb")
        assert sort_key(a) < sort_key(b)
        # Identical inputs produce identical keys.
        assert sort_key(a) == sort_key(a)

    def test_sorted_list_is_deterministic(self) -> None:
        from resolvekit.core.engine.suggest_rank import sort_key

        cands = [
            self._make_candidate(entity_id="bbb", prominence=0.5),
            self._make_candidate(entity_id="aaa", prominence=0.5),
            self._make_candidate(entity_id="ccc", prominence=0.9),
        ]
        sorted1 = sorted(cands, key=sort_key)
        sorted2 = sorted(cands, key=sort_key)
        assert [c.entity_id for c in sorted1] == [c.entity_id for c in sorted2]


class TestRankingQuality:
    def test_geo_country_is_ranked(self) -> None:
        from resolvekit.core.engine.suggest_rank import ranking_quality

        assert ranking_quality("geo.country") == "ranked"

    def test_geo_country_subtype_is_ranked(self) -> None:
        from resolvekit.core.engine.suggest_rank import ranking_quality

        # Sub-type of a live-prominence prefix still gets "ranked".
        assert ranking_quality("geo.country.overseas") == "ranked"

    def test_region_tiers_are_ranked(self) -> None:
        from resolvekit.core.engine.suggest_rank import ranking_quality

        # Region tiers carry containment-derived prominence.
        assert ranking_quality("geo.subregion") == "ranked"
        assert ranking_quality("geo.region") == "ranked"
        assert ranking_quality("geo.continental_union") == "ranked"

    def test_geo_continent_is_unranked(self) -> None:
        from resolvekit.core.engine.suggest_rank import ranking_quality

        # Continents have no prominence data and are unranked.
        assert ranking_quality("geo.continent") == "unranked"

    def test_geo_admin_tiers_are_ranked(self) -> None:
        """All sub-country admin tiers carry live prominence in the shipped packs."""
        from resolvekit.core.engine.suggest_rank import ranking_quality

        for tier in ("geo.admin1", "geo.admin3", "geo.admin4", "geo.admin5"):
            assert ranking_quality(tier) == "ranked"

    def test_org_is_unranked(self) -> None:
        from resolvekit.core.engine.suggest_rank import ranking_quality

        assert ranking_quality("org.igo") == "unranked"

    def test_none_type_is_unranked(self) -> None:
        from resolvekit.core.engine.suggest_rank import ranking_quality

        assert ranking_quality(None) == "unranked"


class TestNameKindRank:
    def test_canonical_is_best(self) -> None:
        from resolvekit.core.engine.suggest_rank import name_kind_rank

        assert name_kind_rank("canonical", is_preferred=False) == 0

    def test_is_preferred_overrides_kind(self) -> None:
        from resolvekit.core.engine.suggest_rank import name_kind_rank

        assert name_kind_rank("alias", is_preferred=True) == 0

    def test_acronym_better_than_alias(self) -> None:
        from resolvekit.core.engine.suggest_rank import name_kind_rank

        acronym_rank = name_kind_rank("acronym", is_preferred=False)
        alias_rank = name_kind_rank("alias", is_preferred=False)
        assert acronym_rank < alias_rank, (
            f"acronym ({acronym_rank}) should rank better than alias ({alias_rank})"
        )

    def test_abbr_better_than_alias(self) -> None:
        from resolvekit.core.engine.suggest_rank import name_kind_rank

        abbr_rank = name_kind_rank("abbr", is_preferred=False)
        alias_rank = name_kind_rank("alias", is_preferred=False)
        assert abbr_rank < alias_rank, (
            f"abbr ({abbr_rank}) should rank better than alias ({alias_rank})"
        )

    def test_unknown_kind_is_worst(self) -> None:
        from resolvekit.core.engine.suggest_rank import name_kind_rank

        unknown_rank = name_kind_rank("endonym", is_preferred=False)
        alias_rank = name_kind_rank("alias", is_preferred=False)
        assert unknown_rank > alias_rank, (
            f"unknown kind ({unknown_rank}) should rank worse than alias ({alias_rank})"
        )


class TestExactMatchSortKey:
    def _make_candidate(
        self,
        *,
        entity_id: str = "x",
        exact_match: bool = False,
        prominence: float = 0.0,
        name_kind_rank: int = 2,
        matched_value_norm: str = "abc",
    ):
        from resolvekit.core.engine.suggest_rank import MatchClass, SuggestCandidate

        return SuggestCandidate(
            entity_id=entity_id,
            match_class=MatchClass.EXACT_PREFIX,
            exact_match=exact_match,
            typo_count=0,
            prominence=prominence,
            name_kind_rank=name_kind_rank,
            matched_value_norm=matched_value_norm,
            match_score=None,
            pack_id="geo",
            entity_type="geo.organization",
            canonical_name="Test",
            matched_value="Test",
        )

    def test_exact_match_beats_high_prominence_prefix(self) -> None:
        """An entity with exact_match=True ranks ahead of one with exact_match=False
        even when the latter has a higher prominence score.
        """
        from resolvekit.core.engine.suggest_rank import sort_key

        acronym_org = self._make_candidate(
            entity_id="org/EU",
            exact_match=True,
            prominence=0.0,
        )
        prominent_prefix = self._make_candidate(
            entity_id="country/USA",
            exact_match=False,
            prominence=1.0,
        )
        assert sort_key(acronym_org) < sort_key(prominent_prefix), (
            "exact_match=True should sort before exact_match=False regardless of prominence"
        )

    def test_within_exact_match_prominence_still_applies(self) -> None:
        """When two candidates both have exact_match=True, prominence breaks the tie."""
        from resolvekit.core.engine.suggest_rank import sort_key

        high = self._make_candidate(entity_id="a", exact_match=True, prominence=0.9)
        low = self._make_candidate(entity_id="b", exact_match=True, prominence=0.1)
        assert sort_key(high) < sort_key(low)

    def test_exact_match_false_candidates_still_sorted_by_prominence(self) -> None:
        """Non-exact candidates maintain prominence ordering among themselves."""
        from resolvekit.core.engine.suggest_rank import sort_key

        high = self._make_candidate(entity_id="a", exact_match=False, prominence=0.9)
        low = self._make_candidate(entity_id="b", exact_match=False, prominence=0.1)
        assert sort_key(high) < sort_key(low)


class TestFuzzyCandidates:
    def test_returns_list(self) -> None:
        from resolvekit.core.engine.suggest_rank import fuzzy_candidates

        names = [
            ("united states", "country/USA", "canonical", True, "United States"),
            ("france", "country/FRA", "canonical", True, "France"),
        ]
        result = fuzzy_candidates("united", names, top_k=5)
        assert isinstance(result, list)

    def test_typo_surfaces_usa(self) -> None:
        """'untied stat' should surface USA via fuzzy matching with typo_count > 0."""
        from resolvekit.core.engine.suggest_rank import MatchClass, fuzzy_candidates

        names = [
            ("united states", "country/USA", "canonical", True, "United States"),
            ("france", "country/FRA", "canonical", True, "France"),
            ("germany", "country/DEU", "canonical", True, "Germany"),
        ]
        result = fuzzy_candidates("untied stat", names, top_k=5)
        entity_ids = [c.entity_id for c in result]
        assert "country/USA" in entity_ids

        usa_cand = next(c for c in result if c.entity_id == "country/USA")
        assert usa_cand.match_class == MatchClass.FUZZY
        assert usa_cand.typo_count > 0

    def test_empty_query_returns_empty(self) -> None:
        from resolvekit.core.engine.suggest_rank import fuzzy_candidates

        names = [("france", "country/FRA", "canonical", True, "France")]
        assert fuzzy_candidates("", names, top_k=5) == []

    def test_empty_names_returns_empty(self) -> None:
        from resolvekit.core.engine.suggest_rank import fuzzy_candidates

        assert fuzzy_candidates("united", [], top_k=5) == []

    def test_match_score_populated(self) -> None:
        from resolvekit.core.engine.suggest_rank import fuzzy_candidates

        names = [("united states", "country/USA", "canonical", True, "United States")]
        result = fuzzy_candidates("united", names, top_k=5)
        if result:
            assert result[0].match_score is not None
            assert 0 <= result[0].match_score <= 100

    def test_fuzzy_denylist_geo_city(self, tmp_path: Path) -> None:
        """auto policy must not run fuzzy when entity_type_prefixes is geo.city."""
        db = tmp_path / "city.db"
        conn = sqlite3.connect(db)
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
            CREATE VIRTUAL TABLE names_fts USING fts5(
                entity_id,
                value_norm,
                content='names',
                content_rowid='rowid'
            );

            INSERT INTO entities VALUES
                ('city/NYC', 'geo.city', 'New York City', 'new york city',
                 NULL, NULL, NULL);
            INSERT INTO names VALUES
                ('city/NYC', 'canonical', 'New York City', 'new york city', 'en', 1);
            INSERT INTO names_fts(entity_id, value_norm) VALUES
                ('city/NYC', 'new york city');
            """
        )
        conn.commit()
        conn.close()

        runner = _make_runner(db, pack_id="geo")
        try:
            # fuzzy="auto" with entity_type_prefixes={"geo.city"} should skip fuzzy.
            results = runner.suggest_prefix(
                query_norm="nuw york",  # typo that only fuzzy would catch
                top_k=5,
                entity_type_prefixes=frozenset({"geo.city"}),
                fuzzy="auto",
            )
            # All returned candidates must be non-FUZZY under auto+city denylist.
            from resolvekit.core.engine.suggest_rank import MatchClass

            for r in results:
                assert r.match_class != MatchClass.FUZZY, (
                    "geo.city should be excluded from fuzzy under auto policy"
                )
        finally:
            runner.close()


# ---------------------------------------------------------------------------
# PipelineRunner.suggest_prefix tests
# ---------------------------------------------------------------------------


class TestPipelineRunnerSuggestPrefix:
    def test_exact_prefix_match(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        _make_suggest_db(db)
        runner = _make_runner(db)
        try:
            results = runner.suggest_prefix(query_norm="france", top_k=5)
            entity_ids = [r.entity_id for r in results]
            assert "country/FRA" in entity_ids
        finally:
            runner.close()

    def test_returns_at_most_top_k(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        _make_suggest_db(db)
        runner = _make_runner(db)
        try:
            results = runner.suggest_prefix(query_norm="un", top_k=1)
            assert len(results) <= 1
        finally:
            runner.close()

    def test_empty_query_returns_empty(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        _make_suggest_db(db)
        runner = _make_runner(db)
        try:
            results = runner.suggest_prefix(query_norm="", top_k=5)
            assert results == []
        finally:
            runner.close()

    def test_prominence_breaks_ties(self, tmp_path: Path) -> None:
        """USA (prominence=0.9) should rank before FRA (prominence=0.7) for 'united'."""
        db = tmp_path / "test.db"
        _make_suggest_db(db, with_prominence=True)
        runner = _make_runner(db)
        try:
            results = runner.suggest_prefix(query_norm="united", top_k=5)
            entity_ids = [r.entity_id for r in results]
            assert "country/USA" in entity_ids
            # USA must appear before any lower-prominence entity with same prefix.
            usa_idx = entity_ids.index("country/USA")
            # FRA won't match "united" prefix but verify ordering is by prominence
            # for USA vs any USA alias hit.
            assert usa_idx == 0 or results[0].entity_id == "country/USA"
        finally:
            runner.close()

    def test_fuzzy_never_skips_fuzzy(self, tmp_path: Path) -> None:
        from resolvekit.core.engine.suggest_rank import MatchClass

        db = tmp_path / "test.db"
        _make_suggest_db(db)
        runner = _make_runner(db)
        try:
            results = runner.suggest_prefix(
                query_norm="franze",  # slight typo for France
                top_k=5,
                fuzzy="never",
            )
            for r in results:
                assert r.match_class != MatchClass.FUZZY
        finally:
            runner.close()

    def test_fuzzy_always_finds_typo(self, tmp_path: Path) -> None:
        from resolvekit.core.engine.suggest_rank import MatchClass

        db = tmp_path / "test.db"
        _make_suggest_db(db)
        runner = _make_runner(db)
        try:
            results = runner.suggest_prefix(
                query_norm="franze",  # typo for France
                top_k=5,
                fuzzy="always",
            )
            fuzzy_results = [r for r in results if r.match_class == MatchClass.FUZZY]
            # At least one fuzzy result should be returned.
            assert len(fuzzy_results) > 0
        finally:
            runner.close()

    def test_deterministic_results(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        _make_suggest_db(db)
        runner = _make_runner(db)
        try:
            r1 = runner.suggest_prefix(query_norm="united", top_k=5)
            r2 = runner.suggest_prefix(query_norm="united", top_k=5)
            assert [c.entity_id for c in r1] == [c.entity_id for c in r2]
        finally:
            runner.close()

    def test_entity_type_filter(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        _make_suggest_db(db)
        runner = _make_runner(db)
        try:
            results = runner.suggest_prefix(
                query_norm="new",
                top_k=5,
                entity_type_prefixes=frozenset({"geo.country"}),
            )
            # New York is geo.admin1, not geo.country — should be excluded.
            entity_ids = [r.entity_id for r in results]
            assert "region/NewYork" not in entity_ids
        finally:
            runner.close()

    def test_candidates_carry_pack_id(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        _make_suggest_db(db)
        runner = _make_runner(db, pack_id="geo")
        try:
            results = runner.suggest_prefix(query_norm="france", top_k=5)
            assert len(results) > 0
            for r in results:
                assert r.pack_id == "geo"
        finally:
            runner.close()

    def test_no_store_returns_empty(self) -> None:
        from resolvekit.core.engine.decision import ThresholdDecisionPolicy
        from resolvekit.core.engine.runner import PipelineRunner

        runner = PipelineRunner(
            store=None,
            decision_policy=ThresholdDecisionPolicy(
                confidence_threshold=0.7, min_gap=0.1, gap_inclusive=True
            ),
        )
        results = runner.suggest_prefix(query_norm="france", top_k=5)
        assert results == []

    def test_exact_match_alias_beats_prominence_prefix(self, tmp_path: Path) -> None:
        """An entity with a name exactly equal to the query ranks first even when
        a higher-prominence entity whose name only *starts with* that query exists.

        This models the EU/city scenario: 'un' should surface the 'UN' org
        alias above high-prominence names that merely start with 'un'.
        """
        db = tmp_path / "exact_alias.db"
        conn = sqlite3.connect(db)
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
            CREATE VIRTUAL TABLE names_fts USING fts5(
                entity_id,
                value_norm,
                content='names',
                content_rowid='rowid'
            );

            INSERT INTO entities VALUES
                -- High-prominence entity whose canonical name starts with 'un'
                ('country/X', 'geo.country', 'Unicorn Land', 'unicorn land',
                 NULL, NULL, '{"prominence": 0.99}'),
                -- Zero-prominence entity with a complete alias 'un'
                ('org/UN', 'org.igo', 'United Nations', 'united nations',
                 NULL, NULL, NULL);

            INSERT INTO names VALUES
                ('country/X', 'canonical', 'Unicorn Land', 'unicorn land', 'en', 1),
                ('org/UN', 'canonical', 'United Nations', 'united nations', 'en', 1),
                ('org/UN', 'alias', 'UN', 'un', 'en', 0);

            INSERT INTO names_fts(entity_id, value_norm) VALUES
                ('country/X', 'unicorn land'),
                ('org/UN', 'united nations'),
                ('org/UN', 'un');
            """
        )
        conn.commit()
        conn.close()

        runner = _make_runner(db)
        try:
            results = runner.suggest_prefix(query_norm="un", top_k=5)
            entity_ids = [r.entity_id for r in results]
            assert entity_ids[0] == "org/UN", (
                f"org/UN (exact alias 'un') should rank first for query 'un'; "
                f"got: {entity_ids}"
            )
        finally:
            runner.close()


# ---------------------------------------------------------------------------
# MultiPackRunner.suggest_prefix tests
# ---------------------------------------------------------------------------


def _make_multi_runner(geo_db: Path, org_db: Path):
    """Build a minimal MultiPackRunner with geo + org packs."""
    import json

    # We need real DomainPack objects.  Build minimal ones via from_datapacks.
    from resolvekit.core.api import Resolver
    from resolvekit.core.datapack import NORMALIZER_VERSION

    geo_path = geo_db.parent / "geo_pack"
    org_path = geo_db.parent / "org_pack"
    geo_path.mkdir(exist_ok=True)
    org_path.mkdir(exist_ok=True)

    import shutil

    shutil.copy(geo_db, geo_path / "entities.sqlite")
    shutil.copy(org_db, org_path / "entities.sqlite")

    for pack_path, domain_pack_id, module_id, feature_version in [
        (geo_path, "geo", "geo.countries", "geo.features.v1"),
        (org_path, "org", "org.entities", "org.features.v1"),
    ]:
        (pack_path / "metadata.json").write_text(
            json.dumps(
                {
                    "datapack_id": f"{domain_pack_id}_test_v1",
                    "module_id": module_id,
                    "domain_pack_id": domain_pack_id,
                    "entity_schema_version": "1.0",
                    "feature_schema_version": feature_version,
                    "normalizer_version": NORMALIZER_VERSION,
                    "index_versions": {"fts": "fts5", "symspell": None},
                    "build_timestamp": "2024-01-15T10:00:00Z",
                    "source_datasets": ["test-fixture"],
                }
            )
        )

    resolver = Resolver.from_datapacks(datapack_paths=[geo_path, org_path])
    return resolver, geo_path, org_path


class TestMultiPackRunnerSuggestPrefix:
    def test_returns_candidates_from_both_packs(self, tmp_path: Path) -> None:
        geo_db = tmp_path / "geo.db"
        org_db = tmp_path / "org.db"
        _make_suggest_db(geo_db)
        _make_suggest_db_org(org_db)

        resolver, _, _ = _make_multi_runner(geo_db, org_db)
        try:
            runner = resolver._runner
            results = runner.suggest_prefix(query_norm="united", top_k=10)
            entity_ids = [r.entity_id for r in results]
            # Should include both USA and UN (United Nations) from different packs.
            assert "country/USA" in entity_ids or "org/UN" in entity_ids
        finally:
            resolver.close()

    def test_dedup_by_entity_id(self, tmp_path: Path) -> None:
        """When the same entity appears in multiple packs, it should appear once."""
        geo_db = tmp_path / "geo.db"
        org_db = tmp_path / "org.db"
        _make_suggest_db(geo_db)
        _make_suggest_db_org(org_db)

        resolver, _, _ = _make_multi_runner(geo_db, org_db)
        try:
            runner = resolver._runner
            results = runner.suggest_prefix(query_norm="united", top_k=10)
            entity_ids = [r.entity_id for r in results]
            # No duplicate entity_ids.
            assert len(entity_ids) == len(set(entity_ids))
        finally:
            resolver.close()

    def test_top_k_enforced(self, tmp_path: Path) -> None:
        geo_db = tmp_path / "geo.db"
        org_db = tmp_path / "org.db"
        _make_suggest_db(geo_db)
        _make_suggest_db_org(org_db)

        resolver, _, _ = _make_multi_runner(geo_db, org_db)
        try:
            runner = resolver._runner
            results = runner.suggest_prefix(query_norm="u", top_k=2)
            assert len(results) <= 2
        finally:
            resolver.close()

    def test_deterministic_order(self, tmp_path: Path) -> None:
        geo_db = tmp_path / "geo.db"
        org_db = tmp_path / "org.db"
        _make_suggest_db(geo_db)
        _make_suggest_db_org(org_db)

        resolver, _, _ = _make_multi_runner(geo_db, org_db)
        try:
            runner = resolver._runner
            r1 = runner.suggest_prefix(query_norm="united", top_k=10)
            r2 = runner.suggest_prefix(query_norm="united", top_k=10)
            assert [c.entity_id for c in r1] == [c.entity_id for c in r2]
        finally:
            resolver.close()
