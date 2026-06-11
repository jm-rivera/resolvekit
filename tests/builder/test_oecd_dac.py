"""Unit tests for the OECD DAC enricher (src/resolvekit/builder/oecd_dac.py)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
import yaml

# ---------------------------------------------------------------------------
# Schema and DB helpers
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
CREATE VIRTUAL TABLE IF NOT EXISTS names_fts USING fts5(entity_id, value_norm);
"""

_SEED_COUNTRIES = [
    ("country/USA", "United States", "USA"),
    ("country/FRA", "France", "FRA"),
    ("country/DEU", "Germany", "DEU"),
    ("country/CZE", "Czech Republic", "CZE"),
    ("country/IND", "India", "IND"),
    ("country/AUT", "Austria", "AUT"),
    ("country/TUR", "Türkiye", "TUR"),
]


def _build_geo_db(tmp_path: Path) -> Path:
    db = tmp_path / "geo.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(_SCHEMA)
    for eid, name, iso3 in _SEED_COUNTRIES:
        conn.execute(
            "INSERT OR IGNORE INTO entities VALUES (?, 'geo.country', ?, ?, NULL, NULL, '{}')",
            (eid, name, name.lower()),
        )
        conn.execute(
            "INSERT OR IGNORE INTO codes VALUES (?, 'iso3', ?, ?)",
            (eid, iso3, iso3.lower()),
        )
    conn.commit()
    conn.close()
    return db


def _build_org_db(tmp_path: Path) -> Path:
    db = tmp_path / "org.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()
    return db


def _minimal_oecd_yaml(
    tmp_path: Path,
    *,
    recipients: list[dict[str, Any]] | None = None,
    providers: list[dict[str, Any]] | None = None,
    channels: list[dict[str, Any]] | None = None,
    agencies: list[dict[str, Any]] | None = None,
) -> Path:
    data = {
        "version": 1,
        "generated_from": {
            "oecd_query_date": "2026-05-23",
            "source_url": "https://development-finance-codelists.oecd.org/CodesList.aspx",
            "aspx_codelist_ids": {
                "recipients": "13",
                "providers": "5",
                "channels": "3",
                "agencies": "16",
            },
        },
        "recipients": recipients or [],
        "providers": providers or [],
        "channels": channels or [],
        "agencies": agencies or [],
    }
    path = tmp_path / "oecd_dac.yaml"
    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    return path


def _minimal_crosswalk_yaml(tmp_path: Path, **sections: dict[str, Any]) -> Path:
    data = dict(
        {
            "version": 1,
            "providers": {},
            "channels": {},
            "agencies": {},
            "recipients": {},
        },
        **sections,
    )
    path = tmp_path / "oecd_crosswalk.yaml"
    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    return path


def _run_enricher(
    geo_db: Path | None,
    org_db: Path | None,
    yaml_path: Path,
    crosswalk_path: Path,
) -> dict[str, dict[str, int]]:
    import resolvekit.builder.oecd_dac as mod
    from resolvekit.builder.pipeline.contribution import apply_contribution
    from resolvekit.builder.sqlite.context import connect_sqlite, transaction

    orig_dac = mod._OECD_DAC_YAML
    orig_cw = mod._OECD_CROSSWALK_YAML
    mod._OECD_DAC_YAML = yaml_path
    mod._OECD_CROSSWALK_YAML = crosswalk_path
    try:
        contribs = mod.build_oecd_contributions(geo_db=geo_db, org_db=org_db)
        out: dict[str, dict[str, int]] = {}
        for key, db in (("geo", geo_db), ("org", org_db)):
            if db is None:
                out[key] = {"entities": 0, "names": 0, "codes": 0, "relations": 0}
                continue
            with connect_sqlite(db, busy_timeout_ms=30000) as conn, transaction(conn):
                out[key] = apply_contribution(conn=conn, contribution=contribs[key])
        return out
    finally:
        mod._OECD_DAC_YAML = orig_dac
        mod._OECD_CROSSWALK_YAML = orig_cw


def _query_one(db: Path, sql: str, params: tuple = ()) -> tuple | None:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_recipient_country_attaches_code(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)
    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        recipients=[
            {
                "code": "55",
                "name_en": "Türkiye",
                "name_fr": "Türkiye",
                "iso3": "TUR",
                "type": "Country",
            }
        ],
    )
    cw_path = _minimal_crosswalk_yaml(tmp_path)
    _run_enricher(geo_db, org_db, yaml_path, cw_path)

    row = _query_one(
        geo_db,
        "SELECT entity_id, system, value FROM codes WHERE system='oecd:recipient' AND entity_id='country/TUR'",
    )
    assert row is not None
    assert row[2] == "55"


@pytest.mark.unit
def test_recipient_country_attaches_french_alias(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)
    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        recipients=[
            {
                "code": "55",
                "name_en": "Türkiye",
                "name_fr": "Türkiye fr",
                "iso3": "TUR",
                "type": "Country",
            }
        ],
    )
    cw_path = _minimal_crosswalk_yaml(tmp_path)
    _run_enricher(geo_db, org_db, yaml_path, cw_path)

    row = _query_one(
        geo_db,
        "SELECT value, lang FROM names WHERE entity_id='country/TUR' AND lang='fr'",
    )
    assert row is not None
    assert row[1] == "fr"


