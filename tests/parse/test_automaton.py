"""Tests for PackAutomaton - Aho-Corasick entity detector.

All tests use bundled SMALL geo data (countries only) or hand-built
SQLite fixtures. LARGE/city data is remote — tests must remain CI-safe
and offline-safe.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest

from resolvekit.core.datapack import NORMALIZER_VERSION
from resolvekit.core.parse.automaton import PackAutomaton
from resolvekit.core.store.sqlite import SQLiteEntityStore
from resolvekit.packs.geo.pack import GEO_NORMALIZATION_PROFILE
from resolvekit.packs.org.pack import ORG_NORMALIZATION_PROFILE

# ---------------------------------------------------------------------------
# Bundled geo countries store path
# ---------------------------------------------------------------------------

_COUNTRIES_DB = (
    Path(__file__).parent.parent.parent
    / "src/resolvekit/_data/geo/countries/entities.sqlite"
)


@pytest.fixture
def countries_store() -> Generator[SQLiteEntityStore, None, None]:
    """Open the bundled countries store (read-only)."""
    store = SQLiteEntityStore(_COUNTRIES_DB)
    yield store
    store.close()


@pytest.fixture
def countries_automaton(countries_store: SQLiteEntityStore) -> PackAutomaton:
    """Build a SMALL geo automaton over the bundled countries data."""
    from resolvekit.packs.geo.sources.symspell import _SMALL_ENTITY_TYPE_PREFIXES

    return PackAutomaton(
        store=countries_store,
        profile=GEO_NORMALIZATION_PROFILE,
        pack_id="geo",
        small_prefixes=_SMALL_ENTITY_TYPE_PREFIXES,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_synthetic_store(tmp_path: Path) -> SQLiteEntityStore:
    """Build a minimal store with a multi-id collision ("georgia") and an org.

    Entities:
      country/KEN  geo.country  Kenya
      country/GEO  geo.country  Georgia  ← collides with admin1/GEO-TB
      admin1/GEO-TB  geo.admin1  Georgia  ← same surface
      admin1/KEN-001  geo.admin1  Nairobi County
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


