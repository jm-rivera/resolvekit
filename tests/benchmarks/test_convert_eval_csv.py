"""Tests for scripts.data_maintenance.convert_eval_csv.

Round-trip correctness: write to tmp parquet via convert(), reload via polars,
verify column set and list-column semantics.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from scripts.data_maintenance.convert_eval_csv import EvalConvertConfig, convert

_EXPECTED_COLUMNS = {
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

# Minimal CSV with header matching the 9-column schema
_MINIMAL_CSV = """\
query_id,text,expected_ids,language,entity_type,category,difficulty,capabilities,source
aaa0000000000001,France,"country/FRA,wikidataId/Q142",en,country,canonical,easy,iso_code,benchmark
bbb0000000000002,Germany,country/DEU,en,country,canonical,easy,,benchmark
ccc0000000000003,typo_place,wikidataId/Q999,en,admin1,canonical,medium,"informal_alias,transliteration",curated-review
ddd0000000000004,no match row,,en,country,no_match,easy,,curated
"""


@pytest.fixture()
def tmp_csv(tmp_path: Path) -> Path:
    p = tmp_path / "test_eval.csv"
    p.write_text(_MINIMAL_CSV)
    return p


@pytest.fixture()
def tmp_parquet(tmp_path: Path) -> Path:
    return tmp_path / "test_eval.parquet"


def test_convert_returns_row_count(tmp_csv: Path, tmp_parquet: Path) -> None:
    n = convert(config=EvalConvertConfig(csv_path=tmp_csv, parquet_path=tmp_parquet))
    assert n == 4


def test_output_has_ten_columns(tmp_csv: Path, tmp_parquet: Path) -> None:
    convert(config=EvalConvertConfig(csv_path=tmp_csv, parquet_path=tmp_parquet))
    frame = pl.read_parquet(tmp_parquet)
    assert set(frame.columns) == _EXPECTED_COLUMNS


def test_text_mapped_to_query_column(tmp_csv: Path, tmp_parquet: Path) -> None:
    convert(config=EvalConvertConfig(csv_path=tmp_csv, parquet_path=tmp_parquet))
    frame = pl.read_parquet(tmp_parquet)
    queries = set(frame["query"].to_list())
    assert "France" in queries
    assert "Germany" in queries


def test_multi_id_row_yields_two_element_list(tmp_csv: Path, tmp_parquet: Path) -> None:
    convert(config=EvalConvertConfig(csv_path=tmp_csv, parquet_path=tmp_parquet))
    frame = pl.read_parquet(tmp_parquet)
    france_row = frame.filter(pl.col("query") == "France")
    assert len(france_row) == 1
    ids = france_row["expected_ids"][0]
    assert len(ids) == 2
    assert "country/FRA" in ids
    assert "wikidataId/Q142" in ids


def test_single_id_row_yields_one_element_list(
    tmp_csv: Path, tmp_parquet: Path
) -> None:
    convert(config=EvalConvertConfig(csv_path=tmp_csv, parquet_path=tmp_parquet))
    frame = pl.read_parquet(tmp_parquet)
    germany_row = frame.filter(pl.col("query") == "Germany")
    ids = germany_row["expected_ids"][0].to_list()
    assert ids == ["country/DEU"]


def test_empty_expected_ids_yields_empty_list(tmp_csv: Path, tmp_parquet: Path) -> None:
    convert(config=EvalConvertConfig(csv_path=tmp_csv, parquet_path=tmp_parquet))
    frame = pl.read_parquet(tmp_parquet)
    no_match_row = frame.filter(pl.col("query") == "no match row")
    assert len(no_match_row) == 1
    ids = no_match_row["expected_ids"][0].to_list()
    assert ids == []


def test_capabilities_parsed_as_list(tmp_csv: Path, tmp_parquet: Path) -> None:
    convert(config=EvalConvertConfig(csv_path=tmp_csv, parquet_path=tmp_parquet))
    frame = pl.read_parquet(tmp_parquet)
    typo_row = frame.filter(pl.col("query") == "typo_place")
    caps = typo_row["capabilities"][0]
    assert set(caps) == {"informal_alias", "transliteration"}


def test_empty_capabilities_yields_empty_list(tmp_csv: Path, tmp_parquet: Path) -> None:
    convert(config=EvalConvertConfig(csv_path=tmp_csv, parquet_path=tmp_parquet))
    frame = pl.read_parquet(tmp_parquet)
    germany_row = frame.filter(pl.col("query") == "Germany")
    caps = germany_row["capabilities"][0].to_list()
    assert caps == []


def test_notes_column_is_null(tmp_csv: Path, tmp_parquet: Path) -> None:
    convert(config=EvalConvertConfig(csv_path=tmp_csv, parquet_path=tmp_parquet))
    frame = pl.read_parquet(tmp_parquet)
    assert frame["notes"].is_null().all()


def test_rows_sorted_by_query_id(tmp_csv: Path, tmp_parquet: Path) -> None:
    convert(config=EvalConvertConfig(csv_path=tmp_csv, parquet_path=tmp_parquet))
    frame = pl.read_parquet(tmp_parquet)
    ids = frame["query_id"].to_list()
    assert ids == sorted(ids)


def test_determinism(tmp_csv: Path, tmp_path: Path) -> None:
    """Two runs on the same CSV produce byte-identical parquet files."""
    p1 = tmp_path / "out1.parquet"
    p2 = tmp_path / "out2.parquet"
    convert(config=EvalConvertConfig(csv_path=tmp_csv, parquet_path=p1))
    convert(config=EvalConvertConfig(csv_path=tmp_csv, parquet_path=p2))
    assert p1.read_bytes() == p2.read_bytes()
