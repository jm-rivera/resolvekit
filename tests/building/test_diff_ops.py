"""Unit tests for SQL diff helpers."""

from __future__ import annotations

import pytest

from resolvekit.builder.sqlite import (
    compute_table_diff,
    ensure_sqlite_schema,
    sample_keys,
    table_count,
)


def test_diff_helpers_reject_invalid_sql_identifiers(tmp_path) -> None:
    db_path = tmp_path / "diff.sqlite"
    ensure_sqlite_schema(db_path)

    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        table_count(db_path, "entities;DROP TABLE entities")

    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        sample_keys(db_path, "entities", ["entity_id;--"], limit=1)

    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        compute_table_diff(
            current_db=db_path,
            previous_db=None,
            table="entities",
            pk_cols=["entity_id"],
            compare_cols=["is preferred"],
            max_samples=5,
        )