def _build_org_store(tmp_path: Path) -> SQLiteEntityStore:
    """Build a minimal org store with punctuation in surface forms."""
    db_path = tmp_path / "orgs.sqlite"
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
            ('org/ATT', 'org.company', 'AT&T', 'att', NULL, NULL),
            ('org/UN', 'org.igo', 'United Nations', 'united nations', NULL, NULL);

        INSERT INTO names VALUES
            ('org/ATT', 'canonical', 'AT&T', 'att', 'en', NULL, 1),
            ('org/UN', 'canonical', 'United Nations', 'united nations', 'en', NULL, 1);
        """
    )
    conn.commit()
    conn.close()
    return SQLiteEntityStore(db_path)


# ---------------------------------------------------------------------------
# Basic detection with correct raw offsets
# ---------------------------------------------------------------------------


def test_basic_detection_kenya_somalia(
    countries_automaton: PackAutomaton,
) -> None:
    """find() returns hits for Kenya and Somalia with correct raw offsets."""
    raw = "drought in Kenya and Somalia"
    hits = countries_automaton.find(raw)

    # Collect by surface.
    by_surface = {h.surface: h for h in hits}
    assert "Kenya" in by_surface, f"Kenya not found in {list(by_surface)}"
    assert "Somalia" in by_surface, f"Somalia not found in {list(by_surface)}"

    kenya_hit = by_surface["Kenya"]
    somalia_hit = by_surface["Somalia"]

    # Raw offsets must recover the exact surface.
    assert raw[kenya_hit.start : kenya_hit.end] == "Kenya"
    assert raw[somalia_hit.start : somalia_hit.end] == "Somalia"

    # Entity IDs must be non-empty.
    assert kenya_hit.entity_ids
    assert somalia_hit.entity_ids

    # Pack ID propagated.
    assert kenya_hit.pack_id == "geo"
    assert somalia_hit.pack_id == "geo"


# ---------------------------------------------------------------------------
# Word-boundary rejection
# ---------------------------------------------------------------------------


def test_word_boundary_oman_in_romania(
    countries_automaton: PackAutomaton,
) -> None:
    """'Oman' must NOT be detected inside 'Romania'."""
    hits = countries_automaton.find("Romania is a country")
    surfaces = [h.surface for h in hits]
    assert "Oman" not in surfaces, f"Oman should not match inside Romania: {surfaces}"


def test_word_boundary_us_in_campus(
    countries_automaton: PackAutomaton,
) -> None:
    """'US' must NOT be detected inside 'campus'."""
    hits = countries_automaton.find("on campus")
    surfaces = [h.surface for h in hits]
    # 'us' (or 'US') should not appear since it's glued to 'camp'.
    assert not any(s.lower() == "us" for s in surfaces), (
        f"'us' should not match inside 'campus': {surfaces}"
    )


def test_word_boundary_mali_in_malice(
    countries_automaton: PackAutomaton,
) -> None:
    """'Mali' must NOT be detected inside 'Malice'."""
    hits = countries_automaton.find("Malice aforethought")
    surfaces = [h.surface for h in hits]
    assert not any(s.lower() == "mali" for s in surfaces), (
        f"'mali' should not match inside 'Malice': {surfaces}"
    )


def test_word_boundary_mali_standalone(
    countries_automaton: PackAutomaton,
) -> None:
    """Standalone 'Mali' DOES produce a hit."""
    hits = countries_automaton.find("Mali")
    surfaces = [h.surface.lower() for h in hits]
    assert "mali" in surfaces, f"Expected standalone 'Mali' hit, got {surfaces}"


# ---------------------------------------------------------------------------
# Many-to-one side-table (collision)
# ---------------------------------------------------------------------------


def test_side_table_many_to_one(tmp_path: Path) -> None:
    """A surface form with multiple entity_ids returns all of them."""
    store = _build_synthetic_store(tmp_path)
    try:
        automaton = PackAutomaton(
            store=store,
            profile=GEO_NORMALIZATION_PROFILE,
            pack_id="geo",
            small_prefixes=None,
        )
        hits = automaton.find("The state of Georgia")
        georgia_hits = [h for h in hits if h.surface.lower() == "georgia"]
        assert georgia_hits, "Expected a 'georgia' hit"
        # Should contain both country/GEO and admin1/GEO-TB.
        all_ids = set(georgia_hits[0].entity_ids)
        assert "country/GEO" in all_ids, f"country/GEO missing: {all_ids}"
        assert "admin1/GEO-TB" in all_ids, f"admin1/GEO-TB missing: {all_ids}"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Offset through normalization
# ---------------------------------------------------------------------------


def test_offset_through_normalization_markdown_html(
    countries_automaton: PackAutomaton,
) -> None:
    """Hits from markdown/HTML raw input carry raw-text offsets."""
    raw = "**Kenya** &amp; Somalia"
    hits = countries_automaton.find(raw)
    by_surface_lower = {h.surface.lower(): h for h in hits}

    # Kenya must be found and its surface must be EXACTLY "Kenya" (not "Kenya**").
    assert "kenya" in by_surface_lower, f"Kenya not detected in {raw!r}: hits={hits}"
    kenya_hit = by_surface_lower["kenya"]
    assert raw[kenya_hit.start : kenya_hit.end] == "Kenya", (
        f"Expected exact 'Kenya', got {raw[kenya_hit.start : kenya_hit.end]!r}"
    )

    # Somalia must be found with exact surface.
    assert "somalia" in by_surface_lower, (
        f"Somalia not detected in {raw!r}: hits={hits}"
    )
    somalia_hit = by_surface_lower["somalia"]
    assert raw[somalia_hit.start : somalia_hit.end] == "Somalia", (
        f"Somalia raw surface mismatch: {raw[somalia_hit.start : somalia_hit.end]!r}"
    )


# ---------------------------------------------------------------------------
# Profile honored (org punctuation stripping)
# ---------------------------------------------------------------------------


def test_profile_org_punctuation(tmp_path: Path) -> None:
    """Org profile strips punctuation so 'AT&T' matches the 'att' pattern."""
    store = _build_org_store(tmp_path)
    try:
        automaton = PackAutomaton(
            store=store,
            profile=ORG_NORMALIZATION_PROFILE,
            pack_id="org",
            small_prefixes=None,
        )
        # The store's canonical norm for AT&T is 'att'.
        # The raw input 'AT&T' normalizes to 'att' under ORG_NORMALIZATION_PROFILE,
        # so the automaton should find it.
        hits = automaton.find("AT&T signed the deal")
        entity_ids_found = {eid for h in hits for eid in h.entity_ids}
        assert "org/ATT" in entity_ids_found, (
            f"Expected org/ATT hit for 'AT&T', got {entity_ids_found}"
        )
    finally:
        store.close()


def test_profile_org_construction_uses_org_profile(tmp_path: Path) -> None:
    """PackAutomaton built with ORG_NORMALIZATION_PROFILE stores the profile."""
    store = _build_org_store(tmp_path)
    try:
        automaton = PackAutomaton(
            store=store,
            profile=ORG_NORMALIZATION_PROFILE,
            pack_id="org",
            small_prefixes=None,
        )
        assert automaton._profile is ORG_NORMALIZATION_PROFILE
        assert automaton._profile.strip_punctuation is True
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Import-guard isolation
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# code_shaped side-table
# ---------------------------------------------------------------------------


def _build_code_shaped_store(tmp_path: Path) -> SQLiteEntityStore:
    """Build a store with an all-caps alias AND a canonical name for contrast.

    Names:
      country/AND  alias      'AND'     → code-shaped (all-caps, len=3)
      country/AND  canonical  'Andorra' → NOT code-shaped
      country/KEN  canonical  'Kenya'   → NOT code-shaped (real name)
    """
    db_path = tmp_path / "code_shaped.sqlite"
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
            ('country/KEN', 'geo.country', 'Kenya',   'kenya',   NULL, NULL);

        INSERT INTO names VALUES
            ('country/AND', 'canonical', 'Andorra', 'andorra', 'en', NULL, 1),
            ('country/AND', 'alias',     'AND',     'and',     NULL, NULL, 0),
            ('country/KEN', 'canonical', 'Kenya',   'kenya',   'en', NULL, 1);
        """
    )
    conn.commit()
    conn.close()
    return SQLiteEntityStore(db_path)


