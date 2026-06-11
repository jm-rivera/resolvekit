"""Convert eval CSV files to their canonical Parquet forms.

The CSV files (9 columns) are the human-editable sources of truth. This script:
  - Maps ``text`` column to ``query`` column
  - Splits comma-joined ``expected_ids`` and ``capabilities`` into lists
  - Defaults ``notes`` to None
  - Sorts by ``query_id`` for determinism
  - Writes 10-column canonical schema

When the source CSV carries an optional ``expected_spans`` column (used by
eval_parse), the column is passed through as a ``pl.Utf8`` JSON string and
each span's ``text[start:end] == surface`` invariant is asserted before write.
The column is absent from the standard 10-column schema but silently tolerated
by ``benchmarks/core/loader.py``; it is read by the dedicated
``benchmarks/parse/loader.py`` instead.

Converts:
  - benchmarks/data/eval_geo.csv    → benchmarks/data/eval_geo.parquet
  - benchmarks/data/eval_org.csv    → benchmarks/data/eval_org.parquet
  - benchmarks/data/eval_parse.csv  → benchmarks/data/eval_parse.parquet

Run: uv run python -m scripts.data_maintenance.convert_eval_csv
"""

from __future__ import annotations

import csv
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_DIR = _REPO_ROOT / "benchmarks" / "data"


@dataclass(frozen=True, slots=True, kw_only=True)
class EvalConvertConfig:
    csv_path: Path = field(default_factory=lambda: _DATA_DIR / "eval_geo.csv")
    parquet_path: Path = field(default_factory=lambda: _DATA_DIR / "eval_geo.parquet")


def _validate_expected_spans(rows: list[dict[str, str]]) -> None:
    """Assert each span's text[start:end] == surface for all rows with expected_spans.

    Raises ValueError on the first mismatch, naming the query_id and span index.
    """
    for row in rows:
        raw = row.get("expected_spans", "").strip()
        if not raw:
            continue
        text = row["text"]
        query_id = row["query_id"]
        try:
            spans = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Row {query_id!r}: expected_spans is not valid JSON: {raw!r}"
            ) from exc
        for i, span in enumerate(spans):
            start = span["start"]
            end = span["end"]
            actual = text[start:end]
            # When the span carries an explicit 'surface' field, validate it;
            # when absent (spans authored without it), just assert offsets are in range.
            if "surface" in span:
                surface = span["surface"]
                if actual != surface:
                    raise ValueError(
                        f"Row {query_id!r} span[{i}]: text[{start}:{end}]={actual!r} "
                        f"!= surface={surface!r}"
                    )
            elif not (0 <= start <= end <= len(text)):
                raise ValueError(
                    f"Row {query_id!r} span[{i}]: offsets [{start}:{end}] out of range "
                    f"for text of length {len(text)}"
                )


def convert(*, config: EvalConvertConfig) -> int:
    """Read an eval CSV and write the canonical Parquet.

    For standard eval files the output has 10 columns. For eval_parse (which
    carries an ``expected_spans`` column in its CSV) the output has 11 columns —
    the same 10 plus ``expected_spans`` as a ``pl.Utf8`` JSON string.

    Returns the row count written.
    """
    with open(config.csv_path, newline="") as fh:
        reader = csv.DictReader(fh)
        raw_rows = list(reader)

    rows = sorted(raw_rows, key=lambda r: r["query_id"])

    # Detect whether this is a parse-eval CSV (carries expected_spans).
    has_spans = bool(rows) and "expected_spans" in rows[0]
    if has_spans:
        _validate_expected_spans(rows)

    def _split(f: str) -> list[str]:
        return [s for s in f.split(",") if s] if f else []

    data: dict[str, object] = {
        "query_id": [r["query_id"] for r in rows],
        "query": [r["text"] for r in rows],
        "expected_ids": [_split(r["expected_ids"]) for r in rows],
        "language": [r["language"] for r in rows],
        "entity_type": [r["entity_type"] for r in rows],
        "category": [r.get("category", "") for r in rows],
        "difficulty": [r["difficulty"] for r in rows],
        "capabilities": [_split(r.get("capabilities", "")) for r in rows],
        "source": [r["source"] for r in rows],
        "notes": [None for _ in rows],
    }
    schema = {
        "query_id": pl.Utf8,
        "query": pl.Utf8,
        "expected_ids": pl.List(pl.Utf8),
        "language": pl.Utf8,
        "entity_type": pl.Utf8,
        "category": pl.Utf8,
        "difficulty": pl.Utf8,
        "capabilities": pl.List(pl.Utf8),
        "source": pl.Utf8,
        "notes": pl.Utf8,
    }

    if has_spans:
        # Pass the JSON string through verbatim; validation already ran above.
        data["expected_spans"] = [r.get("expected_spans", "[]") for r in rows]
        schema["expected_spans"] = pl.Utf8

    frame = pl.DataFrame(data, schema=schema)

    config.parquet_path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(config.parquet_path, compression="zstd")
    row_count = len(frame)
    logger.info("wrote %d rows to %s", row_count, config.parquet_path)
    return row_count


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(
            "convert_eval_csv.py takes no CLI arguments. Configure it by "
            "editing EvalConvertConfig(...) in this block."
        )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    pairs = [
        (_DATA_DIR / "eval_geo.csv", _DATA_DIR / "eval_geo.parquet"),
        (_DATA_DIR / "eval_org.csv", _DATA_DIR / "eval_org.parquet"),
        (_DATA_DIR / "eval_parse.csv", _DATA_DIR / "eval_parse.parquet"),
    ]
    total = 0
    for csv_path, parquet_path in pairs:
        if not csv_path.exists():
            logger.info("skipping missing source: %s", csv_path.name)
            continue
        n = convert(
            config=EvalConvertConfig(csv_path=csv_path, parquet_path=parquet_path)
        )
        print(f"converted {n} rows: {csv_path.name} → {parquet_path.name}")
        total += n
    print(f"total: {total} rows across {len(pairs)} files")
