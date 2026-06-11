"""Unit tests for compute_containment_prominence.

Covers:
- Basic normalization: two-region bucket produces [0, 1] range.
- Per-bucket isolation: subregions and continental_unions are normalized
  separately and do not interfere with each other.
- Degenerate single-region bucket emits 0.5.
- Empty inputs return empty output.
- Ordering guarantee: a region with heavier/more members outranks one with
  fewer/lighter members.
- Missing country signal is silently ignored (non-country member IDs).
- Region absent from region_types is skipped.
"""

from __future__ import annotations

import pytest

from resolvekit.builder.sources.datacommons.geo.prominence import (
    compute_containment_prominence,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(
    region_members: dict[str, list[str]],
    country_prominence: dict[str, float],
    region_types: dict[str, str],
) -> dict[str, float]:
    return compute_containment_prominence(
        region_members=region_members,
        country_prominence=country_prominence,
        region_types=region_types,
    )


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_empty_region_members_returns_empty() -> None:
    result = _run(
        region_members={},
        country_prominence={"country/USA": 0.9},
        region_types={},
    )
    assert result == {}


@pytest.mark.unit
def test_empty_country_prominence_returns_zero_scores_normalized() -> None:
    """Regions with no country coverage get raw score 0.0.

    A bucket of two regions both scoring 0.0 has lo == hi → denom rounds to
    1e-9 → both get clipped to 0.0.  The degenerate single-region case emits
    0.5.
    """
    result = _run(
        region_members={"r/A": ["country/X", "country/Y"], "r/B": ["country/Z"]},
        country_prominence={},  # no country has prominence
        region_types={"r/A": "geo.subregion", "r/B": "geo.subregion"},
    )
    # Both have raw score 0; min-max normalization over identical values → 0.0.
    assert set(result.keys()) == {"r/A", "r/B"}
    for v in result.values():
        assert 0.0 <= v <= 1.0


# ---------------------------------------------------------------------------
# Basic normalization
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_two_regions_span_full_range() -> None:
    """With two regions in the same bucket, scores are exactly 0.0 and 1.0."""
    result = _run(
        region_members={
            "r/heavy": ["country/A", "country/B"],
            "r/light": ["country/C"],
        },
        country_prominence={"country/A": 0.8, "country/B": 0.6, "country/C": 0.2},
        region_types={"r/heavy": "geo.subregion", "r/light": "geo.subregion"},
    )
    # r/heavy raw = 0.8 + 0.6 = 1.4  (max)
    # r/light raw = 0.2              (min)
    assert result["r/heavy"] == pytest.approx(1.0)
    assert result["r/light"] == pytest.approx(0.0)


@pytest.mark.unit
def test_heavier_region_ranks_higher() -> None:
    """A region with more/heavier members must have a higher prominence than one
    with fewer/lighter members."""
    result = _run(
        region_members={
            "r/big": ["country/A", "country/B", "country/C"],
            "r/small": ["country/D"],
        },
        country_prominence={
            "country/A": 0.9,
            "country/B": 0.8,
            "country/C": 0.7,
            "country/D": 0.5,
        },
        region_types={"r/big": "geo.subregion", "r/small": "geo.subregion"},
    )
    assert result["r/big"] > result["r/small"]


@pytest.mark.unit
def test_output_clipped_to_unit_interval() -> None:
    """All prominence values must be in [0, 1]."""
    result = _run(
        region_members={
            "r/A": ["c/1", "c/2", "c/3"],
            "r/B": ["c/4"],
            "r/C": ["c/5", "c/6"],
        },
        country_prominence={
            "c/1": 1.0,
            "c/2": 0.9,
            "c/3": 0.8,
            "c/4": 0.1,
            "c/5": 0.5,
            "c/6": 0.5,
        },
        region_types={
            "r/A": "geo.subregion",
            "r/B": "geo.subregion",
            "r/C": "geo.subregion",
        },
    )
    for v in result.values():
        assert 0.0 <= v <= 1.0


# ---------------------------------------------------------------------------
# Degenerate bucket
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_single_region_bucket_emits_half() -> None:
    """A single-entity bucket must produce exactly 0.5 (no-op centering point)."""
    result = _run(
        region_members={"r/only": ["country/A"]},
        country_prominence={"country/A": 0.75},
        region_types={"r/only": "geo.continental_union"},
    )
    assert result == {"r/only": pytest.approx(0.5)}


# ---------------------------------------------------------------------------
# Per-bucket isolation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_per_bucket_normalization_is_independent() -> None:
    """geo.subregion and geo.continental_union buckets are normalized separately.

    A continental union with a very high raw score must not push subregion
    scores down, and vice versa.  Each bucket spans exactly [0, 1].
    """
    result = _run(
        region_members={
            "sub/A": ["c/1", "c/2"],  # raw = 1.8 (subregion bucket)
            "sub/B": ["c/3"],  # raw = 0.2 (subregion bucket)
            "union/EU": ["c/4", "c/5", "c/6"],  # raw = 2.7 (union bucket)
            "union/AU": ["c/7"],  # raw = 0.1 (union bucket)
        },
        country_prominence={
            "c/1": 0.9,
            "c/2": 0.9,
            "c/3": 0.2,
            "c/4": 0.9,
            "c/5": 0.9,
            "c/6": 0.9,
            "c/7": 0.1,
        },
        region_types={
            "sub/A": "geo.subregion",
            "sub/B": "geo.subregion",
            "union/EU": "geo.continental_union",
            "union/AU": "geo.continental_union",
        },
    )
    # Each bucket independently spans [0, 1].
    assert result["sub/A"] == pytest.approx(1.0)
    assert result["sub/B"] == pytest.approx(0.0)
    assert result["union/EU"] == pytest.approx(1.0)
    assert result["union/AU"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Unknown / missing member IDs
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_non_country_member_ids_are_ignored() -> None:
    """Member IDs absent from country_prominence do not raise errors."""
    result = _run(
        region_members={
            "r/A": ["country/X", "sub/nested_sub", "country/Y"],
        },
        country_prominence={"country/X": 0.6, "country/Y": 0.4},
        region_types={"r/A": "geo.subregion"},
    )
    # Only X and Y contribute; sub/nested_sub is ignored.
    # Single-region bucket → 0.5.
    assert result == {"r/A": pytest.approx(0.5)}


@pytest.mark.unit
def test_region_absent_from_region_types_is_skipped() -> None:
    """Regions not in region_types are silently excluded from output."""
    result = _run(
        region_members={
            "r/known": ["country/A"],
            "r/unknown": ["country/B"],  # not in region_types
        },
        country_prominence={"country/A": 0.8, "country/B": 0.9},
        region_types={"r/known": "geo.subregion"},
    )
    assert "r/unknown" not in result
    assert "r/known" in result


# ---------------------------------------------------------------------------
# Realistic scenario: Sub-Saharan Africa (indirect membership)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_indirect_country_membership_via_transitive_resolution() -> None:
    """Simulate Sub-Saharan Africa whose direct members are leaf subregions.

    The caller (enrich_prominence._load_region_members) must resolve the
    transitive country list before calling compute_containment_prominence.
    This test confirms the function handles the pre-resolved list correctly
    and that a region with transitive members outranks one with fewer.
    """
    # Sub-Saharan Africa: its members are already resolved to countries by the
    # caller (Eastern Africa + Western Africa + ... → ~55 countries).
    # We simulate with 3 proxy countries.
    result = _run(
        region_members={
            "m49/202": ["country/KEN", "country/NGA", "country/ZAF"],  # Sub-Saharan (3)
            "m49/015": ["country/EGY"],  # Northern Africa (1)
        },
        country_prominence={
            "country/KEN": 0.6,
            "country/NGA": 0.9,
            "country/ZAF": 0.7,
            "country/EGY": 0.8,
        },
        region_types={"m49/202": "geo.subregion", "m49/015": "geo.subregion"},
    )
    # m49/202 raw = 0.6+0.9+0.7 = 2.2 (max → 1.0)
    # m49/015 raw = 0.8           (min → 0.0)
    assert result["m49/202"] == pytest.approx(1.0)
    assert result["m49/015"] == pytest.approx(0.0)