def _build_org_code_shaped_store(tmp_path: Path) -> SQLiteEntityStore:
    """Build a minimal org store with a code-shaped alias (GAP)."""
    db_path = tmp_path / "org_code_shaped.sqlite"
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
            ('org/gap_test', 'org.igo', 'GAP Test', 'gap test', NULL, NULL);

        INSERT INTO names VALUES
            ('org/gap_test', 'canonical', 'GAP Test', 'gap test', 'en', NULL, 1),
            ('org/gap_test', 'alias',     'GAP',      'gap',      NULL, NULL, 0);
        """
    )
    conn.commit()
    conn.close()
    return SQLiteEntityStore(db_path)


def test_code_shaped_true_for_all_caps_alias(tmp_path: Path) -> None:
    """code_shaped is True for a hit whose only pattern is an all-caps alias."""
    store = _build_code_shaped_store(tmp_path)
    try:
        automaton = PackAutomaton(
            store=store,
            profile=GEO_NORMALIZATION_PROFILE,
            pack_id="geo",
            small_prefixes=None,
        )
        # 'AND' must produce a hit with code_shaped=True.
        hits = automaton.find("AND")
        and_hits = [h for h in hits if h.surface == "AND"]
        assert and_hits, f"Expected a hit for 'AND', got {hits}"
        assert and_hits[0].code_shaped, (
            "Hit for all-caps alias 'AND' must have code_shaped=True"
        )
    finally:
        store.close()


def test_code_shaped_false_for_canonical_name(tmp_path: Path) -> None:
    """code_shaped is False for a hit produced by a canonical name pattern."""
    store = _build_code_shaped_store(tmp_path)
    try:
        automaton = PackAutomaton(
            store=store,
            profile=GEO_NORMALIZATION_PROFILE,
            pack_id="geo",
            small_prefixes=None,
        )
        # 'Kenya' is a canonical name — code_shaped must be False.
        hits = automaton.find("Kenya")
        kenya_hits = [h for h in hits if h.surface.lower() == "kenya"]
        assert kenya_hits, f"Expected a hit for 'Kenya', got {hits}"
        assert not kenya_hits[0].code_shaped, (
            "Hit for canonical name 'Kenya' must have code_shaped=False"
        )
    finally:
        store.close()


def test_code_shaped_false_for_canonical_and_alias_collision(tmp_path: Path) -> None:
    """When value_norm is shared by an alias AND a canonical row, code_shaped=False.

    'and' is both Andorra's alias (code-shaped) AND, if added as a canonical
    name for some entity, the combined pattern is NOT code-shaped — the
    all-rows-must-pass rule protects recall.
    """
    db_path = tmp_path / "collision.sqlite"
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
            ('place/AND',   'geo.country', 'And',     'and',     NULL, NULL);

        INSERT INTO names VALUES
            -- code-shaped alias
            ('country/AND', 'alias',     'AND', 'and', NULL, NULL, 0),
            -- canonical name for same surface — poisons code_shaped to False
            ('place/AND',   'canonical', 'And', 'and', 'en', NULL, 1);
        """
    )
    conn.commit()
    conn.close()
    store = SQLiteEntityStore(db_path)
    try:
        automaton = PackAutomaton(
            store=store,
            profile=GEO_NORMALIZATION_PROFILE,
            pack_id="geo",
            small_prefixes=None,
        )
        hits = automaton.find("AND")
        and_hits = [h for h in hits if h.surface == "AND"]
        assert and_hits, f"Expected a hit for 'AND' in collision fixture, got {hits}"
        # Because 'and' value_norm has both an alias row (code-shaped) AND a
        # canonical row (not code-shaped), the pattern must not be code_shaped.
        assert not and_hits[0].code_shaped, (
            "Pattern shared by alias+canonical must have code_shaped=False (recall guard)"
        )
    finally:
        store.close()


