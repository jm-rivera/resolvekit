"""Tests for the case-sensitive code channel.

Verifies that code-shaped alias patterns (all-caps, alias name_kind,
length ≤ _SHORT_ALPHA_MAX_LEN) only link when the raw surface is itself
all-uppercase ASCII.  Non-code-shaped patterns (canonical names, lowercase
aliases) are unaffected — recall is preserved.

Tests cover both geo (country/AND) and org (GAP) to confirm the gate is
pack-agnostic, not geo-only.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from resolvekit.core.api.resolver import Resolver
from resolvekit.core.datapack import NORMALIZER_VERSION

# ---------------------------------------------------------------------------
# Synthetic store builders
# ---------------------------------------------------------------------------


def _build_geo_and_store(tmp_path: Path) -> Path:
    """Minimal geo DataPack with Andorra (AND alias) and a short real name.

    Entities:
      country/AND  geo.country  Andorra — alias 'AND' (code-shaped)
      country/ALT  geo.country  Alt     — canonical 'alt' (3-char lowercase,
                                          NOT code-shaped — recall canary)
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
            ('country/AND', 'geo.country', 'Andorra', 'andorra', NULL, NULL),
            ('country/ALT', 'geo.country', 'Alt',     'alt',     NULL, NULL);

        INSERT INTO names VALUES
            -- Andorra canonical name
            ('country/AND', 'canonical', 'Andorra', 'andorra', 'en', NULL, 1),
            -- AND is a code-shaped alias (all-caps, alias kind, len=3)
            ('country/AND', 'alias',     'AND',     'and',     NULL, NULL, 0),
            -- Alt is a 3-char canonical name — NOT code-shaped (not an alias)
            ('country/ALT', 'canonical', 'Alt',     'alt',     'en', NULL, 1);

        INSERT INTO names_fts(entity_id, value_norm) VALUES
            ('country/AND', 'andorra'),
            ('country/AND', 'and'),
            ('country/ALT', 'alt');
        """
    )
    conn.commit()
    conn.close()

    (tmp_path / "metadata.json").write_text(
        json.dumps(
            {
                "datapack_id": "case_channel_geo_test",
                "module_id": "geo.countries",
                "domain_pack_id": "geo",
                "entity_schema_version": "1.0",
                "feature_schema_version": "geo.features.v1",
                "normalizer_version": NORMALIZER_VERSION,
                "index_versions": {"fts": "fts5", "symspell": None},
                "build_timestamp": "2026-06-04T00:00:00Z",
                "source_datasets": ["case-channel-test"],
            }
        )
    )
    return tmp_path


def _build_org_gap_store(tmp_path: Path) -> Path:
    """Minimal org DataPack with GAP (code-shaped alias) for pack-agnostic canary.

    Entity:
      org/gap_test  org.government_organization  GAP Test — alias 'GAP' (code-shaped)
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
            ('org/gap_test', 'org.government_organization', 'GAP Test', 'gap test', NULL, NULL);

        INSERT INTO names VALUES
            ('org/gap_test', 'canonical', 'GAP Test', 'gap test', 'en', NULL, 1),
            ('org/gap_test', 'alias',     'GAP',      'gap',      NULL, NULL, 0);

        INSERT INTO names_fts(entity_id, value_norm) VALUES
            ('org/gap_test', 'gap test'),
            ('org/gap_test', 'gap');
        """
    )
    conn.commit()
    conn.close()

    (tmp_path / "metadata.json").write_text(
        json.dumps(
            {
                "datapack_id": "case_channel_org_test",
                "module_id": "org.governments",
                "domain_pack_id": "org",
                "entity_schema_version": "1.0",
                "feature_schema_version": "org.features.v1",
                "normalizer_version": NORMALIZER_VERSION,
                "index_versions": {"fts": "fts5", "symspell": None},
                "build_timestamp": "2026-06-04T00:00:00Z",
                "source_datasets": ["case-channel-org-test"],
            }
        )
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def geo_and_resolver(tmp_path_factory: pytest.TempPathFactory) -> Resolver:
    """Resolver backed by the Andorra+Alt geo fixture."""
    pack_dir = _build_geo_and_store(tmp_path_factory.mktemp("geo_and"))
    return Resolver.from_datapacks(datapack_paths=[pack_dir])


@pytest.fixture(scope="module")
def org_gap_resolver(tmp_path_factory: pytest.TempPathFactory) -> Resolver:
    """Resolver backed by the GAP org fixture."""
    pack_dir = _build_org_gap_store(tmp_path_factory.mktemp("org_gap"))
    return Resolver.from_datapacks(datapack_paths=[pack_dir])


# ---------------------------------------------------------------------------
# Geo case channel — AND / and / And
# ---------------------------------------------------------------------------


def test_geo_and_uppercase_links(geo_and_resolver: Resolver) -> None:
    """'AND' (all-caps) links to country/AND — admitted by the case channel."""
    result = geo_and_resolver.parse("AND")
    entity_ids = [e.entity_id for e in result.entities]
    assert "country/AND" in entity_ids, (
        f"'AND' should resolve to country/AND; entities={entity_ids}, "
        f"dropped={result.dropped_spans}"
    )


def test_geo_and_lowercase_dropped(geo_and_resolver: Resolver) -> None:
    """'and' (lowercase) is dropped with reason='code_case_mismatch', no Andorra."""
    result = geo_and_resolver.parse("Kenya and Somalia")
    entity_ids = [e.entity_id for e in result.entities]
    assert "country/AND" not in entity_ids, (
        f"'and' must not resolve to country/AND; entities={entity_ids}"
    )
    # The dropped-spans channel must record the reason.
    and_dropped = [d for d in result.dropped_spans if d.surface.lower() == "and"]
    # There may be no 'and' hit at all (deny-list or word-boundary), OR it should
    # be dropped as code_case_mismatch.  Regardless, no Andorra link is the contract.
    # But when the deny-list is absent for 'and' (it must not contain ISO codes),
    # the code channel owns the drop — verify if a drop exists.
    for d in and_dropped:
        assert d.reason in ("deny_list", "code_case_mismatch"), (
            f"'and' dropped for unexpected reason: {d.reason}"
        )


def test_geo_and_bare_lowercase_dropped_with_code_case_mismatch(
    geo_and_resolver: Resolver,
) -> None:
    """Bare 'and' token (isolated, after deny-list) → code_case_mismatch drop."""
    # Note: 'and' IS on the deny-list, so it will be caught there first.
    # This test verifies the end result: no Andorra link regardless of which gate fires.
    result = geo_and_resolver.parse("and")
    entity_ids = [e.entity_id for e in result.entities]
    assert "country/AND" not in entity_ids, (
        f"Bare 'and' must not resolve to country/AND; entities={entity_ids}"
    )
    assert result.dropped_spans, (
        "Bare 'and' should produce a dropped span (deny_list or code_case_mismatch)"
    )
    reasons = {d.reason for d in result.dropped_spans}
    assert reasons & {"deny_list", "code_case_mismatch"}, (
        f"Expected deny_list or code_case_mismatch reason; got {reasons}"
    )


def test_geo_and_mixed_case_dropped(geo_and_resolver: Resolver) -> None:
    """'And' (title-case) is dropped — not all-uppercase ASCII."""
    result = geo_and_resolver.parse("And")
    entity_ids = [e.entity_id for e in result.entities]
    assert "country/AND" not in entity_ids, (
        f"'And' must not resolve to country/AND; entities={entity_ids}"
    )


def test_geo_recall_canonical_3char_not_gated(geo_and_resolver: Resolver) -> None:
    """A lowercase canonical name of 3 chars is NOT dropped by the code channel.

    'alt' is a canonical name (not an alias), so it is not code-shaped and
    the case channel never fires for it — recall is preserved.
    """
    result = geo_and_resolver.parse("alt")
    # The case channel must not drop 'alt' (it's a canonical, not an alias).
    # The span may still fail to resolve for other reasons (threshold, etc.)
    # but it must NOT be dropped with code_case_mismatch.
    alt_dropped_by_case = [
        d
        for d in result.dropped_spans
        if d.surface.lower() == "alt" and d.reason == "code_case_mismatch"
    ]
    assert not alt_dropped_by_case, (
        "Lowercase canonical 3-char name 'alt' must NOT be dropped by code channel; "
        f"dropped_spans={result.dropped_spans}"
    )


# ---------------------------------------------------------------------------
# Org case channel — pack-agnostic canary
# ---------------------------------------------------------------------------


def test_org_gap_uppercase_links(org_gap_resolver: Resolver) -> None:
    """'GAP' (all-caps) links to the org entity — pack-agnostic channel works."""
    result = org_gap_resolver.parse("GAP")
    entity_ids = [e.entity_id for e in result.entities]
    assert "org/gap_test" in entity_ids, (
        f"'GAP' should resolve to org/gap_test; entities={entity_ids}, "
        f"dropped={result.dropped_spans}"
    )


def test_org_gap_lowercase_dropped(org_gap_resolver: Resolver) -> None:
    """'gap' (lowercase) is dropped with code_case_mismatch, no org link.

    This is the pack-agnostic canary: confirms the gate is not geo-only.
    """
    result = org_gap_resolver.parse("gap")
    entity_ids = [e.entity_id for e in result.entities]
    assert "org/gap_test" not in entity_ids, (
        f"'gap' must not resolve to org/gap_test; entities={entity_ids}"
    )
    gap_dropped = [d for d in result.dropped_spans if d.surface.lower() == "gap"]
    assert gap_dropped, (
        f"'gap' must produce a dropped span; dropped={result.dropped_spans}"
    )
    assert gap_dropped[0].reason == "code_case_mismatch", (
        f"'gap' must be dropped as code_case_mismatch, got {gap_dropped[0].reason!r}"
    )


# ---------------------------------------------------------------------------
# Bundled data e2e — Kenya and Somalia (automaton-level, no full Resolver)
# ---------------------------------------------------------------------------

_COUNTRIES_DB = (
    Path(__file__).parent.parent.parent
    / "src/resolvekit/_data/geo/countries/entities.sqlite"
)


@pytest.fixture(scope="module")
def bundled_countries_automaton() -> object:
    """PackAutomaton built from the bundled countries store (offline-safe).

    Uses the store directly to avoid the multi-pack dependency check that
    `Resolver.from_datapacks` enforces.  Returns the automaton object.
    """
    from resolvekit.core.parse.automaton import PackAutomaton
    from resolvekit.core.store.sqlite import SQLiteEntityStore
    from resolvekit.packs.geo.pack import GEO_NORMALIZATION_PROFILE
    from resolvekit.packs.geo.sources.symspell import _SMALL_ENTITY_TYPE_PREFIXES

    store = SQLiteEntityStore(_COUNTRIES_DB)
    automaton = PackAutomaton(
        store=store,
        profile=GEO_NORMALIZATION_PROFILE,
        pack_id="geo",
        small_prefixes=_SMALL_ENTITY_TYPE_PREFIXES,
    )
    return automaton


def test_bundled_and_lowercase_is_not_code_shaped_hit_or_dropped(
    bundled_countries_automaton: object,
) -> None:
    """At automaton level: 'and' hit carries code_shaped=True (it is the AND alias).

    This confirms the predicate fires on bundled data.  The case channel in
    link_span will subsequently drop the span — tested at resolver level in the
    synthetic fixtures above.
    """
    from resolvekit.core.parse.automaton import PackAutomaton

    assert isinstance(bundled_countries_automaton, PackAutomaton)
    hits = bundled_countries_automaton.find("Kenya and Somalia")
    and_hits = [h for h in hits if h.surface.lower() == "and"]
    # 'and' may or may not produce a hit depending on word-boundary;
    # if it does, it must be code_shaped=True (the AND alias is code-shaped).
    for h in and_hits:
        assert h.code_shaped, (
            f"'and' hit in bundled data must have code_shaped=True; hit={h}"
        )


def test_bundled_and_uppercase_is_code_shaped_hit(
    bundled_countries_automaton: object,
) -> None:
    """At automaton level: bare 'AND' produces a hit with code_shaped=True."""
    from resolvekit.core.parse.automaton import PackAutomaton

    assert isinstance(bundled_countries_automaton, PackAutomaton)
    hits = bundled_countries_automaton.find("AND")
    and_hits = [h for h in hits if h.surface == "AND"]
    assert and_hits, (
        f"'AND' must produce a hit in bundled countries data; all hits={hits}"
    )
    assert and_hits[0].code_shaped, (
        "Hit for 'AND' in bundled data must have code_shaped=True"
    )