@pytest.mark.unit
def test_recipient_region_creates_entity(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)
    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        recipients=[
            {
                "code": "289",
                "name_en": "Sub-Sahara",
                "name_fr": None,
                "iso3": None,
                "type": "Region",
            }
        ],
    )
    cw_path = _minimal_crosswalk_yaml(tmp_path)
    _run_enricher(geo_db, org_db, yaml_path, cw_path)

    row = _query_one(
        geo_db,
        "SELECT entity_id, entity_type, canonical_name FROM entities WHERE entity_id='geo.region/oecd:289'",
    )
    code_row = _query_one(
        geo_db,
        "SELECT value FROM codes WHERE entity_id='geo.region/oecd:289' AND system='oecd:recipient'",
    )

    assert row is not None
    assert row[1] == "geo.region"
    assert row[2] == "Sub-Sahara"
    assert code_row is not None
    assert code_row[0] == "289"


@pytest.mark.unit
def test_provider_country_attaches_code(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)
    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        providers=[
            {
                "code": "1",
                "name_en": "Austria",
                "name_fr": "Autriche",
                "iso3": "AUT",
                "type": "DAC member",
            }
        ],
    )
    cw_path = _minimal_crosswalk_yaml(tmp_path)
    _run_enricher(geo_db, org_db, yaml_path, cw_path)

    row = _query_one(
        geo_db,
        "SELECT value FROM codes WHERE entity_id='country/AUT' AND system='oecd:provider'",
    )
    assert row is not None
    assert row[0] == "1"


@pytest.mark.unit
def test_provider_multilateral_creates_entity(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)
    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        providers=[
            {
                "code": "901",
                "name_en": "World Bank Group",
                "name_fr": None,
                "iso3": None,
                "type": "Multilateral",
            }
        ],
    )
    cw_path = _minimal_crosswalk_yaml(tmp_path)
    _run_enricher(geo_db, org_db, yaml_path, cw_path)

    row = _query_one(
        org_db,
        "SELECT entity_id, entity_type FROM entities WHERE entity_id='org/oecd:provider:901'",
    )
    assert row is not None
    assert row[1] == "org.igo"


@pytest.mark.unit
def test_provider_multilateral_uses_crosswalk(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)

    # Pre-seed the org DB with an existing entity
    conn = sqlite3.connect(org_db)
    conn.execute(
        "INSERT OR IGNORE INTO entities VALUES ('org/dc/WorldBank', 'org.igo', 'World Bank', 'world bank', NULL, NULL, '{}')"
    )
    conn.commit()
    conn.close()

    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        providers=[
            {
                "code": "901",
                "name_en": "World Bank Group",
                "name_fr": None,
                "iso3": None,
                "type": "Multilateral",
            }
        ],
    )
    cw_path = _minimal_crosswalk_yaml(tmp_path, providers={"901": "org/dc/WorldBank"})
    _run_enricher(geo_db, org_db, yaml_path, cw_path)

    new_entity = _query_one(
        org_db, "SELECT 1 FROM entities WHERE entity_id='org/oecd:provider:901'"
    )
    code_row = _query_one(
        org_db,
        "SELECT entity_id FROM codes WHERE system='oecd:provider' AND value='901'",
    )

    assert new_entity is None, (
        "Should not create a new entity when crosswalk maps to existing"
    )
    assert code_row is not None
    assert code_row[0] == "org/dc/WorldBank"


@pytest.mark.unit
def test_channel_creates_entity_and_parent_relation(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)
    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        channels=[
            {
                "code": "10000",
                "name_en": "Public Sector",
                "name_fr": None,
                "category": "10000",
                "acronym": None,
            },
            {
                "code": "11000",
                "name_en": "Donor Government",
                "name_fr": None,
                "category": "10000",
                "acronym": None,
            },
        ],
    )
    cw_path = _minimal_crosswalk_yaml(tmp_path)
    _run_enricher(geo_db, org_db, yaml_path, cw_path)

    e1 = _query_one(
        org_db, "SELECT 1 FROM entities WHERE entity_id='org/oecd:channel:10000'"
    )
    e2 = _query_one(
        org_db, "SELECT 1 FROM entities WHERE entity_id='org/oecd:channel:11000'"
    )
    relation = _query_one(
        org_db,
        "SELECT 1 FROM relations WHERE entity_id='org/oecd:channel:11000' AND relation_type='part_of' AND target_id='org/oecd:channel:10000'",
    )

    assert e1 is not None
    assert e2 is not None
    assert relation is not None


@pytest.mark.unit
def test_channel_acronym_added_as_alias(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)
    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        channels=[
            {
                "code": "10000",
                "name_en": "Public Sector",
                "name_fr": None,
                "category": "10000",
                "acronym": "PS",
            },
        ],
    )
    cw_path = _minimal_crosswalk_yaml(tmp_path)
    _run_enricher(geo_db, org_db, yaml_path, cw_path)

    row = _query_one(
        org_db,
        "SELECT value FROM names WHERE entity_id='org/oecd:channel:10000' AND value='PS'",
    )
    assert row is not None


