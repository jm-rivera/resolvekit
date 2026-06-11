"""Regression test: OECD→geo FTS rebuild ordering in stage_enrich.

This file pins the per-domain→OECD→deferred-rebuild ordering. The primary
test drives the real ``stage_enrich(context)`` through a ``SimpleNamespace``
stub so it exercises ``stage_enrich``'s ``dbs_needing_fts`` accumulation —
the actual bug site. A seam-level test against ``_enrich_database`` /
``enrich_oecd_dac`` / ``rebuild_fts`` directly would not catch a reordering
regression there.

The bug: under the old eager-rebuild-in-per-domain-loop logic, FTS was
rebuilt after per-domain enrichers ran, and any names the OECD pass then
added to the DB were never re-indexed. ``MATCH 'turkiye'`` (the OECD
recipient alias) would return empty. The current deferred-rebuild code
indexes both passes before rebuilding FTS.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from resolvekit.builder.formal_names import COUNTRY_ENTITY_TYPE
from resolvekit.builder.pipeline.contribution import GraphContribution
from resolvekit.builder.pipeline.enrich import stage_enrich
from resolvekit.core.util.normalization import TextNormalizer

# ---------------------------------------------------------------------------
# Schema — matches the shape used by test_oecd_dac.py and the real geo DB
# ---------------------------------------------------------------------------

_SCHEMA = """
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
CREATE VIRTUAL TABLE IF NOT EXISTS names_fts USING fts5(
    entity_id,
    value_norm,
    content='names',
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 1'
);
"""

# Zero-deltas shape reused in no-op fake OECD contributions.
_ZERO_DOMAIN_DELTA: dict[str, int] = {
    "entities": 0,
    "names": 0,
    "codes": 0,
    "relations": 0,
}


def _build_geo_db(tmp_path: Path) -> Path:
    """Seed a minimal geo SQLite with one country entity and its iso3 code."""
    normalizer = TextNormalizer()
    db = tmp_path / "geo.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(_SCHEMA)
    canonical = "Türkiye"
    conn.execute(
        "INSERT OR IGNORE INTO entities VALUES (?, ?, ?, ?, NULL, NULL, '{}')",
        ("country/TUR", "geo.country", canonical, normalizer.normalize(canonical)),
    )
    # iso3 code row — _iso3_to_entity_id in oecd_dac.py looks up value='TUR'
    # (uppercase) so this seed lets the OECD pass resolve to the existing entity
    # rather than creating a fresh geo.region/oecd:* one.
    conn.execute(
        "INSERT OR IGNORE INTO codes VALUES (?, 'iso3', ?, ?)",
        ("country/TUR", "TUR", "tur"),
    )
    conn.commit()
    conn.close()
    return db


def _query_fts(db: Path, match_token: str) -> list[tuple[str]]:
    """Return all (entity_id,) rows from names_fts matching the token."""
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT entity_id FROM names_fts WHERE names_fts MATCH ?",
            (match_token,),
        ).fetchall()
    finally:
        conn.close()


def _geo_only_context() -> SimpleNamespace:
    """Stub BuildContext exposing only what stage_enrich reads: a single geo
    recipe and a no-op state.set_meta."""
    return SimpleNamespace(
        plan=SimpleNamespace(recipes=[SimpleNamespace(domain="geo")]),
        state=SimpleNamespace(set_meta=lambda *a, **k: None),
    )


def _patch_enrich_for_geo(monkeypatch: pytest.MonkeyPatch, geo_db: Path) -> None:
    """Route stage_enrich's geo enrichment at the seeded DB with a single
    hermetic per-domain adder. The caller patches ``enrich_oecd_dac`` itself —
    that patch is the meaningful per-test variation."""
    import resolvekit.builder.pipeline.enrich as enrich_mod

    monkeypatch.setattr(
        enrich_mod,
        "canonical_staging_db",
        lambda ctx, domain, *, phase: geo_db if domain == "geo" else None,
    )
    monkeypatch.setattr(
        enrich_mod,
        "_ENRICHERS",
        {COUNTRY_ENTITY_TYPE: [_fake_per_domain_adder]},
    )


# ---------------------------------------------------------------------------
# Fake enrichers — hermetic, no pycountry/CLDR/groups/OECD-YAML imports
# ---------------------------------------------------------------------------

_normalizer = TextNormalizer()

# Per-domain fake: returns "Republic of Türkiye" as a name contribution.
# Must NOT write to the DB — enrichers are pure; the pipeline calls
# apply_contribution. Must NOT call rebuild_fts (FTS rebuild is the stage's
# responsibility, deferred after all passes).
_PER_DOMAIN_VALUE = "Republic of Türkiye"
_PER_DOMAIN_VALUE_NORM = _normalizer.normalize(_PER_DOMAIN_VALUE)


def _fake_per_domain_adder(db_path: Path) -> GraphContribution:
    return GraphContribution(
        names=[
            {
                "entity_id": "country/TUR",
                "name_kind": "formal",
                "value": _PER_DOMAIN_VALUE,
                "value_norm": _PER_DOMAIN_VALUE_NORM,
                "lang": "en",
                "script": "",
                "is_preferred": 0,
            }
        ]
    )


# OECD fake: returns "Türkiye" recipient alias as a geo contribution.
# stage_enrich gates the OECD FTS rebuild on deltas["names"] != 0 — returning
# a contribution with one name row triggers it.
_OECD_VALUE = "Türkiye"
_OECD_VALUE_NORM = _normalizer.normalize(_OECD_VALUE)


def _fake_oecd(
    *, geo_db: Path | None, org_db: Path | None
) -> dict[str, GraphContribution]:
    """Return a geo contribution with one name row; write nothing."""
    return {
        "geo": GraphContribution(
            names=[
                {
                    "entity_id": "country/TUR",
                    "name_kind": "alias",
                    "value": _OECD_VALUE,
                    "value_norm": _OECD_VALUE_NORM,
                    "lang": "en",
                    "script": "",
                    "is_preferred": 0,
                }
            ]
        ),
        "org": GraphContribution(),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_oecd_name_indexed_after_stage_enrich(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OECD-injected geo name is queryable in names_fts after stage_enrich.

    This is the primary regression guard for the deferred-FTS-rebuild fix.
    Under the old eager-rebuild logic, stage_enrich would rebuild FTS after the
    per-domain pass, then the OECD pass would add more names — but FTS would
    never be rebuilt again, so 'MATCH turkiye' returned empty.
    """
    geo_db = _build_geo_db(tmp_path)
    context = _geo_only_context()
    _patch_enrich_for_geo(monkeypatch, geo_db)
    monkeypatch.setattr(
        "resolvekit.builder.pipeline.enrich.build_oecd_contributions", _fake_oecd
    )

    stage_enrich(context)

    # PRIMARY assertion (regression guard): both the per-domain name and the
    # OECD recipient alias are indexed after the deferred rebuild.
    #
    # The FTS tokenizer uses 'unicode61 remove_diacritics 1', so value_norm
    # 'türkiye' and 'republic of türkiye' both contain the token 'turkiye'.
    # Under the old eager-rebuild ordering, FTS was rebuilt after the
    # per-domain pass — the OECD pass then wrote 'türkiye' to names but the
    # index was never updated, so 'MATCH turkiye' returned only 1 row (the
    # per-domain one). The deferred rebuild indexes both passes, yielding 2
    # rows. The row count difference signals a regression.
    oecd_hits = _query_fts(geo_db, _OECD_VALUE_NORM)
    assert len(oecd_hits) == 2, (
        f"Expected 2 rows in names_fts matching '{_OECD_VALUE_NORM}' (per-domain + OECD); "
        f"got {len(oecd_hits)}: {oecd_hits!r}. "
        f"If len==1, the OECD name was not indexed — classic deferred-rebuild regression."
    )
    assert all(row == ("country/TUR",) for row in oecd_hits), (
        f"Unexpected entity_id in names_fts MATCH hits: {oecd_hits!r}"
    )

    # Per-domain name must be independently queryable via a phrase query
    # (multi-word; phrase form avoids FTS5 parsing as AND of three tokens).
    per_domain_phrase = f'"{_PER_DOMAIN_VALUE_NORM}"'
    domain_hits = _query_fts(geo_db, per_domain_phrase)
    assert domain_hits == [("country/TUR",)], (
        f"Per-domain name '{_PER_DOMAIN_VALUE_NORM}' not found in names_fts; "
        f"got: {domain_hits!r}"
    )


@pytest.mark.unit
def test_per_domain_name_indexed_without_oecd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per-domain enricher name is queryable in names_fts without the OECD pass.

    Isolates failures: if test_oecd_name_indexed_after_stage_enrich fails but
    this test passes, the fault is in the OECD→FTS ordering, not per-domain
    indexing itself.
    """
    geo_db = _build_geo_db(tmp_path)
    context = _geo_only_context()
    _patch_enrich_for_geo(monkeypatch, geo_db)
    # No-op OECD pass — empty contributions, no DB writes, no FTS rebuild triggered
    # by OECD path (stage_enrich still rebuilds via dbs_needing_fts from per-domain).
    monkeypatch.setattr(
        "resolvekit.builder.pipeline.enrich.build_oecd_contributions",
        lambda *, geo_db, org_db: {
            "geo": GraphContribution(),
            "org": GraphContribution(),
        },
    )

    stage_enrich(context)

    per_domain_phrase = f'"{_PER_DOMAIN_VALUE_NORM}"'
    hits = _query_fts(geo_db, per_domain_phrase)
    assert hits == [("country/TUR",)], (
        f"Per-domain name not indexed without OECD pass; got: {hits!r}"
    )