def test_code_shaped_true_for_org_alias(tmp_path: Path) -> None:
    """code_shaped is True for an all-caps alias in the org pack (pack-agnostic)."""
    store = _build_org_code_shaped_store(tmp_path)
    try:
        automaton = PackAutomaton(
            store=store,
            profile=ORG_NORMALIZATION_PROFILE,
            pack_id="org",
            small_prefixes=None,
        )
        hits = automaton.find("GAP")
        gap_hits = [h for h in hits if h.surface == "GAP"]
        assert gap_hits, f"Expected a hit for 'GAP', got {hits}"
        assert gap_hits[0].code_shaped, (
            "Hit for all-caps org alias 'GAP' must have code_shaped=True"
        )
    finally:
        store.close()


def test_module_import_succeeds_without_ahocorasick_rs() -> None:
    """Importing resolvekit.core.parse.automaton never requires ahocorasick_rs."""
    # If this test runs, the import already succeeded.  Just assert the module
    # attribute exists and that the class is importable.
    import resolvekit.core.parse.automaton as am

    assert hasattr(am, "PackAutomaton")
    assert hasattr(am, "_load_ac")


# ---------------------------------------------------------------------------
# SMALL gating reduces pattern enumeration
# ---------------------------------------------------------------------------


def test_small_gating_reduces_patterns(
    countries_store: SQLiteEntityStore,
) -> None:
    """SMALL build enumerates fewer (or equal) patterns than the full build."""
    from resolvekit.packs.geo.sources.symspell import _SMALL_ENTITY_TYPE_PREFIXES

    small_automaton = PackAutomaton(
        store=countries_store,
        profile=GEO_NORMALIZATION_PROFILE,
        pack_id="geo",
        small_prefixes=_SMALL_ENTITY_TYPE_PREFIXES,
    )
    full_automaton = PackAutomaton(
        store=countries_store,
        profile=GEO_NORMALIZATION_PROFILE,
        pack_id="geo",
        small_prefixes=None,
    )

    # For the countries-only store, all entities ARE geo.country, so both
    # builds should have the same count.  But the SMALL build must never
    # exceed the full build.
    assert small_automaton.pattern_count <= full_automaton.pattern_count, (
        f"SMALL ({small_automaton.pattern_count}) > FULL ({full_automaton.pattern_count})"
    )
    # Sanity: both builds must have at least one pattern.
    assert small_automaton.pattern_count > 0
    assert full_automaton.pattern_count > 0


