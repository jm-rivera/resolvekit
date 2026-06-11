"""Shared fixtures for parse tests.

``parse_geo_datapack``: session-scoped minimal DataPack with Kenya and Somalia
(plus USA and GBR for completeness) — no calibrator, no checksum issues.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from resolvekit.core.datapack import NORMALIZER_VERSION

if TYPE_CHECKING:
    from resolvekit.core.api.resolver import Resolver


@pytest.fixture(scope="session")
def parse_geo_datapack(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Minimal geo DataPack with Kenya, Somalia, USA, and GBR.

    Session-scoped; no calibrator artifact so no checksum mismatch.
    Used by parse API / bulk / import-guard tests.
    """
    tmp_path = tmp_path_factory.mktemp("parse_geo_datapack")
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
            ('country/SOM', 'geo.country', 'Somalia', 'somalia', NULL, NULL),
            ('country/USA', 'geo.country', 'United States', 'united states', NULL, NULL),
            ('country/GBR', 'geo.country', 'United Kingdom', 'united kingdom', NULL, NULL);

        INSERT INTO codes VALUES
            ('country/KEN', 'iso2', 'KE', 'ke'),
            ('country/KEN', 'iso3', 'KEN', 'ken'),
            ('country/SOM', 'iso2', 'SO', 'so'),
            ('country/SOM', 'iso3', 'SOM', 'som'),
            ('country/USA', 'iso2', 'US', 'us'),
            ('country/USA', 'iso3', 'USA', 'usa'),
            ('country/GBR', 'iso2', 'GB', 'gb'),
            ('country/GBR', 'iso3', 'GBR', 'gbr');

        INSERT INTO names VALUES
            ('country/KEN', 'canonical', 'Kenya', 'kenya', 'en', 1),
            ('country/SOM', 'canonical', 'Somalia', 'somalia', 'en', 1),
            ('country/USA', 'canonical', 'United States', 'united states', 'en', 1),
            ('country/GBR', 'canonical', 'United Kingdom', 'united kingdom', 'en', 1);

        INSERT INTO names_fts(entity_id, value_norm) VALUES
            ('country/KEN', 'kenya'),
            ('country/SOM', 'somalia'),
            ('country/USA', 'united states'),
            ('country/GBR', 'united kingdom');
        """
    )
    conn.commit()
    conn.close()

    (tmp_path / "metadata.json").write_text(
        json.dumps(
            {
                "datapack_id": "parse_geo_test_v1",
                "module_id": "geo.countries",
                "domain_pack_id": "geo",
                "entity_schema_version": "1.0",
                "feature_schema_version": "geo.features.v1",
                "normalizer_version": NORMALIZER_VERSION,
                "index_versions": {"fts": "fts5", "symspell": None},
                "build_timestamp": "2026-06-04T00:00:00Z",
                "source_datasets": ["parse-test-fixture"],
            }
        )
    )
    return tmp_path


@pytest.fixture(scope="module")
def parse_geo_resolver(parse_geo_datapack: Path) -> Resolver:
    """Resolver backed by the parse_geo_datapack (Kenya, Somalia, USA, GBR).

    Uses RoutingMode.AUTO so tests verify that parse() works on a
    normally-constructed resolver (the domain-pinning via entity_types
    in _resolve_one must avoid the AUTO-mode guard).
    """
    from resolvekit.core.api.resolver import Resolver

    return Resolver.from_datapacks(datapack_paths=[parse_geo_datapack])
