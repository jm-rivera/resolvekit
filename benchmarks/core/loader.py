"""Benchmark dataset loader.

Reads committed Parquet files and returns `list[Query]`. The Parquet column
is still named `query`; the dataclass field is `text` (kills `query.query` stutter).
`expected_ids` semantics:
  - Empty tuple      → the tool SHOULD abstain (no_match).
  - Single element   → unambiguous match.
  - Multiple elements → ambiguous; any intersection with match_ids counts.
"""

from __future__ import annotations

from pathlib import Path

from benchmarks.build.spec import DATASET_NAMES
from benchmarks.core.kernel import Query

_DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"


def load_dataset(
    name: str,
    *,
    data_dir: Path | None = None,
) -> list[Query]:
    """Load a committed Parquet benchmark dataset into Query records."""
    import polars as pl

    if name not in DATASET_NAMES:
        raise ValueError(f"Unknown dataset {name!r}; expected one of {DATASET_NAMES}")

    directory = data_dir if data_dir is not None else _DEFAULT_DATA_DIR
    path = directory / f"{name}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"Benchmark dataset {name!r} not found at {path}. "
            "Run `uv run python -m benchmarks.build` to build it."
        )

    frame = pl.read_parquet(path)
    expected_columns = {
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
    missing = expected_columns - set(frame.columns)
    if missing:
        raise ValueError(f"Parquet file {path} missing columns: {sorted(missing)}")
    # extra columns (e.g. expected_spans on eval_parse) are silently ignored here;
    # the dedicated benchmarks/parse/loader reads them.

    return [
        Query(
            query_id=str(record["query_id"]),
            text=str(record["query"]),
            expected_ids=tuple(record["expected_ids"] or ()),
            language=str(record["language"]),
            entity_type=str(record["entity_type"]),
            category=str(record["category"]),
            difficulty=str(record["difficulty"]),
            capabilities=tuple(record["capabilities"] or ()),
            source=str(record["source"]),
            notes=None if record["notes"] is None else str(record["notes"]),
        )
        for record in frame.iter_rows(named=True)
    ]
