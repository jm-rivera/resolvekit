"""Geo benchmark guard for M5 (markdown / HTML normalization).

Two guards:
  1. Accuracy table  — 12 representative queries → expected entity_ids.
  2. Latency gate    — p50 latency with M5 flags enabled must be within
                       15% of an inline baseline measured with flags off.
                       This is machine-independent: we compare flag-off vs
                       flag-on on the same box in the same test run.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from statistics import median

import pytest

from resolvekit.core.api import Resolver
from resolvekit.core.datapack import NORMALIZER_VERSION
from resolvekit.core.model import ResolutionStatus

# ---------------------------------------------------------------------------
# Fixtures — module-scoped so the DB is created once for all tests
# ---------------------------------------------------------------------------

_DATAPACK_SCHEMA = """
    CREATE TABLE entities (
        entity_id TEXT PRIMARY KEY, entity_type TEXT NOT NULL,
        canonical_name TEXT NOT NULL, canonical_name_norm TEXT NOT NULL,
        valid_from TEXT, valid_until TEXT
    );
    CREATE TABLE names (
        entity_id TEXT NOT NULL, name_kind TEXT NOT NULL,
        value TEXT NOT NULL, value_norm TEXT NOT NULL,
        lang TEXT, is_preferred INTEGER DEFAULT 0
    );
    CREATE TABLE codes (
        entity_id TEXT NOT NULL, system TEXT NOT NULL,
        value TEXT NOT NULL, value_norm TEXT NOT NULL,
        PRIMARY KEY (entity_id, system)
    );
    CREATE TABLE relations (
        entity_id TEXT NOT NULL, relation_type TEXT NOT NULL,
        target_id TEXT NOT NULL
    );
    CREATE VIRTUAL TABLE names_fts USING fts5(entity_id, value_norm);
    INSERT INTO entities VALUES
        ('country/USA','geo.country','United States','united states',NULL,NULL),
        ('country/GBR','geo.country','United Kingdom','united kingdom',NULL,NULL);
    INSERT INTO codes VALUES
        ('country/USA','iso2','US','us'),('country/USA','iso3','USA','usa'),
        ('country/GBR','iso2','GB','gb'),('country/GBR','iso3','GBR','gbr');
    INSERT INTO names VALUES
        ('country/USA','canonical','United States','united states','en',1),
        ('country/GBR','canonical','United Kingdom','united kingdom','en',1);
    INSERT INTO names_fts(entity_id, value_norm) VALUES
        ('country/USA','united states'),('country/GBR','united kingdom');
"""

_DATAPACK_META = {
    "datapack_id": "geo_guard_v1",
    "module_id": "geo.countries",
    "domain_pack_id": "geo",
    "entity_schema_version": "1.0",
    "feature_schema_version": "geo.features.v1",
    "normalizer_version": NORMALIZER_VERSION,
    "index_versions": {"fts": "fts5", "symspell": None},
    "build_timestamp": "2026-04-24T00:00:00Z",
    "source_datasets": ["guard-fixture"],
}


@pytest.fixture(scope="module")
def guard_datapack(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Module-scoped minimal geo datapack used by all guard tests."""
    tmp = tmp_path_factory.mktemp("geo_guard")
    conn = sqlite3.connect(tmp / "entities.sqlite")
    conn.executescript(_DATAPACK_SCHEMA)
    conn.commit()
    conn.close()
    (tmp / "metadata.json").write_text(json.dumps(_DATAPACK_META))
    return tmp


@pytest.fixture(scope="module")
def geo_resolver(guard_datapack: Path):
    """Module-scoped resolver (M5 flags on via GEO_NORMALIZATION_PROFILE)."""
    resolver = Resolver.from_datapacks(datapack_paths=[guard_datapack], domains=["geo"])
    yield resolver
    resolver.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_N_LATENCY = 500  # unique synthetic queries per resolver for latency gate


def _measure_p50_ms(resolver: Resolver, queries: list[str]) -> float:
    """Return p50 latency in milliseconds across *queries*."""
    latencies: list[float] = []
    for q in queries:
        t0 = time.perf_counter()
        resolver.resolve(q)
        latencies.append((time.perf_counter() - t0) * 1_000)
    return float(median(latencies))


