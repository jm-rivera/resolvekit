"""Statistical-power gate for the curated eval sets.

Asserts per-entity_type row counts meet the ≥40 floor for meaningful
regression detection. Does not assert accuracy numbers (those are
truth-dependent and reviewed separately).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import polars as pl
import pytest

from benchmarks.core.loader import load_dataset

_FLOOR = 40


@pytest.fixture(scope="module")
def eval_rows():
    return load_dataset("eval_geo")


@pytest.fixture(scope="module")
def eval_frame():
    data_dir = Path(__file__).parent.parent.parent / "benchmarks" / "data"
    return pl.read_parquet(data_dir / "eval_geo.parquet")


@pytest.fixture(scope="module")
def eval_org_rows():
    return load_dataset("eval_org")


def test_no_country_region_rows(eval_rows) -> None:
    """All country_region labels have been renamed to admin1."""
    bad = [r for r in eval_rows if r.entity_type == "country_region"]
    assert bad == [], (
        f"Found {len(bad)} row(s) still labeled entity_type='country_region': "
        + ", ".join(r.query_id for r in bad[:5])
    )


def test_no_org_rows_in_main_eval(eval_rows) -> None:
    """Main eval set contains zero org rows (org moved to eval_org)."""
    org_rows = [r for r in eval_rows if r.entity_type == "org"]
    assert org_rows == [], (
        f"Found {len(org_rows)} org row(s) in main eval set; they belong in eval_org. "
        + ", ".join(r.query_id for r in org_rows[:5])
    )


def test_admin1_count_meets_floor(eval_rows) -> None:
    types = Counter(r.entity_type for r in eval_rows)
    assert types["admin1"] >= _FLOOR, f"admin1 count {types['admin1']} < {_FLOOR}"


def test_admin2_count_meets_floor(eval_rows) -> None:
    types = Counter(r.entity_type for r in eval_rows)
    assert types["admin2"] >= _FLOOR, f"admin2 count {types['admin2']} < {_FLOOR}"


def test_admin3_count_meets_floor(eval_rows) -> None:
    types = Counter(r.entity_type for r in eval_rows)
    assert types["admin3"] >= _FLOOR, f"admin3 count {types['admin3']} < {_FLOOR}"


def test_admin4_count_meets_floor(eval_rows) -> None:
    types = Counter(r.entity_type for r in eval_rows)
    assert types["admin4"] >= _FLOOR, f"admin4 count {types['admin4']} < {_FLOOR}"


def test_admin5_count_meets_floor(eval_rows) -> None:
    types = Counter(r.entity_type for r in eval_rows)
    assert types["admin5"] >= _FLOOR, f"admin5 count {types['admin5']} < {_FLOOR}"


# eval_org was re-scoped to the IGOs/development orgs that ship in the org pack
# (international NGOs like MSF/Oxfam/HRW were dropped — they aren't in the data).
# Its floor is lower than the geo strata until the org pack's coverage grows.
_ORG_FLOOR = 20


def test_eval_org_count_meets_floor(eval_org_rows) -> None:
    """eval_org has enough in-scope org rows for meaningful measurement."""
    org_count = sum(1 for r in eval_org_rows if r.entity_type == "org")
    assert org_count >= _ORG_FLOOR, f"eval_org org count {org_count} < {_ORG_FLOOR}"


def test_eval_org_contains_only_org_rows(eval_org_rows) -> None:
    """eval_org contains exclusively org entity_type rows."""
    non_org = [r for r in eval_org_rows if r.entity_type != "org"]
    assert non_org == [], (
        f"Found {len(non_org)} non-org row(s) in eval_org: "
        + ", ".join(r.query_id for r in non_org[:5])
    )


def test_capabilities_populated(eval_rows) -> None:
    """At least one row has a non-empty capabilities tuple."""
    with_caps = [r for r in eval_rows if r.capabilities]
    assert len(with_caps) > 0, "No rows have non-empty capabilities"


def test_capabilities_has_iso_code_rows(eval_rows) -> None:
    """iso_code capability tag is present in the dataset."""
    iso_rows = [r for r in eval_rows if "iso_code" in r.capabilities]
    assert len(iso_rows) > 0, "No rows tagged with iso_code capability"


def test_capabilities_has_informal_alias_rows(eval_rows) -> None:
    """informal_alias capability tag is present in the dataset."""
    alias_rows = [r for r in eval_rows if "informal_alias" in r.capabilities]
    assert len(alias_rows) > 0, "No rows tagged with informal_alias capability"


def test_capabilities_has_multilingual_rows(eval_rows) -> None:
    """multilingual capability tag is present (non-English rows)."""
    ml_rows = [r for r in eval_rows if "multilingual" in r.capabilities]
    assert len(ml_rows) > 0, "No rows tagged with multilingual capability"


def test_total_row_count_above_original(eval_rows) -> None:
    """Total row count exceeds the original 376 (curation added rows)."""
    assert len(eval_rows) > 376, (
        f"Expected more than 376 rows after curation, got {len(eval_rows)}"
    )


def test_parquet_column_set(eval_frame) -> None:
    """Parquet has exactly the 10 canonical columns."""
    expected = {
        "query_id",
        "query",
        "expected_ids",
        "language",
        "entity_type",
        "category",
        "difficulty",
        "capabilities",
        "source",
        "notes",
    }
    assert set(eval_frame.columns) == expected
