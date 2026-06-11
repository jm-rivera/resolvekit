"""Tests for the parse eval dataset: loader, convert round-trip, and engine exclusion.

Covers:
- convert() round-trip: CSV with expected_spans → Parquet → ParseEvalRow
- load_parse_dataset() returns expected rows with decoded GoldSpan tuples
- set(DATASET_SPECS) == set(DATASET_NAMES) invariant for eval_parse
- eval_parse has eval=True flag in DATASET_SPECS
- _load_datasets(None, ...) excludes eval_parse (default run)
- _load_datasets(["eval_parse"], ...) includes eval_parse (explicit)
- convert() raises ValueError on span surface mismatch
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import polars as pl
import pytest

from benchmarks.parse.loader import GoldSpan, ParseEvalRow, load_parse_dataset
from scripts.data_maintenance.convert_eval_csv import EvalConvertConfig, convert

# ---------------------------------------------------------------------------
# Helpers for writing fixture CSVs with correct JSON-in-CSV quoting.
# csv.writer doubles interior quotes; csv.DictReader undoes that on read.
# ---------------------------------------------------------------------------

_HEADER = [
    "query_id",
    "text",
    "expected_ids",
    "language",
    "entity_type",
    "category",
    "difficulty",
    "capabilities",
    "source",
    "expected_spans",
]


def _write_fixture_csv(path: Path, rows: list[list[str]]) -> None:
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    writer.writerow(_HEADER)
    for row in rows:
        writer.writerow(row)
    path.write_text(buf.getvalue(), encoding="utf-8")


def _spans_json(*spans: dict) -> str:
    return json.dumps(list(spans))


_FIXTURE_ROWS: list[list[str]] = [
    [
        "parse0000000000001",
        "Kenya and Somalia",
        "",
        "en",
        "country",
        "parse_adversarial",
        "medium",
        "case_channel",
        "fixture",
        _spans_json(
            {
                "start": 0,
                "end": 5,
                "surface": "Kenya",
                "expected_id": "country/KEN",
                "entity_type": "country",
            },
            {
                "start": 10,
                "end": 17,
                "surface": "Somalia",
                "expected_id": "country/SOM",
                "entity_type": "country",
            },
        ),
    ],
    [
        "parse0000000000002",
        "chad",
        "",
        "en",
        "country",
        "recall_floor",
        "easy",
        "lowercase_canonical",
        "fixture",
        _spans_json(
            {
                "start": 0,
                "end": 4,
                "surface": "chad",
                "expected_id": "country/TCD",
                "entity_type": "country",
            }
        ),
    ],
    [
        "parse0000000000003",
        "No entities here",
        "",
        "en",
        "country",
        "nil_canary",
        "easy",
        "",
        "fixture",
        "[]",
    ],
]


@pytest.fixture()
def fixture_csv(tmp_path: Path) -> Path:
    p = tmp_path / "eval_parse.csv"
    _write_fixture_csv(p, _FIXTURE_ROWS)
    return p


@pytest.fixture()
def fixture_parquet(tmp_path: Path) -> Path:
    return tmp_path / "eval_parse.parquet"


@pytest.fixture()
def converted_parquet(fixture_csv: Path, fixture_parquet: Path) -> Path:
    """Run convert() once and return the output path."""
    convert(
        config=EvalConvertConfig(csv_path=fixture_csv, parquet_path=fixture_parquet)
    )
    return fixture_parquet


# ---------------------------------------------------------------------------
# convert() — round-trip basics
# ---------------------------------------------------------------------------


def test_convert_returns_row_count(fixture_csv: Path, fixture_parquet: Path) -> None:
    n = convert(
        config=EvalConvertConfig(csv_path=fixture_csv, parquet_path=fixture_parquet)
    )
    assert n == 3


def test_converted_parquet_has_expected_spans_column(converted_parquet: Path) -> None:
    frame = pl.read_parquet(converted_parquet)
    assert "expected_spans" in frame.columns


def test_converted_parquet_has_standard_columns(converted_parquet: Path) -> None:
    frame = pl.read_parquet(converted_parquet)
    standard = {
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
    assert standard.issubset(set(frame.columns))


def test_convert_raises_on_surface_mismatch(tmp_path: Path) -> None:
    """convert() must raise ValueError when text[start:end] != surface."""
    bad_csv = tmp_path / "bad.csv"
    # text = "Hello world", span says surface="World" but text[0:3]=="Hel"
    _write_fixture_csv(
        bad_csv,
        [
            [
                "bad000000000000001",
                "Hello world",
                "",
                "en",
                "country",
                "parse_adversarial",
                "easy",
                "",
                "fixture",
                _spans_json(
                    {
                        "start": 0,
                        "end": 3,
                        "surface": "World",
                        "expected_id": "country/WLD",
                        "entity_type": "country",
                    }
                ),
            ]
        ],
    )
    bad_parquet = tmp_path / "bad.parquet"
    with pytest.raises(ValueError, match="surface"):
        convert(config=EvalConvertConfig(csv_path=bad_csv, parquet_path=bad_parquet))


def test_convert_nil_row_gets_empty_spans(converted_parquet: Path) -> None:
    frame = pl.read_parquet(converted_parquet)
    nil_row = frame.filter(pl.col("query_id") == "parse0000000000003")
    assert len(nil_row) == 1
    raw = nil_row["expected_spans"][0]
    assert json.loads(raw) == []


# ---------------------------------------------------------------------------
# load_parse_dataset() — decoding
# ---------------------------------------------------------------------------


def test_load_parse_dataset_returns_list(converted_parquet: Path) -> None:
    rows = load_parse_dataset(data_dir=converted_parquet.parent)
    assert isinstance(rows, list)
    assert len(rows) == 3


def test_load_parse_dataset_row_types(converted_parquet: Path) -> None:
    rows = load_parse_dataset(data_dir=converted_parquet.parent)
    for row in rows:
        assert isinstance(row, ParseEvalRow)


def test_load_parse_dataset_preserves_spans(converted_parquet: Path) -> None:
    """Kenya-and-Somalia row must decode to two GoldSpan entries with correct offsets."""
    rows = load_parse_dataset(data_dir=converted_parquet.parent)
    kenya_row = next(r for r in rows if r.row_id == "parse0000000000001")

    assert len(kenya_row.gold_spans) == 2

    kenya_span = kenya_row.gold_spans[0]
    assert isinstance(kenya_span, GoldSpan)
    assert kenya_span.start == 0
    assert kenya_span.end == 5
    assert kenya_span.expected_id == "country/KEN"
    assert kenya_span.entity_type == "country"
    # Offset round-trip: text[start:end] must equal "Kenya"
    assert kenya_row.text[kenya_span.start : kenya_span.end] == "Kenya"

    somalia_span = kenya_row.gold_spans[1]
    assert somalia_span.start == 10
    assert somalia_span.end == 17
    assert somalia_span.expected_id == "country/SOM"
    assert kenya_row.text[somalia_span.start : somalia_span.end] == "Somalia"


def test_load_parse_dataset_nil_row_empty_spans(converted_parquet: Path) -> None:
    rows = load_parse_dataset(data_dir=converted_parquet.parent)
    nil_row = next(r for r in rows if r.row_id == "parse0000000000003")
    assert nil_row.gold_spans == ()


def test_load_parse_dataset_expected_id_none_for_nil(tmp_path: Path) -> None:
    """A span with null expected_id decodes to GoldSpan(expected_id=None)."""
    nil_span_csv = tmp_path / "eval_parse.csv"
    _write_fixture_csv(
        nil_span_csv,
        [
            [
                "nil000000000000001",
                "Mystery town",
                "",
                "en",
                "country",
                "nil_canary",
                "easy",
                "",
                "fixture",
                _spans_json(
                    {
                        "start": 0,
                        "end": 7,
                        "surface": "Mystery",
                        "expected_id": None,
                        "entity_type": "country",
                    }
                ),
            ]
        ],
    )
    nil_parquet = tmp_path / "eval_parse.parquet"
    convert(config=EvalConvertConfig(csv_path=nil_span_csv, parquet_path=nil_parquet))
    rows = load_parse_dataset(data_dir=tmp_path)
    assert len(rows) == 1
    span = rows[0].gold_spans[0]
    assert span.expected_id is None
    assert span.start == 0
    assert span.end == 7


def test_load_parse_dataset_raises_for_missing_parquet(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_parse_dataset(data_dir=tmp_path)


def test_load_parse_dataset_raises_for_unknown_name() -> None:
    with pytest.raises(ValueError, match="Unknown dataset"):
        load_parse_dataset(name="nonexistent_parse_set")


# ---------------------------------------------------------------------------
# Registry invariant: DATASET_SPECS == DATASET_NAMES (includes eval_parse)
# ---------------------------------------------------------------------------


def test_dataset_specs_equals_dataset_names_with_eval_parse() -> None:
    """set(DATASET_SPECS) == set(DATASET_NAMES) must hold after eval_parse addition."""
    from benchmarks.build import DATASET_SPECS
    from benchmarks.build.spec import DATASET_NAMES

    assert set(DATASET_SPECS) == set(DATASET_NAMES), (
        f"DATASET_SPECS keys {sorted(DATASET_SPECS)} do not match "
        f"DATASET_NAMES {sorted(DATASET_NAMES)}"
    )


def test_eval_parse_in_dataset_names() -> None:
    from benchmarks.build.spec import DATASET_NAMES

    assert "eval_parse" in DATASET_NAMES


def test_eval_parse_spec_has_eval_flag() -> None:
    from benchmarks.build import DATASET_SPECS

    spec = DATASET_SPECS["eval_parse"]
    assert spec.eval is True


def test_eval_parse_spec_has_no_build_fn() -> None:
    """eval_parse is a committed eval set; it has no builder function."""
    from benchmarks.build import DATASET_SPECS

    spec = DATASET_SPECS["eval_parse"]
    assert spec.build_fn is None


# ---------------------------------------------------------------------------
# Engine exclusion: default run excludes eval_parse; explicit includes it
# ---------------------------------------------------------------------------


def test_load_datasets_default_excludes_eval_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_load_datasets(None, ...) must not include eval_parse."""
    from benchmarks.core import engine as eng

    # Return [] for any name so no real parquet is needed.
    monkeypatch.setattr(eng, "load_dataset", lambda name, data_dir=None: [])

    result = eng._load_datasets(None, data_dir=tmp_path)
    assert "eval_parse" not in result, (
        "eval_parse must be excluded from the default benchmark run to prevent "
        "a bogus 0%-accuracy row"
    )


def test_load_datasets_explicit_includes_eval_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    converted_parquet: Path,
) -> None:
    """_load_datasets(['eval_parse'], ...) must include eval_parse."""
    from benchmarks.core import engine as eng

    # Provide the fixture parquet in data_dir; skip hash computation.
    data_dir = converted_parquet.parent
    monkeypatch.setattr(eng, "_sha256_file", lambda p: "deadbeef")

    result = eng._load_datasets(["eval_parse"], data_dir=data_dir)
    assert "eval_parse" in result