# ---------------------------------------------------------------------------
# 12-row accuracy table
# ---------------------------------------------------------------------------

# Each row: (raw_query, expected_entity_id)
# The fixture has:
#   country/USA — canonical "United States", codes iso2=US iso3=USA
#   country/GBR — canonical "United Kingdom", codes iso2=GB iso3=GBR
_ACCURACY_TABLE: list[tuple[str, str]] = [
    # Plain-text canonical names
    ("United States", "country/USA"),
    ("United Kingdom", "country/GBR"),
    # ISO-2 codes
    ("US", "country/USA"),
    ("GB", "country/GBR"),
    # ISO-3 codes
    ("USA", "country/USA"),
    ("GBR", "country/GBR"),
    # Markdown bold (M5 — geo profile strips ** markers)
    ("**United States**", "country/USA"),
    # Markdown italic (M5)
    ("_United Kingdom_", "country/GBR"),
    # Markdown heading (M5 — leading # stripped)
    ("# United States", "country/USA"),
    # HTML numeric entity &#85; → 'U', giving "US" (M5 decode)
    ("&#85;S", "country/USA"),
    # Blockquote marker (M5 — leading > stripped)
    ("> United Kingdom", "country/GBR"),
    # Code marker (M5 — backtick stripped)
    ("`United States`", "country/USA"),
]


@pytest.mark.parametrize("query,expected_entity_id", _ACCURACY_TABLE)
def test_geo_accuracy_table(
    geo_resolver: Resolver, query: str, expected_entity_id: str
) -> None:
    """Each representative query resolves to the expected entity."""
    result = geo_resolver.resolve(query)
    assert result.status == ResolutionStatus.RESOLVED, (
        f"Expected RESOLVED for {query!r}, got {result.status} "
        f"(entity_id={result.entity_id!r})"
    )
    assert result.entity_id == expected_entity_id, (
        f"Query {query!r}: expected {expected_entity_id!r}, got {result.entity_id!r}"
    )


# ---------------------------------------------------------------------------
# Latency gate
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_geo_latency_p50_within_15pct_of_no_flag_baseline(
    guard_datapack: Path,
) -> None:
    """p50 latency with M5 flags enabled is within 15% of flag-off baseline.

    Uses synthetic queries (pool of N unique strings) so the result is
    machine-independent: we compare flag-off vs flag-on in the same process.

    Note: the guard datapack is minimal (2 entities); absolute latencies will
    be much lower than the real geo dataset.  The gate checks *relative*
    overhead, not absolute performance. The 15% budget and absolute gate are
    enforced by separate benchmark runs.
    """
    from resolvekit.core.util.normalization import TextNormalizer
    from resolvekit.packs.geo.pack import GEO_NORMALIZATION_PROFILE

    # Flag-OFF profile: same as geo but with M5 passes disabled
    no_flag_profile = GEO_NORMALIZATION_PROFILE.model_copy(
        update={"strip_markdown_formatting": False, "decode_html_entities": False}
    )

    # Plain-text queries without hint chars — the short-circuit fires for
    # flag-on too, so we measure only the cost of _MD_HTML_HINT_RE.search().
    queries = [f"entity_{i}" for i in range(_N_LATENCY)]

    flag_off = Resolver.from_datapacks(datapack_paths=[guard_datapack], domains=["geo"])
    # Inject the flag-off normalizer after construction
    flag_off._pack_normalizers["geo"] = TextNormalizer(no_flag_profile)

    flag_on = Resolver.from_datapacks(datapack_paths=[guard_datapack], domains=["geo"])

    # Warm up both resolvers before timing
    for _ in range(10):
        flag_off.resolve("United States")
        flag_on.resolve("United States")

    baseline_p50 = _measure_p50_ms(flag_off, queries)
    flagged_p50 = _measure_p50_ms(flag_on, queries)

    budget = baseline_p50 * 1.15
    assert flagged_p50 <= budget, (
        f"M5 latency regression: p50 with flags ON is {flagged_p50:.4f} ms, "
        f"but baseline (flags OFF) is {baseline_p50:.4f} ms "
        f"(budget: {budget:.4f} ms, 15% overhead allowed)."
    )