def test_small_gating_excludes_non_small_types(tmp_path: Path) -> None:
    """SMALL build with prefix filter excludes admin1 names from a mixed store."""
    store = _build_synthetic_store(tmp_path)
    try:
        # Build SMALL (country-only).
        small_automaton = PackAutomaton(
            store=store,
            profile=GEO_NORMALIZATION_PROFILE,
            pack_id="geo",
            small_prefixes=frozenset({"geo.country"}),
        )
        # Build FULL.
        full_automaton = PackAutomaton(
            store=store,
            profile=GEO_NORMALIZATION_PROFILE,
            pack_id="geo",
            small_prefixes=None,
        )
        # Full has more patterns (includes "nairobi county" from admin1).
        assert full_automaton.pattern_count > small_automaton.pattern_count, (
            f"Full ({full_automaton.pattern_count}) should exceed "
            f"small ({small_automaton.pattern_count}) with mixed store"
        )
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Test — build_or_get_automaton cache
# ---------------------------------------------------------------------------


def test_build_or_get_automaton_caches(
    countries_store: SQLiteEntityStore,
) -> None:
    """build_or_get_automaton returns the same object on repeated calls."""
    from resolvekit.core.parse.automaton import build_or_get_automaton, invalidate
    from resolvekit.packs.geo.sources.symspell import _SMALL_ENTITY_TYPE_PREFIXES

    a1 = build_or_get_automaton(
        store=countries_store,
        profile=GEO_NORMALIZATION_PROFILE,
        pack_id="geo",
        small_or_full="small",
        small_prefixes=_SMALL_ENTITY_TYPE_PREFIXES,
        data_version_summary="v1",
    )
    a2 = build_or_get_automaton(
        store=countries_store,
        profile=GEO_NORMALIZATION_PROFILE,
        pack_id="geo",
        small_or_full="small",
        small_prefixes=_SMALL_ENTITY_TYPE_PREFIXES,
        data_version_summary="v1",
    )
    assert a1 is a2

    # After invalidation, a new build is returned.
    invalidate(countries_store)
    a3 = build_or_get_automaton(
        store=countries_store,
        profile=GEO_NORMALIZATION_PROFILE,
        pack_id="geo",
        small_or_full="small",
        small_prefixes=_SMALL_ENTITY_TYPE_PREFIXES,
        data_version_summary="v1",
    )
    assert a3 is not a1


