"""Fork safety: constructing Resolver post-fork must work in child process."""

from __future__ import annotations

import json
import multiprocessing
import sqlite3
import sys
from pathlib import Path

import pytest

from resolvekit.core.datapack import NORMALIZER_VERSION


def _build_datapack(tmp_path: Path) -> Path:
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
                "datapack_id": "geo_fork_test_v1",
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


def _child_resolve(
    datapack_path: str, result_queue: multiprocessing.Queue[int]
) -> None:
    """Run inside a forked child: construct Resolver and resolve."""
    try:
        from resolvekit.core.api import Resolver

        with Resolver.from_datapacks(
            datapack_paths=[Path(datapack_path)], domains=["geo"]
        ) as resolver:
            result = resolver.resolve(text="United States")
        if result.entity_id == "country/USA":
            result_queue.put(0)
        else:
            result_queue.put(1)
    except Exception:
        result_queue.put(2)


@pytest.mark.skipif(sys.platform == "win32", reason="fork not available on Windows")
def test_resolver_works_post_fork(tmp_path: Path) -> None:
    """A Resolver constructed after fork in the child must resolve correctly."""
    datapack_path = _build_datapack(tmp_path)
    ctx = multiprocessing.get_context("fork")
    q: multiprocessing.Queue[int] = ctx.Queue()
    proc = ctx.Process(target=_child_resolve, args=(str(datapack_path), q))
    proc.start()
    proc.join(timeout=15)

    assert proc.exitcode == 0, f"Child process exited with code {proc.exitcode}"
    assert not q.empty(), "Child did not put a result in the queue"
    exit_code = q.get_nowait()
    assert exit_code == 0, f"Child resolve returned error code {exit_code}"
