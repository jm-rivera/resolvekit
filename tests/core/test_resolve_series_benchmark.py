"""Throughput benchmarks for resolve_series and resolve_series_explained.

Each test is guarded by ``@pytest.mark.slow`` and skipped unless the
``--run-slow`` flag is passed to pytest.  Run with::

    uv run pytest tests/core/test_resolve_series_benchmark.py --run-slow --benchmark-only

Median budget: < 1.0 s per test on a laptop.
"""

import json
import sqlite3
from pathlib import Path
from statistics import quantiles
from typing import Any

import pandas as pd
import pytest

from resolvekit.core.api import Resolver

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def benchmark_datapack(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Minimal geo DataPack with two entities for benchmark tests.

    Reuses the same schema as ``geo_test_datapack`` but is module-scoped so
    the SQLite file is created only once across all benchmark tests.
    """
    tmp_path = tmp_path_factory.mktemp("bench_datapack")
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
                "datapack_id": "geo_bench_v1",
                "module_id": "geo.countries",
                "domain_pack_id": "geo",
                "entity_schema_version": "1.0",
                "feature_schema_version": "geo.features.v1",
                "index_versions": {"fts": "fts5", "symspell": None},
                "build_timestamp": "2024-01-15T10:00:00Z",
                "source_datasets": ["bench-fixture"],
            }
        )
    )
    return tmp_path


@pytest.fixture(scope="module")
def benchmark_resolver(benchmark_datapack: Path) -> Resolver:
    """Module-scoped Resolver for benchmark tests."""
    return Resolver.from_datapacks([benchmark_datapack], packs=["geo"])


def _p95(benchmark: Any) -> float:
    """Return the p95 from raw benchmark timing data."""
    # benchmark.stats is Metadata; Metadata.stats is Stats; Stats.data is the raw list.
    data = sorted(benchmark.stats.stats.data)
    if len(data) < 2:
        return benchmark.stats.stats.median  # type: ignore[no-any-return]
    # quantiles(data, n=20) gives 19 cut-points at 5%, 10%, ..., 95%.
    return quantiles(data, n=20)[-1]


def _make_series(n: int, k: int) -> pd.Series:
    """Create a Series of length *n* with *k* unique string values.

    The first two values map to real entities; the rest are synthetic
    no-match tokens of the form ``"entity_NNN"``.  Values tile from a pool
    of size *k*, giving an even distribution across positions.
    """
    pool = ["United States", "United Kingdom"] + [f"entity_{i}" for i in range(k - 2)]
    values = [pool[i % k] for i in range(n)]
    return pd.Series(values)


def _make_mixed_series(n: int, k: int) -> pd.Series:
    """Create an N-length Series with K uniques plus ~10% NaN and ~5% non-string.

    Exercises the NaN-coercion branch and the ``str(v)`` fallback that the
    all-string benches never hit. Catches regressions in the lambda-based
    str-coercion path inside ``_resolve_series_dedup``.
    """
    pool = ["United States", "United Kingdom"] + [f"entity_{i}" for i in range(k - 2)]
    values: list[Any] = [pool[i % k] for i in range(n)]
    # ~10% NaN
    for i in range(0, n, 10):
        values[i] = float("nan")
    # ~5% non-string (ints + pd.NaT)
    for i in range(2, n, 20):
        values[i] = i  # int
    for i in range(7, n, 20):
        values[i] = pd.NaT
    return pd.Series(values, dtype=object)


# ---------------------------------------------------------------------------
# Benchmark tests
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_resolve_series_100k_rows_with_200_uniques(
    benchmark: Any, benchmark_resolver: Resolver
) -> None:
    """100K-row Series, 200 unique values — dedup path (200 resolve calls)."""
    series = _make_series(n=100_000, k=200)

    result = benchmark(
        benchmark_resolver.resolve_series,
        series=series,
    )

    assert len(result) == 100_000
    median = benchmark.stats.stats.median
    assert median < 1.0, f"Median {median:.3f}s exceeded 1.0s budget"
    p95 = _p95(benchmark)
    assert p95 < 1.5 * median, (
        f"p95 ({p95:.3f}s) > 1.5 x median ({median:.3f}s) — unstable run"
    )


@pytest.mark.slow
def test_resolve_series_high_uniqueness_throughput(
    benchmark: Any, benchmark_resolver: Resolver
) -> None:
    """20K-row Series, 5K unique values — stresses broadcast loop O(N) path."""
    series = _make_series(n=20_000, k=5_000)

    result = benchmark(
        benchmark_resolver.resolve_series,
        series=series,
    )

    assert len(result) == 20_000
    median = benchmark.stats.stats.median
    assert median < 1.0, f"Median {median:.3f}s exceeded 1.0s budget"
    p95 = _p95(benchmark)
    assert p95 < 1.5 * median, (
        f"p95 ({p95:.3f}s) > 1.5 x median ({median:.3f}s) — unstable run"
    )


@pytest.mark.slow
def test_resolve_series_mixed_input_throughput(
    benchmark: Any, benchmark_resolver: Resolver
) -> None:
    """100K-row Series with ~10% NaN and ~5% non-string — exercises coerce paths."""
    series = _make_mixed_series(n=100_000, k=200)

    result = benchmark(
        benchmark_resolver.resolve_series,
        series=series,
    )

    assert len(result) == 100_000
    median = benchmark.stats.stats.median
    assert median < 1.0, f"Median {median:.3f}s exceeded 1.0s budget"
    p95 = _p95(benchmark)
    assert p95 < 1.5 * median, (
        f"p95 ({p95:.3f}s) > 1.5 x median ({median:.3f}s) — unstable run"
    )


@pytest.mark.slow
def test_resolve_series_explained_100k_rows_with_200_uniques(
    benchmark: Any, benchmark_resolver: Resolver
) -> None:
    """100K-row Series, 200 unique values — explained (DataFrame) form."""
    series = _make_series(n=100_000, k=200)

    result = benchmark(
        benchmark_resolver.resolve_series_explained,
        series=series,
    )

    assert len(result) == 100_000
    assert list(result.columns) == [
        "entity_id",
        "status",
        "confidence",
        "canonical_name",
        "pack_id",
    ]
    median = benchmark.stats.stats.median
    assert median < 1.0, f"Median {median:.3f}s exceeded 1.0s budget"
    p95 = _p95(benchmark)
    assert p95 < 1.5 * median, (
        f"p95 ({p95:.3f}s) > 1.5 x median ({median:.3f}s) — unstable run"
    )
