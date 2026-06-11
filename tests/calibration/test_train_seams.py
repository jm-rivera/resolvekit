"""Tests for the public calibration/resolver seams.

Covers:
- query_stratified_split importable as a public, kwargs-only function
- Resolver.store_for_domain returns the correct EntityStore
"""

from __future__ import annotations

import json
import random
import sqlite3
from pathlib import Path

import pytest

from resolvekit.calibration.dataset import LabeledExample
from resolvekit.calibration.train import query_stratified_split
from resolvekit.core.datapack import NORMALIZER_VERSION
from resolvekit.core.store import EntityStore

# ---------------------------------------------------------------------------
# query_stratified_split is public and kwargs-only
# ---------------------------------------------------------------------------


def _make_examples(n_pos: int, n_neg: int) -> list[LabeledExample]:
    """Build a minimal list of labeled examples for split tests."""
    examples: list[LabeledExample] = []
    for i in range(n_pos):
        examples.append(
            LabeledExample(
                query_text=f"query_pos_{i}",
                expected_entity_id=f"country/P{i:03d}",
                domain="geo",
                source_adapter="synthetic",
                label=1,
                raw_score=0.9,
            )
        )
    for i in range(n_neg):
        examples.append(
            LabeledExample(
                query_text=f"query_neg_{i}",
                expected_entity_id=f"country/N{i:03d}",
                domain="geo",
                source_adapter="synthetic",
                label=0,
                raw_score=0.1,
            )
        )
    return examples


def test_query_stratified_split_is_public() -> None:
    """query_stratified_split is importable without the leading underscore."""
    # import already at module top — verifies the name is public
    assert callable(query_stratified_split)


def test_query_stratified_split_kwargs_only() -> None:
    """Calling with positional args raises TypeError (kwargs-only contract)."""
    examples = _make_examples(10, 10)
    rng = random.Random(0)
    with pytest.raises(TypeError):
        query_stratified_split(examples, 0.2, rng)  # type: ignore[call-arg]


def test_query_stratified_split_basic() -> None:
    """Split partitions all examples and produces both classes in train."""
    examples = _make_examples(20, 20)
    rng = random.Random(42)
    train, eval_ = query_stratified_split(examples=examples, eval_split=0.2, rng=rng)

    assert len(train) + len(eval_) == len(examples)
    train_labels = {e.label for e in train}
    assert 0 in train_labels and 1 in train_labels


def test_query_stratified_split_zero_eval() -> None:
    """eval_split=0 puts everything in train, nothing in eval."""
    examples = _make_examples(5, 5)
    rng = random.Random(0)
    train, eval_ = query_stratified_split(examples=examples, eval_split=0.0, rng=rng)

    assert len(train) == len(examples)
    assert eval_ == []


# ---------------------------------------------------------------------------
# Resolver.store_for_domain — store identity preserved
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def geo_datapack(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Minimal geo DataPack for Resolver construction."""
    tmp_path = tmp_path_factory.mktemp("geo_seam_datapack")
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
                "datapack_id": "geo_seam_v1",
                "module_id": "geo.countries",
                "domain_pack_id": "geo",
                "entity_schema_version": "1.0",
                "feature_schema_version": "geo.features.v1",
                "normalizer_version": NORMALIZER_VERSION,
                "index_versions": {"fts": "fts5", "symspell": None},
                "build_timestamp": "2024-01-15T10:00:00Z",
                "source_datasets": ["test-fixture"],
            }
        ),
        encoding="utf-8",
    )

    return tmp_path


def test_resolver_store_for_domain_returns_entitystore(geo_datapack: Path) -> None:
    """store_for_domain("geo") returns an EntityStore."""
    from resolvekit.core.api.resolver import Resolver

    with Resolver.from_datapacks(datapack_paths=[geo_datapack]) as resolver:
        store = resolver.store_for_domain("geo")
        assert isinstance(store, EntityStore)


def test_resolver_store_for_domain_same_instance_as_runner(geo_datapack: Path) -> None:
    """store_for_domain returns the identical object the runner holds (engine-behavior fence)."""
    from resolvekit.core.api.resolver import Resolver

    with Resolver.from_datapacks(datapack_paths=[geo_datapack]) as resolver:
        store = resolver.store_for_domain("geo")

        # Reach into the runner to verify store identity
        runner = resolver._runner
        stores: dict = getattr(runner, "_stores", {})
        expected = stores.get("geo") or next(
            (s for k, s in stores.items() if k.startswith("geo")), None
        )
        assert expected is not None, "runner._stores has no geo entry"
        assert store is expected


def test_resolver_store_for_domain_unknown_raises(geo_datapack: Path) -> None:
    """store_for_domain raises ValueError for an unknown domain."""
    from resolvekit.core.api.resolver import Resolver

    with (
        Resolver.from_datapacks(datapack_paths=[geo_datapack]) as resolver,
        pytest.raises(ValueError, match="org"),
    ):
        resolver.store_for_domain("org")
