"""Smoke tests for the CalibrationRunConfig + run_calibration orchestrator."""

from __future__ import annotations

import json
import random
import sqlite3
from enum import StrEnum
from pathlib import Path

import pytest

from resolvekit.calibration.dataset import LabeledExample, save_examples_jsonl
from resolvekit.calibration.evaluation import CalibrationMetrics
from resolvekit.calibration.models import Calibrator, PlattCalibrator
from resolvekit.core.datapack import NORMALIZER_VERSION
from scripts.calibrate.calibrate_common import CalibrationRunConfig, run_calibration

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def geo_datapack(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Minimal geo DataPack for Resolver construction."""
    tmp_path = tmp_path_factory.mktemp("calibrate_common_datapack")
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
                "datapack_id": "calibrate_common_v1",
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubMethod(StrEnum):
    PLATT = "platt"


def _stub_fit_methods(
    *,
    train: list[LabeledExample],
    eval: list[LabeledExample],
    rng: random.Random,
    domain: str,
) -> dict[_StubMethod, tuple[Calibrator, CalibrationMetrics]]:
    """Stub fit callable that returns a single trivial calibrator."""
    cal = PlattCalibrator(a=-1.0, b=0.0, domain=domain, fit_n_samples=20)
    metrics = CalibrationMetrics(
        brier_score=0.1,
        log_loss=0.2,
        ece=0.05,
        adaptive_ece=0.04,
        n_samples=20,
    )
    return {_StubMethod.PLATT: (cal, metrics)}


def _make_labeled_examples(n: int, tmp_path: Path) -> Path:
    """Write *n* synthetic LabeledExample rows to a JSONL file and return its path."""
    examples: list[LabeledExample] = []
    for i in range(n):
        examples.append(
            LabeledExample(
                query_text=f"query_{i}",
                expected_entity_id=f"country/Q{i:03d}",
                domain="geo",
                source_adapter="synthetic",
                label=i % 2,
                raw_score=0.9 if i % 2 == 1 else 0.2,
            )
        )
    out = tmp_path / "examples.jsonl"
    save_examples_jsonl(examples, out)
    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_run_calibration_constructs_config(
    geo_datapack: Path,
    tmp_path: Path,
) -> None:
    """CalibrationRunConfig + run_calibration writes best-calibrator JSON."""
    from resolvekit.core.api import Resolver

    output_dir = tmp_path / "output"
    examples_jsonl = _make_labeled_examples(20, tmp_path)

    def _build_resolver(*, datapacks_root: Path) -> Resolver:
        return Resolver.from_datapacks(datapack_paths=[geo_datapack])

    config = CalibrationRunConfig(
        domain="geo",
        build_resolver=_build_resolver,
        fit_methods=_stub_fit_methods,
        output_subdir="geo",
        output_dir=output_dir,
        examples_jsonl=examples_jsonl,
    )

    run_calibration(config=config)

    best_json = output_dir / "geo" / "geo_calibrator_best.json"
    assert best_json.exists(), f"Expected {best_json} to be written by run_calibration"

    with best_json.open(encoding="utf-8") as fh:
        data = json.load(fh)
    assert "domain" in data, "Saved calibrator JSON should contain 'domain' key"
