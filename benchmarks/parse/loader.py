"""Loader for the parse evaluation gold set.

Reads ``benchmarks/data/eval_parse.parquet`` (produced by
``scripts/data_maintenance/convert_eval_csv.py``) and decodes the
JSON-encoded ``expected_spans`` column into typed Python dataclasses.

Public surface:

    GoldSpan(start, end, expected_id, entity_type)
        Immutable, slotted.  ``expected_id`` is None for NIL canary spans.

    ParseEvalRow(row_id, text, language, gold_spans)
        One document from the gold set.

    load_parse_dataset(name="eval_parse", *, data_dir=None) -> list[ParseEvalRow]
        Load and decode the Parquet.  Raises FileNotFoundError when the
        Parquet has not yet been generated from the CSV.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from benchmarks.build.spec import DATASET_NAMES


class _SpanDict(TypedDict):
    start: int
    end: int
    surface: str
    expected_id: str | None
    entity_type: str


_DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"


@dataclass(frozen=True, slots=True)
class GoldSpan:
    """A single gold span within a ParseEvalRow document.

    Attributes:
        start:       byte/char offset of the span start (inclusive) in the row text.
        end:         byte/char offset of the span end (exclusive) in the row text.
        expected_id: the canonical entity id the mention should resolve to, or
                     ``None`` for NIL canary spans (the parser should NOT link them).
        entity_type: the entity type of the expected entity (e.g. ``"country"``).
    """

    start: int
    end: int
    expected_id: str | None
    entity_type: str


@dataclass(frozen=True, slots=True)
class ParseEvalRow:
    """One document from the parse evaluation gold set.

    Attributes:
        row_id:     the ``query_id`` from the source CSV.
        text:       the raw document text.
        language:   BCP-47 language tag (e.g. ``"en"``).
        gold_spans: tuple of :class:`GoldSpan` sorted by start offset.
    """

    row_id: str
    text: str
    language: str
    gold_spans: tuple[GoldSpan, ...]


def _decode_spans(raw: str) -> tuple[GoldSpan, ...]:
    """Decode a JSON-encoded expected_spans string into a tuple of GoldSpan.

    The JSON schema for each element is:
        {"start": int, "end": int, "expected_id": str|null, "entity_type": str}

    The ``surface`` key is present in the CSV/Parquet for validation purposes but
    is not stored in GoldSpan (recoverable from ``text[start:end]`` at call time).
    """
    spans_data: list[_SpanDict] = json.loads(raw) if raw.strip() else []
    return tuple(
        GoldSpan(
            start=s["start"],
            end=s["end"],
            expected_id=s["expected_id"] or None,
            entity_type=s["entity_type"],
        )
        for s in spans_data
    )


def load_parse_dataset(
    name: str = "eval_parse",
    *,
    data_dir: Path | None = None,
) -> list[ParseEvalRow]:
    """Load the parse evaluation gold set from Parquet.

    Args:
        name:     dataset name; must be ``"eval_parse"`` (or another registered
                  parse eval dataset in the future).
        data_dir: override the default ``benchmarks/data/`` directory, e.g. for
                  tests that use a fixture directory.

    Returns:
        A list of :class:`ParseEvalRow` objects, one per document in the gold set.

    Raises:
        ValueError: if ``name`` is not a known dataset.
        FileNotFoundError: if the Parquet file has not been generated yet.
        ValueError: if the Parquet is missing the ``expected_spans`` column.
    """
    import polars as pl

    if name not in DATASET_NAMES:
        raise ValueError(f"Unknown dataset {name!r}; expected one of {DATASET_NAMES}")

    directory = data_dir if data_dir is not None else _DEFAULT_DATA_DIR
    path = directory / f"{name}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"Parse eval dataset {name!r} not found at {path}. "
            "Run `uv run python -m scripts.data_maintenance.convert_eval_csv` "
            "to generate it from the source CSV."
        )

    frame = pl.read_parquet(path)

    required = {"query_id", "query", "language", "expected_spans"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(
            f"Parquet {path} missing columns required by load_parse_dataset: "
            f"{sorted(missing)}"
        )

    rows: list[ParseEvalRow] = []
    for record in frame.iter_rows(named=True):
        raw_spans = record.get("expected_spans") or "[]"
        rows.append(
            ParseEvalRow(
                row_id=str(record["query_id"]),
                text=str(record["query"]),
                language=str(record["language"]),
                gold_spans=_decode_spans(str(raw_spans)),
            )
        )
    return rows
