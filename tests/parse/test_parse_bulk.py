"""Tests for Resolver.parse_bulk() — ragged explode, row_idx tagging,
input kinds, and no cross-row deduplication.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from resolvekit.core.api.resolver import Resolver


# ---------------------------------------------------------------------------
# Ragged explode + exact column set
# ---------------------------------------------------------------------------


def test_parse_bulk_ragged_explode(parse_geo_resolver: Resolver) -> None:
    """Row 0 yields Kenya+Somalia; row 1 ('no entities here') yields zero entities."""
    result = parse_geo_resolver.parse_bulk(
        values=["Kenya and Somalia", "no entities here"]
    )

    row0_entities = [e for e in result if e.row_idx == 0]
    row1_entities = [e for e in result if e.row_idx == 1]

    surfaces0 = {e.surface for e in row0_entities}
    assert "Kenya" in surfaces0, f"Expected 'Kenya' in row 0, got: {surfaces0}"
    assert "Somalia" in surfaces0, f"Expected 'Somalia' in row 0, got: {surfaces0}"

    # Row 1 has no known entities.
    assert len(row1_entities) == 0, (
        f"Expected 0 entities in row 1, got: {[e.surface for e in row1_entities]}"
    )


def test_parse_bulk_to_dataframe_exact_columns(parse_geo_resolver: Resolver) -> None:
    """to_dataframe() yields the exact expected column set including row_idx."""
    pytest.importorskip("pandas")
    result = parse_geo_resolver.parse_bulk(
        values=["Kenya and Somalia", "no entities here"]
    )
    df = result.to_dataframe()
    expected = [
        "row_idx",
        "surface",
        "entity_id",
        "entity_type",
        "pack_id",
        "status",
        "confidence",
        "start",
        "end",
        "to",
    ]
    assert df.columns.tolist() == expected, (
        f"column mismatch:\n  expected: {expected}\n  got:      {df.columns.tolist()}"
    )


def test_parse_bulk_row_idx_tagged(parse_geo_resolver: Resolver) -> None:
    """Every entity carries its source row_idx."""
    result = parse_geo_resolver.parse_bulk(values=["Kenya", "Somalia"])
    for e in result:
        assert e.row_idx is not None, f"row_idx must be set for bulk entities: {e}"


# ---------------------------------------------------------------------------
# Input kinds
# ---------------------------------------------------------------------------


def test_parse_bulk_accepts_list(parse_geo_resolver: Resolver) -> None:
    """parse_bulk accepts a plain list."""
    result = parse_geo_resolver.parse_bulk(values=["Kenya", "Somalia"])
    assert len(result) >= 2


def test_parse_bulk_accepts_pandas_series(parse_geo_resolver: Resolver) -> None:
    """parse_bulk accepts a pandas Series (gated with importorskip)."""
    pd = pytest.importorskip("pandas")
    series = pd.Series(["Kenya", "Somalia"])
    result = parse_geo_resolver.parse_bulk(values=series)
    surfaces = {e.surface for e in result}
    assert "Kenya" in surfaces


def test_parse_bulk_nan_cell_no_crash(parse_geo_resolver: Resolver) -> None:
    """None/NaN cells contribute zero entities and do not crash."""
    pd = pytest.importorskip("pandas")

    series = pd.Series(["Kenya", None, float("nan"), "Somalia"])
    result = parse_geo_resolver.parse_bulk(values=series)

    # Rows 1 and 2 (None/NaN) must contribute zero entities.
    null_entities = [e for e in result if e.row_idx in (1, 2)]
    assert len(null_entities) == 0, (
        f"None/NaN rows should produce no entities, got: {null_entities}"
    )

    # Rows 0 and 3 must still work.
    surfaces = {e.surface for e in result}
    assert "Kenya" in surfaces
    assert "Somalia" in surfaces


def test_parse_bulk_none_list_cell_no_crash(parse_geo_resolver: Resolver) -> None:
    """None in a plain list contributes zero entities and does not crash."""
    result = parse_geo_resolver.parse_bulk(values=["Kenya", None, "Somalia"])
    null_entities = [e for e in result if e.row_idx == 1]
    assert len(null_entities) == 0
    surfaces = {e.surface for e in result}
    assert "Kenya" in surfaces


# ---------------------------------------------------------------------------
# No cross-row deduplication
# ---------------------------------------------------------------------------


def test_parse_bulk_no_cross_row_dedup(parse_geo_resolver: Resolver) -> None:
    """The same entity in two rows yields two ParsedEntity objects with distinct row_idx."""
    result = parse_geo_resolver.parse_bulk(values=["Kenya", "Kenya"])

    kenya_entities = [e for e in result if e.surface == "Kenya"]
    assert len(kenya_entities) == 2, (
        f"Expected 2 Kenya entities (no cross-row dedup), got {len(kenya_entities)}"
    )
    row_idxs = {e.row_idx for e in kenya_entities}
    assert row_idxs == {0, 1}, f"Expected row_idxs {{0, 1}}, got {row_idxs}"


# ---------------------------------------------------------------------------
# Closed resolver guard
# ---------------------------------------------------------------------------


def test_parse_bulk_closed_resolver_raises(parse_geo_datapack: Any) -> None:
    """Calling parse_bulk() on a closed resolver raises RuntimeError."""
    from resolvekit.core.api.resolver import Resolver

    r = Resolver.from_datapacks(datapack_paths=[parse_geo_datapack])
    r.close()
    with pytest.raises(RuntimeError, match="closed"):
        r.parse_bulk(values=["Kenya"])