@pytest.mark.unit
def test_agency_creates_entity_with_donor_relation(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)
    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        providers=[
            {
                "code": "1",
                "name_en": "Austria",
                "name_fr": "Autriche",
                "iso3": "AUT",
                "type": "DAC member",
            }
        ],
        agencies=[
            {
                "code": "1",
                "name_en": "Federal Ministry",
                "name_fr": None,
                "donor_code": "1",
                "acronym": "BMF",
            }
        ],
    )
    cw_path = _minimal_crosswalk_yaml(tmp_path)
    _run_enricher(geo_db, org_db, yaml_path, cw_path)

    entity = _query_one(
        org_db, "SELECT entity_id FROM entities WHERE entity_id='org/oecd:agency:AUT:1'"
    )
    relation = _query_one(
        org_db,
        "SELECT 1 FROM relations WHERE entity_id='org/oecd:agency:AUT:1' AND relation_type='subsidiary_of' AND target_id='country/AUT'",
    )

    assert entity is not None
    assert relation is not None


@pytest.mark.unit
def test_agency_code_value_is_composite(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)
    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        providers=[
            {
                "code": "1",
                "name_en": "Austria",
                "name_fr": None,
                "iso3": "AUT",
                "type": "DAC member",
            }
        ],
        agencies=[
            {
                "code": "1",
                "name_en": "BMF",
                "name_fr": None,
                "donor_code": "1",
                "acronym": None,
            }
        ],
    )
    cw_path = _minimal_crosswalk_yaml(tmp_path)
    _run_enricher(geo_db, org_db, yaml_path, cw_path)

    row = _query_one(
        org_db,
        "SELECT value FROM codes WHERE entity_id='org/oecd:agency:AUT:1' AND system='oecd:agency'",
    )
    assert row is not None
    assert row[0] == "AUT:1"


@pytest.mark.unit
def test_country_as_both_recipient_and_provider(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)
    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        recipients=[
            {
                "code": "54",
                "name_en": "Czech Republic",
                "name_fr": None,
                "iso3": "CZE",
                "type": "Country",
            }
        ],
        providers=[
            {
                "code": "311",
                "name_en": "Czech Republic",
                "name_fr": None,
                "iso3": "CZE",
                "type": "DAC member",
            }
        ],
    )
    cw_path = _minimal_crosswalk_yaml(tmp_path)
    _run_enricher(geo_db, org_db, yaml_path, cw_path)

    recipient_code = _query_one(
        geo_db,
        "SELECT value FROM codes WHERE entity_id='country/CZE' AND system='oecd:recipient'",
    )
    provider_code = _query_one(
        geo_db,
        "SELECT value FROM codes WHERE entity_id='country/CZE' AND system='oecd:provider'",
    )

    assert recipient_code is not None
    assert provider_code is not None


