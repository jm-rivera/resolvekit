"""Thread safety: concurrent resolve calls must be consistent and exception-free."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

from resolvekit.core.api import Resolver
from resolvekit.core.datapack import NORMALIZER_VERSION


@pytest.fixture
def countries_datapack(tmp_path: Path) -> Path:
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
            ('country/USA', 'geo.country', 'United States', 'united states', NULL, NULL);
        INSERT INTO codes VALUES
            ('country/USA', 'iso2', 'US', 'us'),
            ('country/USA', 'iso3', 'USA', 'usa');
        INSERT INTO names VALUES
            ('country/USA', 'canonical', 'United States', 'united states', 'en', 1);
        INSERT INTO names_fts(entity_id, value_norm) VALUES
            ('country/USA', 'united states');
        """
    )
    conn.commit()
    conn.close()

    (tmp_path / "metadata.json").write_text(
        json.dumps(
            {
                "datapack_id": "geo_thread_test_v1",
                "module_id": "geo.countries",
                "domain_pack_id": "geo",
                "entity_schema_version": "1.0",
                "feature_schema_version": "geo.features.v1",
                "normalizer_version": NORMALIZER_VERSION,
                "index_versions": {"fts": "fts5", "symspell": None},
                "build_timestamp": "2024-01-15T10:00:00Z",
                "source_datasets": ["test-fixture"],
            }
        )
    )
    return tmp_path


def test_concurrent_resolve_is_consistent(countries_datapack: Path) -> None:
    """16 threads each doing 200 resolves must all agree and raise no exceptions."""
    n_threads = 16
    n_calls = 200
    results: list[str | None] = []
    errors: list[Exception] = []

    with Resolver.from_datapacks(
        datapack_paths=[countries_datapack], domains=["geo"], cache_size=0
    ) as resolver:

        def worker() -> list[str | None]:
            out: list[str | None] = []
            for _ in range(n_calls):
                result = resolver.resolve(text="United States")
                out.append(result.entity_id)
            return out

        with ThreadPoolExecutor(max_workers=n_threads) as pool:
            futures = [pool.submit(worker) for _ in range(n_threads)]
            for future in as_completed(futures):
                try:
                    results.extend(future.result())
                except Exception as exc:
                    errors.append(exc)

    assert not errors, f"Exceptions in worker threads: {errors}"
    assert len(results) == n_threads * n_calls
    unique = set(results)
    assert len(unique) == 1, f"Inconsistent results across threads: {unique}"
    assert "country/USA" in unique