def test_resolver_close_evicts_automaton_cache(tmp_path: Path) -> None:
    """Resolver.close() evicts its stores' automaton-cache entries.

    Verifies the `invalidate()` seam — the same call Resolver.close() makes —
    removes the entry and does not strong-ref the store indefinitely.
    """
    from resolvekit.core.parse.automaton import _AUTOMATON_CACHE, build_or_get_automaton
    from resolvekit.packs.geo.sources.symspell import _SMALL_ENTITY_TYPE_PREFIXES

    store = _build_synthetic_store(tmp_path)

    # Populate the cache with an entry for this store.
    build_or_get_automaton(
        store=store,
        profile=GEO_NORMALIZATION_PROFILE,
        pack_id="geo",
        small_or_full="small",
        small_prefixes=_SMALL_ENTITY_TYPE_PREFIXES,
        data_version_summary="test",
    )
    before_size = len(_AUTOMATON_CACHE)
    assert any(k[0] == id(store) for k in _AUTOMATON_CACHE), (
        "Cache should contain an entry for this store"
    )

    from resolvekit.core.parse.automaton import invalidate

    invalidate(store)
    after_size = len(_AUTOMATON_CACHE)
    assert after_size < before_size, (
        f"Cache should shrink after invalidate: before={before_size}, after={after_size}"
    )
    assert not any(k[0] == id(store) for k in _AUTOMATON_CACHE), (
        "No cache entries should remain for the evicted store"
    )


def test_resolver_close_evicts_via_resolver(tmp_path: Path) -> None:
    """Resolver.close() path evicts automaton-cache entries for its stores.

    Builds a real Resolver, calls parse() to populate the cache, then
    asserts the cache loses the entries after close().
    """
    import json
    import sqlite3

    from resolvekit.core.parse.automaton import _AUTOMATON_CACHE

    # Build a minimal datapack.
    db_path = tmp_path / "entities.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE entities (
            entity_id TEXT PRIMARY KEY, entity_type TEXT NOT NULL,
            canonical_name TEXT NOT NULL, canonical_name_norm TEXT NOT NULL,
            valid_from TEXT, valid_until TEXT
        );
        CREATE TABLE names (
            entity_id TEXT NOT NULL, name_kind TEXT NOT NULL, value TEXT NOT NULL,
            value_norm TEXT NOT NULL, lang TEXT, is_preferred INTEGER DEFAULT 0
        );
        CREATE TABLE codes (
            entity_id TEXT NOT NULL, system TEXT NOT NULL,
            value TEXT NOT NULL, value_norm TEXT NOT NULL,
            PRIMARY KEY (entity_id, system)
        );
        CREATE TABLE relations (
            entity_id TEXT NOT NULL, relation_type TEXT NOT NULL, target_id TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE names_fts USING fts5(entity_id, value_norm);
        INSERT INTO entities VALUES ('country/KEN', 'geo.country', 'Kenya', 'kenya', NULL, NULL);
        INSERT INTO names VALUES ('country/KEN', 'canonical', 'Kenya', 'kenya', 'en', 1);
        INSERT INTO names_fts(entity_id, value_norm) VALUES ('country/KEN', 'kenya');
        """
    )
    conn.commit()
    conn.close()
    (tmp_path / "metadata.json").write_text(
        json.dumps(
            {
                "datapack_id": "automaton_close_test",
                "module_id": "geo.countries",
                "domain_pack_id": "geo",
                "entity_schema_version": "1.0",
                "feature_schema_version": "geo.features.v1",
                "normalizer_version": NORMALIZER_VERSION,
                "index_versions": {"fts": "fts5", "symspell": None},
                "build_timestamp": "2026-06-04T00:00:00Z",
                "source_datasets": ["close-test"],
            }
        )
    )

    from resolvekit.core.api.resolver import Resolver

    resolver = Resolver.from_datapacks(datapack_paths=[tmp_path])
    # parse() builds and caches the automaton for this store.
    resolver.parse("Kenya")

    store = resolver.store_for("geo")
    assert any(k[0] == id(store) for k in _AUTOMATON_CACHE), (
        "Cache should have an entry after parse()"
    )
    before_size = len(_AUTOMATON_CACHE)

    resolver.close()

    after_size = len(_AUTOMATON_CACHE)
    assert after_size < before_size, (
        f"Cache should shrink after resolver.close(): before={before_size}, after={after_size}"
    )
    assert not any(k[0] == id(store) for k in _AUTOMATON_CACHE), (
        "No cache entries should remain for the closed resolver's store"
    )