@pytest.mark.unit
def test_crosswalk_missing_entity_logs_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A non-null crosswalk target absent from all DBs should log a warning, not raise.

    Raising ValueError was too strict: partial or filtered builds don't contain
    the full entity corpus, so a missing target just means we skip attaching the
    OECD code for this run rather than failing the entire build.
    """
    import logging

    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)
    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        providers=[
            {
                "code": "901",
                "name_en": "World Bank",
                "name_fr": None,
                "iso3": None,
                "type": "Multilateral",
            }
        ],
    )
    cw_path = _minimal_crosswalk_yaml(tmp_path, providers={"901": "org/does-not-exist"})

    with caplog.at_level(logging.WARNING, logger="resolvekit.builder.oecd_dac"):
        _run_enricher(geo_db, org_db, yaml_path, cw_path)  # must not raise

    assert any("901" in msg for msg in caplog.messages), (
        "Expected a warning mentioning the missing crosswalk entry '901'"
    )


@pytest.mark.unit
def test_idempotent_rerun(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)
    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        recipients=[
            {
                "code": "55",
                "name_en": "Türkiye",
                "name_fr": None,
                "iso3": "TUR",
                "type": "Country",
            }
        ],
        providers=[
            {
                "code": "1",
                "name_en": "Austria",
                "name_fr": None,
                "iso3": "AUT",
                "type": "DAC member",
            },
            {
                "code": "901",
                "name_en": "World Bank",
                "name_fr": None,
                "iso3": None,
                "type": "Multilateral",
            },
        ],
        channels=[
            {
                "code": "10000",
                "name_en": "Public Sector",
                "name_fr": None,
                "category": "10000",
                "acronym": None,
            },
        ],
        agencies=[
            {
                "code": "1",
                "name_en": "Austrian Ministry",
                "name_fr": None,
                "donor_code": "1",
                "acronym": "BMF",
            },
        ],
    )
    cw_path = _minimal_crosswalk_yaml(tmp_path)

    _run_enricher(geo_db, org_db, yaml_path, cw_path)

    def _counts(db: Path) -> dict[str, int]:
        conn = sqlite3.connect(db)
        counts = {
            "entities": conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
            "names": conn.execute("SELECT COUNT(*) FROM names").fetchone()[0],
            "codes": conn.execute("SELECT COUNT(*) FROM codes").fetchone()[0],
            "relations": conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0],
        }
        conn.close()
        return counts

    geo_counts_1 = _counts(geo_db)
    org_counts_1 = _counts(org_db)

    second_deltas = _run_enricher(geo_db, org_db, yaml_path, cw_path)

    geo_counts_2 = _counts(geo_db)
    org_counts_2 = _counts(org_db)

    assert geo_counts_1 == geo_counts_2
    assert org_counts_1 == org_counts_2
    assert second_deltas["geo"] == {
        "entities": 0,
        "names": 0,
        "codes": 0,
        "relations": 0,
    }
    assert second_deltas["org"] == {
        "entities": 0,
        "names": 0,
        "codes": 0,
        "relations": 0,
    }


@pytest.mark.unit
def test_missing_yaml_raises_file_not_found(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)
    nonexistent = tmp_path / "does_not_exist.yaml"
    cw_path = _minimal_crosswalk_yaml(tmp_path)

    with pytest.raises(FileNotFoundError):
        _run_enricher(geo_db, org_db, nonexistent, cw_path)


@pytest.mark.unit
def test_missing_yaml_raises_import_error_when_no_pyyaml(tmp_path: Path) -> None:
    import resolvekit.builder.oecd_dac as mod

    yaml_path = _minimal_oecd_yaml(tmp_path)
    cw_path = _minimal_crosswalk_yaml(tmp_path)
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)

    orig_yaml = mod._yaml
    mod._yaml = None  # type: ignore[assignment]
    try:
        with pytest.raises(ImportError, match="pip install"):
            _run_enricher(geo_db, org_db, yaml_path, cw_path)
    finally:
        mod._yaml = orig_yaml


@pytest.mark.unit
def test_geo_only_build_skips_org_codelists(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        recipients=[
            {
                "code": "55",
                "name_en": "Türkiye",
                "name_fr": None,
                "iso3": "TUR",
                "type": "Country",
            }
        ],
        providers=[
            {
                "code": "901",
                "name_en": "World Bank",
                "name_fr": None,
                "iso3": None,
                "type": "Multilateral",
            }
        ],
    )
    cw_path = _minimal_crosswalk_yaml(tmp_path)

    result = _run_enricher(geo_db, None, yaml_path, cw_path)

    assert result["org"] == {"entities": 0, "names": 0, "codes": 0, "relations": 0}
    assert result["geo"]["codes"] > 0

    org_entity = _query_one(
        geo_db, "SELECT 1 FROM entities WHERE entity_id='org/oecd:provider:901'"
    )
    assert org_entity is None, "org entities should not be created when org_db is None"


@pytest.mark.unit
def test_both_none_returns_zero_deltas(tmp_path: Path) -> None:
    yaml_path = _minimal_oecd_yaml(tmp_path)
    cw_path = _minimal_crosswalk_yaml(tmp_path)

    result = _run_enricher(None, None, yaml_path, cw_path)

    assert result == {
        "geo": {"entities": 0, "names": 0, "codes": 0, "relations": 0},
        "org": {"entities": 0, "names": 0, "codes": 0, "relations": 0},
    }


@pytest.mark.unit
def test_crosswalk_null_value_is_skipped(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)
    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        providers=[
            {
                "code": "901",
                "name_en": "World Bank",
                "name_fr": None,
                "iso3": None,
                "type": "Multilateral",
            }
        ],
    )
    # crosswalk has null for 901 — should be treated as no mapping
    cw_path = _minimal_crosswalk_yaml(tmp_path, providers={"901": None})
    _run_enricher(geo_db, org_db, yaml_path, cw_path)

    entity = _query_one(
        org_db, "SELECT 1 FROM entities WHERE entity_id='org/oecd:provider:901'"
    )
    assert entity is not None, (
        "null crosswalk should cause new entity creation, not skip"
    )


@pytest.mark.unit
def test_crosswalk_skips_org_entries_when_org_db_none(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    yaml_path = _minimal_oecd_yaml(tmp_path)
    # crosswalk has an org-prefixed target but org_db=None — should not raise
    cw_path = _minimal_crosswalk_yaml(tmp_path, providers={"901": "org/some-entity"})

    _run_enricher(geo_db, None, yaml_path, cw_path)  # must not raise


@pytest.mark.unit
def test_agency_uses_crosswalk(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)

    # Pre-seed the org DB with an existing entity
    conn = sqlite3.connect(org_db)
    conn.execute(
        "INSERT OR IGNORE INTO entities VALUES ('org/dc/BMF', 'org.government_organization', 'BMF', 'bmf', NULL, NULL, '{}')"
    )
    conn.commit()
    conn.close()

    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        providers=[
            {
                "code": "1",
                "name_en": "Austria",
                "name_fr": "Autriche",
                "iso3": "AUT",
                "type": "DAC member",
            }
        ],
        agencies=[
            {
                "code": "1",
                "name_en": "Federal Ministry",
                "name_fr": None,
                "donor_code": "1",
                "acronym": "BMF",
            }
        ],
    )
    cw_path = _minimal_crosswalk_yaml(tmp_path, agencies={"AUT:1": "org/dc/BMF"})
    _run_enricher(geo_db, org_db, yaml_path, cw_path)

    # (a) no org/oecd:agency:AUT:1 entity created
    new_entity = _query_one(
        org_db, "SELECT 1 FROM entities WHERE entity_id='org/oecd:agency:AUT:1'"
    )
    # (b) OECD code attached to the mapped entity
    code_row = _query_one(
        org_db,
        "SELECT entity_id FROM codes WHERE system='oecd:agency' AND value='AUT:1'",
    )
    # (c) agency_of relation pointing to country/AUT
    relation = _query_one(
        org_db,
        "SELECT 1 FROM relations WHERE entity_id='org/dc/BMF' AND relation_type='subsidiary_of' AND target_id='country/AUT'",
    )

    assert new_entity is None, (
        "Should not create a new entity when crosswalk maps to existing"
    )
    assert code_row is not None
    assert code_row[0] == "org/dc/BMF"
    assert relation is not None


@pytest.mark.unit
def test_agency_crosswalk_key_case_normalized(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)

    # Pre-seed the org DB with an existing entity
    conn = sqlite3.connect(org_db)
    conn.execute(
        "INSERT OR IGNORE INTO entities VALUES ('org/dc/BMF', 'org.government_organization', 'BMF', 'bmf', NULL, NULL, '{}')"
    )
    conn.commit()
    conn.close()

    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        providers=[
            {
                "code": "1",
                "name_en": "Austria",
                "name_fr": "Autriche",
                "iso3": "AUT",
                "type": "DAC member",
            }
        ],
        agencies=[
            {
                "code": "1",
                "name_en": "Federal Ministry",
                "name_fr": None,
                "donor_code": "1",
                "acronym": "BMF",
            }
        ],
    )
    # crosswalk uses lowercase iso3 — should still match
    cw_path = _minimal_crosswalk_yaml(tmp_path, agencies={"aut:1": "org/dc/BMF"})
    _run_enricher(geo_db, org_db, yaml_path, cw_path)

    # No new entity created — crosswalk hit despite lowercase key
    new_entity = _query_one(
        org_db, "SELECT 1 FROM entities WHERE entity_id='org/oecd:agency:AUT:1'"
    )
    code_row = _query_one(
        org_db,
        "SELECT entity_id FROM codes WHERE system='oecd:agency' AND value='AUT:1'",
    )

    assert new_entity is None, (
        "Lowercase crosswalk key should resolve to existing entity, not create a new one"
    )
    assert code_row is not None
    assert code_row[0] == "org/dc/BMF"


@pytest.mark.unit
def test_recipient_unknown_iso3_creates_region(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)
    # XKX (Kosovo) is not in our seed countries
    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        recipients=[
            {
                "code": "57",
                "name_en": "Kosovo",
                "name_fr": "Kosovo",
                "iso3": "XKX",
                "type": "Country",
            }
        ],
    )
    cw_path = _minimal_crosswalk_yaml(tmp_path)
    _run_enricher(geo_db, org_db, yaml_path, cw_path)

    entity = _query_one(
        geo_db, "SELECT entity_type FROM entities WHERE entity_id='geo.region/oecd:57'"
    )
    assert entity is not None
    assert entity[0] == "geo.region"


def _seed_geo_entity(
    db: Path, entity_id: str, name: str, entity_type: str = "org.igo"
) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT OR IGNORE INTO entities VALUES (?, ?, ?, ?, NULL, NULL, '{}')",
        (entity_id, entity_type, name, name.lower()),
    )
    conn.commit()
    conn.close()


@pytest.mark.unit
def test_provider_multilateral_crosswalk_to_geo_entity(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)
    _seed_geo_entity(geo_db, "undata-geo/G00601300", "UNICEF")

    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        providers=[
            {
                "code": "963",
                "name_en": "UNICEF",
                "name_fr": "UNICEF fr",
                "iso3": None,
                "type": "Multilateral",
            }
        ],
    )
    cw_path = _minimal_crosswalk_yaml(
        tmp_path, providers={"963": "undata-geo/G00601300"}
    )
    _run_enricher(geo_db, org_db, yaml_path, cw_path)

    # (a) no org entity created for this code
    org_entity = _query_one(
        org_db, "SELECT 1 FROM entities WHERE entity_id='org/oecd:provider:963'"
    )
    assert org_entity is None

    # (b) code attached to geo entity
    code_row = _query_one(
        geo_db,
        "SELECT entity_id FROM codes WHERE system='oecd:provider' AND value='963'",
    )
    assert code_row is not None
    assert code_row[0] == "undata-geo/G00601300"

    # (c) French alias on the geo entity
    fr_name = _query_one(
        geo_db,
        "SELECT value FROM names WHERE entity_id='undata-geo/G00601300' AND lang='fr'",
    )
    assert fr_name is not None
    assert fr_name[0] == "UNICEF fr"


@pytest.mark.unit
def test_provider_multilateral_crosswalk_to_geo_with_no_org_db(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    _seed_geo_entity(geo_db, "undata-geo/G00601300", "UNICEF")

    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        providers=[
            {
                "code": "963",
                "name_en": "UNICEF",
                "name_fr": None,
                "iso3": None,
                "type": "Multilateral",
            }
        ],
    )
    cw_path = _minimal_crosswalk_yaml(
        tmp_path, providers={"963": "undata-geo/G00601300"}
    )

    # Must not raise even though org_db=None
    _run_enricher(geo_db, None, yaml_path, cw_path)

    code_row = _query_one(
        geo_db,
        "SELECT entity_id FROM codes WHERE system='oecd:provider' AND value='963'",
    )
    assert code_row is not None
    assert code_row[0] == "undata-geo/G00601300"


@pytest.mark.unit
def test_channel_crosswalk_to_geo_entity(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)
    _seed_geo_entity(geo_db, "undata-geo/G00601300", "UNICEF")

    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        channels=[
            {
                "code": "41122",
                "name_en": "UNICEF",
                "name_fr": "UNICEF fr",
                "category": "41122",
                "acronym": None,
            }
        ],
    )
    cw_path = _minimal_crosswalk_yaml(
        tmp_path, channels={"41122": "undata-geo/G00601300"}
    )
    _run_enricher(geo_db, org_db, yaml_path, cw_path)

    # No org entity created for this channel code
    org_entity = _query_one(
        org_db, "SELECT 1 FROM entities WHERE entity_id='org/oecd:channel:41122'"
    )
    assert org_entity is None

    # Code attached to geo entity
    code_row = _query_one(
        geo_db,
        "SELECT entity_id FROM codes WHERE system='oecd:channel' AND value='41122'",
    )
    assert code_row is not None
    assert code_row[0] == "undata-geo/G00601300"


@pytest.mark.unit
def test_crosswalk_validation_locates_target_db(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)
    _seed_geo_entity(geo_db, "undata-geo/G00601300", "UNICEF")

    # Pre-seed an org entity
    conn = sqlite3.connect(org_db)
    conn.execute(
        "INSERT OR IGNORE INTO entities VALUES ('org/dc/WorldBank', 'org.igo', 'World Bank', 'world bank', NULL, NULL, '{}')"
    )
    conn.commit()
    conn.close()

    import resolvekit.builder.oecd_dac as mod

    crosswalk = {
        "version": 1,
        "providers": {"963": "undata-geo/G00601300", "901": "org/dc/WorldBank"},
        "channels": {},
        "agencies": {},
        "recipients": {},
    }
    result = mod._validate_crosswalk(crosswalk, geo_db=geo_db, org_db=org_db)

    assert result["undata-geo/G00601300"] == "geo"
    assert result["org/dc/WorldBank"] == "org"


@pytest.mark.unit
def test_agency_multilateral_donor_no_crosswalk_creates_entity(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)
    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        providers=[
            {
                "code": "909",
                "name_en": "IDB",
                "name_fr": None,
                "iso3": None,
                "type": "Multilateral donor",
            }
        ],
        agencies=[
            {
                "code": "1",
                "name_en": "IDB Trust Fund",
                "name_fr": None,
                "donor_code": "909",
                "acronym": None,
            }
        ],
    )
    cw_path = _minimal_crosswalk_yaml(tmp_path)
    _run_enricher(geo_db, org_db, yaml_path, cw_path)

    entity = _query_one(
        org_db, "SELECT entity_id FROM entities WHERE entity_id='org/oecd:agency:909:1'"
    )
    code_row = _query_one(
        org_db,
        "SELECT entity_id, system, value FROM codes WHERE entity_id='org/oecd:agency:909:1' AND system='oecd:agency'",
    )
    relation = _query_one(
        org_db,
        "SELECT 1 FROM relations WHERE entity_id='org/oecd:agency:909:1' AND relation_type='subsidiary_of' AND target_id='org/oecd:provider:909'",
    )

    assert entity is not None
    assert code_row is not None
    assert code_row[2] == "909:1"
    assert relation is not None


@pytest.mark.unit
def test_agency_multilateral_donor_with_crosswalk_uses_geo_target(
    tmp_path: Path,
) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)
    _seed_geo_entity(geo_db, "undata-geo/G00700700", "IDB")

    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        providers=[
            {
                "code": "909",
                "name_en": "IDB",
                "name_fr": None,
                "iso3": None,
                "type": "Multilateral donor",
            }
        ],
        agencies=[
            {
                "code": "1",
                "name_en": "IDB Trust Fund",
                "name_fr": None,
                "donor_code": "909",
                "acronym": None,
            }
        ],
    )
    cw_path = _minimal_crosswalk_yaml(
        tmp_path, providers={"909": "undata-geo/G00700700"}
    )
    _run_enricher(geo_db, org_db, yaml_path, cw_path)

    entity = _query_one(
        org_db, "SELECT entity_id FROM entities WHERE entity_id='org/oecd:agency:909:1'"
    )
    relation = _query_one(
        org_db,
        "SELECT 1 FROM relations WHERE entity_id='org/oecd:agency:909:1' AND relation_type='subsidiary_of' AND target_id='undata-geo/G00700700'",
    )
    wrong_relation = _query_one(
        org_db,
        "SELECT 1 FROM relations WHERE entity_id='org/oecd:agency:909:1' AND relation_type='subsidiary_of' AND target_id='org/oecd:provider:909'",
    )
    # Provider went via crosswalk — no org/oecd:provider:909 entity created
    provider_entity = _query_one(
        org_db, "SELECT 1 FROM entities WHERE entity_id='org/oecd:provider:909'"
    )

    assert entity is not None
    assert relation is not None, (
        "subsidiary_of should point to the crosswalk-mapped geo entity"
    )
    assert wrong_relation is None, (
        "subsidiary_of must not point to the oecd provider entity when crosswalk maps it"
    )
    assert provider_entity is None


@pytest.mark.unit
def test_agency_with_truly_unknown_donor_code_logs_and_skips(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)
    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        providers=[
            {
                "code": "1",
                "name_en": "Austria",
                "name_fr": None,
                "iso3": "AUT",
                "type": "DAC member",
            }
        ],
        agencies=[
            {
                "code": "5",
                "name_en": "Ghost Agency",
                "name_fr": None,
                "donor_code": "99999",
                "acronym": None,
            }
        ],
    )
    cw_path = _minimal_crosswalk_yaml(tmp_path)
    _run_enricher(geo_db, org_db, yaml_path, cw_path)

    entity = _query_one(
        org_db, "SELECT 1 FROM entities WHERE entity_id LIKE 'org/oecd:agency:%:5'"
    )
    assert entity is None, "Agency with donor_code not in providers must not be created"


@pytest.mark.unit
def test_idempotent_rerun_with_multilateral_agencies(tmp_path: Path) -> None:
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)
    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        providers=[
            {
                "code": "1",
                "name_en": "Austria",
                "name_fr": None,
                "iso3": "AUT",
                "type": "DAC member",
            },
            {
                "code": "909",
                "name_en": "IDB",
                "name_fr": None,
                "iso3": None,
                "type": "Multilateral donor",
            },
        ],
        agencies=[
            {
                "code": "1",
                "name_en": "Austrian Ministry",
                "name_fr": None,
                "donor_code": "1",
                "acronym": "BMF",
            },
            {
                "code": "1",
                "name_en": "IDB Trust Fund",
                "name_fr": None,
                "donor_code": "909",
                "acronym": None,
            },
        ],
    )
    cw_path = _minimal_crosswalk_yaml(tmp_path)

    _run_enricher(geo_db, org_db, yaml_path, cw_path)

    def _counts(db: Path) -> dict[str, int]:
        conn = sqlite3.connect(db)
        counts = {
            "entities": conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
            "names": conn.execute("SELECT COUNT(*) FROM names").fetchone()[0],
            "codes": conn.execute("SELECT COUNT(*) FROM codes").fetchone()[0],
            "relations": conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0],
        }
        conn.close()
        return counts

    geo_counts_1 = _counts(geo_db)
    org_counts_1 = _counts(org_db)

    second_deltas = _run_enricher(geo_db, org_db, yaml_path, cw_path)

    geo_counts_2 = _counts(geo_db)
    org_counts_2 = _counts(org_db)

    assert geo_counts_1 == geo_counts_2
    assert org_counts_1 == org_counts_2
    assert second_deltas["geo"] == {
        "entities": 0,
        "names": 0,
        "codes": 0,
        "relations": 0,
    }
    assert second_deltas["org"] == {
        "entities": 0,
        "names": 0,
        "codes": 0,
        "relations": 0,
    }


# ---------------------------------------------------------------------------
# Parametrized DB-combination tests (exercises the unified write path for all
# three combos: geo+org, geo-only, org-only)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "use_geo,use_org",
    [
        (True, True),  # geo+org (both DBs present)
        (True, False),  # geo-only
        (False, True),  # org-only
    ],
    ids=["geo_and_org", "geo_only", "org_only"],
)
def test_unified_write_path_all_db_combos(
    tmp_path: Path, use_geo: bool, use_org: bool
) -> None:
    """The unified ExitStack write path must produce correct results for every
    combination of present/absent DBs.

    geo+org: recipients & providers in geo, multilateral orgs & channels & agencies in org.
    geo-only: same geo writes; org entities (multilaterals, channels, agencies) skipped.
    org-only: recipients/country-providers skipped (no geo); org entities created.
    """
    geo_db = _build_geo_db(tmp_path) if use_geo else None
    org_db = _build_org_db(tmp_path) if use_org else None

    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        recipients=[
            {
                "code": "55",
                "name_en": "Türkiye",
                "name_fr": None,
                "iso3": "TUR",
                "type": "Country",
            }
        ],
        providers=[
            {
                "code": "1",
                "name_en": "Austria",
                "name_fr": None,
                "iso3": "AUT",
                "type": "DAC member",
            },
            {
                "code": "901",
                "name_en": "World Bank Group",
                "name_fr": None,
                "iso3": None,
                "type": "Multilateral",
            },
        ],
        channels=[
            {
                "code": "10000",
                "name_en": "Public Sector",
                "name_fr": None,
                "category": "10000",
                "acronym": None,
            }
        ],
        agencies=[
            {
                "code": "1",
                "name_en": "Austrian Ministry",
                "name_fr": None,
                "donor_code": "1",
                "acronym": None,
            }
        ],
    )
    cw_path = _minimal_crosswalk_yaml(tmp_path)

    result = _run_enricher(geo_db, org_db, yaml_path, cw_path)

    # Deltas must always be present for both keys regardless of which DBs are used.
    assert set(result.keys()) == {"geo", "org"}
    assert set(result["geo"].keys()) == {"entities", "names", "codes", "relations"}
    assert set(result["org"].keys()) == {"entities", "names", "codes", "relations"}

    if use_geo and geo_db is not None:
        # Recipient code attached to geo entity
        recipient_code = _query_one(
            geo_db,
            "SELECT value FROM codes WHERE entity_id='country/TUR' AND system='oecd:recipient'",
        )
        assert recipient_code is not None, (
            "geo: oecd:recipient code missing from country/TUR"
        )
        assert recipient_code[0] == "55"

        # Country-provider code attached to geo entity
        provider_code = _query_one(
            geo_db,
            "SELECT value FROM codes WHERE entity_id='country/AUT' AND system='oecd:provider'",
        )
        assert provider_code is not None, (
            "geo: oecd:provider code missing from country/AUT"
        )
        assert provider_code[0] == "1"

        # Deltas must be positive for geo
        assert result["geo"]["codes"] > 0, "geo delta codes should be > 0"
    else:
        # geo absent — zero deltas
        assert result["geo"] == {"entities": 0, "names": 0, "codes": 0, "relations": 0}

    if use_org and org_db is not None:
        # Multilateral org entity created in org DB
        org_entity = _query_one(
            org_db,
            "SELECT entity_id, entity_type FROM entities WHERE entity_id='org/oecd:provider:901'",
        )
        assert org_entity is not None, "org: multilateral provider entity missing"
        assert org_entity[1] == "org.igo"

        # Channel entity created in org DB
        channel_entity = _query_one(
            org_db,
            "SELECT 1 FROM entities WHERE entity_id='org/oecd:channel:10000'",
        )
        assert channel_entity is not None, "org: channel entity missing"

        # Agency entity created in org DB
        agency_entity = _query_one(
            org_db,
            "SELECT 1 FROM entities WHERE entity_id='org/oecd:agency:AUT:1'",
        )
        assert agency_entity is not None, "org: agency entity missing"

        # Deltas must be positive for org
        assert result["org"]["entities"] > 0, "org delta entities should be > 0"
    else:
        # org absent — zero deltas; org entities must not appear in geo DB
        assert result["org"] == {"entities": 0, "names": 0, "codes": 0, "relations": 0}
        if use_geo and geo_db is not None:
            org_in_geo = _query_one(
                geo_db,
                "SELECT 1 FROM entities WHERE entity_id='org/oecd:provider:901'",
            )
            assert org_in_geo is None, (
                "org-prefixed entity must not be in geo DB when org_db=None"
            )


# ---------------------------------------------------------------------------
# Characterization test: exact per-table delta values on a first run
# ---------------------------------------------------------------------------

# All-zero delta shape — reused in the idempotency assertion below.
_Z: dict[str, int] = {"entities": 0, "names": 0, "codes": 0, "relations": 0}


@pytest.mark.unit
def test_first_run_deltas_pin_exact_per_table_counts(tmp_path: Path) -> None:
    """Pin exact per-table delta values returned by enrich_oecd_dac on a
    known first-run geo+org input.

    These are *characterization* literals captured from HEAD — they pin the
    current behavior so that a later delta-counting refactor can be verified
    for preservation. Provenance comment on each integer explains which upsert
    produced it.
    """
    geo_db = _build_geo_db(tmp_path)
    org_db = _build_org_db(tmp_path)

    yaml_path = _minimal_oecd_yaml(
        tmp_path,
        recipients=[
            {
                "code": "55",
                "name_en": "Türkiye",
                "name_fr": None,
                "iso3": "TUR",
                "type": "Country",
            }
        ],
        providers=[
            {
                "code": "1",
                "name_en": "Austria",
                "name_fr": None,
                "iso3": "AUT",
                "type": "DAC member",
            },
            {
                "code": "901",
                "name_en": "World Bank Group",
                "name_fr": None,
                "iso3": None,
                "type": "Multilateral",
            },
        ],
        channels=[
            {
                "code": "10000",
                "name_en": "Public Sector",
                "name_fr": None,
                "category": "10000",
                "acronym": None,
            }
        ],
        agencies=[
            {
                "code": "1",
                "name_en": "Austrian Ministry",
                "name_fr": None,
                "donor_code": "1",
                "acronym": None,
            }
        ],
    )
    cw_path = _minimal_crosswalk_yaml(tmp_path)

    result = _run_enricher(geo_db, org_db, yaml_path, cw_path)

    assert (
        result
        == {
            "geo": {
                "entities": 0,  # Türkiye→country/TUR (existing), Austria→country/AUT (existing): no new entities
                "names": 2,  # name_en "Türkiye" on country/TUR + name_en "Austria" on country/AUT
                "codes": 2,  # oecd:recipient=55 on country/TUR + oecd:provider=1 on country/AUT
                "relations": 0,  # no new geo relations from recipients/country-providers
            },
            "org": {
                "entities": 3,  # org/oecd:provider:901 (World Bank, igo) + org/oecd:channel:10000 (Public Sector) + org/oecd:agency:AUT:1 (Austrian Ministry)
                "names": 3,  # one name_en per entity (World Bank Group, Public Sector, Austrian Ministry)
                "codes": 3,  # oecd:provider=901 + oecd:channel=10000 + oecd:agency=AUT:1
                "relations": 1,  # subsidiary_of → country/AUT for org/oecd:agency:AUT:1; category==code for channel → no part_of
            },
        }
    )

    # Idempotency: second run must produce all-zero deltas for both domains.
    second = _run_enricher(geo_db, org_db, yaml_path, cw_path)
    assert second == {"geo": _Z, "org": _Z}
