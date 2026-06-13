"""Shared test fixtures for tests."""

import importlib.util
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from resolvekit.core.datapack import NORMALIZER_VERSION

# Test paths that require the `calibration` extra (gecko-syndata). gecko-syndata
# pins lxml<6, which has no Python 3.14 wheel, so these are skipped whenever
# gecko is not importable: the CI 3.14 ceiling leg, and any local env without
# the calibration extra. On the 3.12 / macOS / Windows legs (all extras
# installed) gecko is present and nothing here is skipped.
if importlib.util.find_spec("gecko") is None:
    collect_ignore = [
        "builder",
        "building",
        "benchmarks",
        "calibration",
        "calibrate",
        "parse/test_baselines.py",
        "parse/test_parse_eval_adapter.py",
        "parse/test_parse_eval_dataset.py",
        "parse/test_span_metrics.py",
        "release/test_verify_bundled_data_freshness.py",
        "test_benchmark_autocomplete.py",
        "test_benchmark_resolver.py",
    ]
from resolvekit.core.explain import MemoryTraceSink, NullTraceSink
from resolvekit.core.model import (
    EntityRecord,
    NormalizedText,
    Query,
    ResolutionContext,
)
from resolvekit.core.model.entity import CodeRecord
from resolvekit.core.store import EntityStore


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="Run tests marked as slow (e.g., benchmarks).",
    )
    parser.addoption(
        "--run-remote-data",
        action="store_true",
        default=False,
        help="Run tests marked requires_remote_data (downloads/uses ~800MB remote data packs).",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    run_slow = config.getoption("--run-slow")
    run_remote_data = config.getoption("--run-remote-data")
    skip_slow = pytest.mark.skip(reason="needs --run-slow to run")
    skip_remote = pytest.mark.skip(
        reason="needs --run-remote-data to run (uses remote data packs not bundled)"
    )
    for item in items:
        if not run_slow and "slow" in item.keywords:
            item.add_marker(skip_slow)
        if not run_remote_data and "requires_remote_data" in item.keywords:
            item.add_marker(skip_remote)


class MockEntityStore(EntityStore):
    """Configurable mock store for tests.

    Provides a reusable EntityStore implementation that can be configured
    with specific entities and code mappings for each test.

    Args:
        entities: Dict mapping entity_id to EntityRecord
        codes: Dict mapping (system, value_norm) tuples to list of entity_ids
        names: Dict mapping value_norm to list of entity_ids for exact name lookup
    """

    def __init__(
        self,
        entities: dict[str, EntityRecord] | None = None,
        codes: dict[tuple[str, str], list[str]] | None = None,
        names: dict[str, list[str]] | None = None,
    ):
        self._entities = entities or {}
        self._codes = codes or {}
        self._names = names or {}

    def get_entity(self, entity_id: str) -> EntityRecord | None:
        return self._entities.get(entity_id)

    def lookup_code(self, system: str, value_norm: str) -> list[str]:
        return self._codes.get((system, value_norm), [])

    def lookup_code_any(self, value_norm: str) -> list[tuple[str, str]]:
        results: list[tuple[str, str]] = []
        for (system, stored_norm), entity_ids in self._codes.items():
            if stored_norm == value_norm:
                for eid in entity_ids:
                    results.append((eid, system))
        return results

    def lookup_name_exact(
        self, value_norm: str, name_kinds: set[str] | None = None
    ) -> list[str]:
        return self._names.get(value_norm, [])

    def search_fulltext(
        self, query_norm: str, fields: set[str] | None = None, limit: int = 10
    ) -> list[tuple[str, float, int]]:
        return []

    def all_entity_ids(self) -> set[str]:
        return set(self._entities.keys())

    def bulk_get_entities(self, entity_ids: list[str]) -> dict[str, EntityRecord]:
        return {eid: e for eid in entity_ids if (e := self.get_entity(eid))}

    def get_reverse_relations(
        self,
        target_id: str,
        relation_type: str,
        *,
        as_of: date | None = None,
    ) -> list[str]:
        """Return entity IDs whose relations include (relation_type, target_id).

        Derived by scanning every stored entity's ``relations`` list.  Honors
        the half-open ``[valid_from, valid_until)`` ``as_of`` filter when set.
        Matches the ``EntityStore.get_reverse_relations`` interface signature.
        """
        result: list[str] = []
        for eid, entity in self._entities.items():
            for rel in entity.relations:
                if rel.relation_type != relation_type or rel.target_id != target_id:
                    continue
                if as_of is not None:
                    as_of_str = as_of.isoformat()
                    if rel.valid_from is not None and as_of_str < rel.valid_from:
                        continue
                    if rel.valid_until is not None and as_of_str >= rel.valid_until:
                        continue
                result.append(eid)
                break  # each entity contributes at most once per (type, target)
        return result


def make_query(text: str, normalized: str | None = None) -> Query:
    """Create a Query with normalized text.

    Args:
        text: Raw input text
        normalized: Normalized form (defaults to text.lower())

    Returns:
        Query object ready for use in tests
    """
    norm = normalized if normalized is not None else text.lower()
    return Query(
        raw_text=text,
        normalized=NormalizedText(original=text, normalized=norm),
    )


@pytest.fixture
def empty_store() -> MockEntityStore:
    """Empty mock store with no entities."""
    return MockEntityStore()


@pytest.fixture
def null_trace() -> NullTraceSink:
    """Null trace sink that discards events."""
    return NullTraceSink()


@pytest.fixture
def memory_trace() -> MemoryTraceSink:
    """Memory trace sink that collects events."""
    return MemoryTraceSink()


@pytest.fixture
def empty_context() -> ResolutionContext:
    """Empty resolution context."""
    return ResolutionContext()


@pytest.fixture
def usa_store() -> MockEntityStore:
    """Mock store with USA entity for common test scenarios."""
    return MockEntityStore(
        entities={
            "country/USA": EntityRecord(
                entity_id="country/USA",
                entity_type="geo.country",
                canonical_name="United States of America",
                canonical_name_norm="united states of america",
                codes=[
                    CodeRecord(system="iso2", value="US", value_norm="us"),
                    CodeRecord(system="iso3", value="USA", value_norm="usa"),
                    CodeRecord(
                        system="dcid", value="country/USA", value_norm="country/usa"
                    ),
                ],
            ),
        },
        codes={
            ("iso2", "us"): ["country/USA"],
            ("iso3", "usa"): ["country/USA"],
            ("dcid", "country/usa"): ["country/USA"],  # normalized key
        },
    )


@pytest.fixture(scope="session")
def geo_test_datapack(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create a minimal geo DataPack for resolver tests.

    Session-scoped: the SQLite + metadata file pair is read-only across
    consumers, so a single build amortises the ~50 ms cost across the whole
    test suite.
    """
    tmp_path = tmp_path_factory.mktemp("geo_test_datapack")
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
            ('country/USA', 'geo.country', 'United States', 'united states', NULL, NULL),
            ('country/GBR', 'geo.country', 'United Kingdom', 'united kingdom', NULL, NULL);
        INSERT INTO codes VALUES
            ('country/USA', 'iso2', 'US', 'us'),
            ('country/USA', 'iso3', 'USA', 'usa'),
            ('country/GBR', 'iso2', 'GB', 'gb'),
            ('country/GBR', 'iso3', 'GBR', 'gbr');
        INSERT INTO names VALUES
            ('country/USA', 'canonical', 'United States', 'united states', 'en', 1),
            ('country/GBR', 'canonical', 'United Kingdom', 'united kingdom', 'en', 1);
        INSERT INTO names_fts(entity_id, value_norm) VALUES
            ('country/USA', 'united states'),
            ('country/GBR', 'united kingdom');
    """
    )
    conn.commit()
    conn.close()

    (tmp_path / "metadata.json").write_text(
        json.dumps(
            {
                "datapack_id": "geo_test_v1",
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
