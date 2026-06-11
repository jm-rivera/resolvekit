"""Unit tests for benchmarks.parse.metrics.span_metrics.

Covers:
- Exact match (1 TP)
- Boundary off-by-one (FP + FN; not boundary-exact)
- Missing prediction (FN)
- Spurious prediction (FP)
- NIL gold span correctly unlinked (nil_correct)
- NIL gold span wrongly linked (FP)
- Empty input edge (0/0 → P=R=F1=0.0, not NaN)
- NIL raw counts (nil_correct/nil_total) stored per row
- aggregate_results NIL micro-average vs macro-average
"""

from __future__ import annotations

import pytest

from benchmarks.parse.loader import GoldSpan
from benchmarks.parse.metrics import PredSpan, aggregate_results, span_metrics

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gold(start: int, end: int, eid: str | None = "country/KEN") -> GoldSpan:
    return GoldSpan(start=start, end=end, expected_id=eid, entity_type="country")


def _pred(start: int, end: int, eid: str | None = "country/KEN") -> PredSpan:
    return PredSpan(start=start, end=end, entity_id=eid, entity_type="country")


# ---------------------------------------------------------------------------
# Exact match (1 TP)
# ---------------------------------------------------------------------------


def test_exact_match_one_tp():
    g = [_gold(0, 5)]
    p = [_pred(0, 5)]
    r = span_metrics(predictions=p, gold=g)

    assert r.true_positives == 1
    assert r.false_positives == 0
    assert r.false_negatives == 0
    assert r.precision == pytest.approx(1.0)
    assert r.recall == pytest.approx(1.0)
    assert r.f1 == pytest.approx(1.0)
    assert r.boundary_exact_rate == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Boundary off-by-one: correct entity_id but shifted offsets
# ---------------------------------------------------------------------------


def test_boundary_off_by_one_is_fp_and_fn():
    """A prediction with the right entity_id but non-overlapping offsets is FP+FN."""
    g = [_gold(0, 5)]  # "Kenya"
    p = [_pred(1, 6)]  # slightly shifted — overlaps with [0,5), so it IS a TP
    # The spans DO overlap (1 < 5 and 0 < 6), so this should be TP but not boundary-exact.
    r = span_metrics(predictions=p, gold=g)

    assert r.true_positives == 1
    assert r.false_positives == 0
    assert r.false_negatives == 0
    # Offsets differ → not boundary-exact.
    assert r.boundary_exact_rate == pytest.approx(0.0)


def test_boundary_no_overlap_is_fp_and_fn():
    """A prediction with the right entity_id but no overlap is FP+FN."""
    g = [_gold(0, 5)]  # "Kenya"
    p = [_pred(10, 15)]  # no overlap at all
    r = span_metrics(predictions=p, gold=g)

    assert r.true_positives == 0
    assert r.false_positives == 1
    assert r.false_negatives == 1
    assert r.precision == pytest.approx(0.0)
    assert r.recall == pytest.approx(0.0)
    assert r.f1 == pytest.approx(0.0)
    assert r.boundary_exact_rate == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Missing prediction (FN)
# ---------------------------------------------------------------------------


def test_missing_prediction_is_fn():
    g = [_gold(0, 5)]
    p: list[PredSpan] = []
    r = span_metrics(predictions=p, gold=g)

    assert r.true_positives == 0
    assert r.false_positives == 0
    assert r.false_negatives == 1
    assert r.precision == pytest.approx(0.0)
    assert r.recall == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Spurious prediction (FP)
# ---------------------------------------------------------------------------


def test_spurious_prediction_is_fp():
    g: list[GoldSpan] = []
    p = [_pred(0, 5)]
    r = span_metrics(predictions=p, gold=g)

    assert r.true_positives == 0
    assert r.false_positives == 1
    assert r.false_negatives == 0
    assert r.precision == pytest.approx(0.0)
    # recall = TP / (TP+FN) = 0/0 → 0.0 (empty-input convention)
    assert r.recall == pytest.approx(0.0)


def test_spurious_and_missing():
    """One gold span not predicted (FN), one spurious prediction (FP)."""
    g = [_gold(0, 5, eid="country/KEN")]
    p = [_pred(0, 5, eid="country/NGA")]  # wrong entity
    r = span_metrics(predictions=p, gold=g)

    assert r.true_positives == 0
    assert r.false_positives == 1
    assert r.false_negatives == 1


# ---------------------------------------------------------------------------
# NIL gold span correctly unlinked
# ---------------------------------------------------------------------------


def test_nil_gold_correctly_unlinked():
    """A NIL gold span with no overlapping prediction → nil_correct_rate=1.0."""
    g = [_gold(10, 20, eid=None)]  # NIL span
    p: list[PredSpan] = []
    r = span_metrics(predictions=p, gold=g)

    assert r.true_positives == 0
    assert r.false_positives == 0
    assert r.false_negatives == 0
    assert r.nil_correct_rate == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# NIL gold span wrongly linked (FP)
# ---------------------------------------------------------------------------


def test_nil_gold_wrongly_linked_is_fp():
    """A prediction overlapping a NIL gold span is an FP."""
    g = [_gold(0, 10, eid=None)]  # NIL span
    p = [_pred(0, 10, eid="country/NGA")]  # links the NIL region
    r = span_metrics(predictions=p, gold=g)

    assert r.true_positives == 0
    assert r.false_positives == 1
    assert r.nil_correct_rate == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Empty input edge
# ---------------------------------------------------------------------------


def test_empty_input_returns_zeros_not_nan():
    """With no predictions and no gold, P=R=F1=0.0 (not NaN)."""
    r = span_metrics(predictions=[], gold=[])

    assert r.precision == pytest.approx(0.0)
    assert r.recall == pytest.approx(0.0)
    assert r.f1 == pytest.approx(0.0)
    assert r.boundary_exact_rate == pytest.approx(0.0)
    assert r.nil_correct_rate == pytest.approx(1.0)
    assert r.true_positives == 0
    assert r.false_positives == 0
    assert r.false_negatives == 0

    # Explicitly confirm no NaNs.
    import math

    assert not math.isnan(r.precision)
    assert not math.isnan(r.recall)
    assert not math.isnan(r.f1)


# ---------------------------------------------------------------------------
# Multi-span document
# ---------------------------------------------------------------------------


def test_multi_span_partial_match():
    """2 gold spans; 1 correct + 1 missed → precision=1.0, recall=0.5, f1=0.667."""
    g = [_gold(0, 5, "country/KEN"), _gold(10, 15, "country/NGA")]
    p = [_pred(0, 5, "country/KEN")]  # only Kenya predicted
    r = span_metrics(predictions=p, gold=g)

    assert r.true_positives == 1
    assert r.false_positives == 0
    assert r.false_negatives == 1
    assert r.precision == pytest.approx(1.0)
    assert r.recall == pytest.approx(0.5)
    assert r.f1 == pytest.approx(2 * 1.0 * 0.5 / (1.0 + 0.5))


def test_boundary_exact_rate_only_for_matched():
    """boundary_exact_rate is the fraction of TPs with exact offsets."""
    g = [_gold(0, 5, "country/KEN"), _gold(10, 15, "country/NGA")]
    p = [
        _pred(0, 5, "country/KEN"),  # exact match
        _pred(
            11, 15, "country/NGA"
        ),  # off-by-one start, still overlaps → TP but not exact
    ]
    r = span_metrics(predictions=p, gold=g)

    assert r.true_positives == 2
    assert r.false_positives == 0
    assert r.false_negatives == 0
    # Only one of the two TPs has exact boundaries.
    assert r.boundary_exact_rate == pytest.approx(0.5)


def test_no_gold_spans_nil_correct_rate_is_one():
    """When there are no NIL gold spans, nil_correct_rate is 1.0 by convention."""
    g = [_gold(0, 5, "country/KEN")]
    p = [_pred(0, 5, "country/KEN")]
    r = span_metrics(predictions=p, gold=g)
    assert r.nil_correct_rate == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# nil_correct / nil_total raw counts stored per row
# ---------------------------------------------------------------------------


def test_nil_raw_counts_stored_per_row():
    """span_metrics stores nil_correct and nil_total on the result."""
    # 3 NIL gold spans; parser links 1 of them (FP) → nil_correct=2, nil_total=3.
    g = [
        _gold(0, 5, eid=None),
        _gold(10, 15, eid=None),
        _gold(20, 25, eid=None),
    ]
    p = [_pred(10, 15, eid="country/KEN")]  # overlaps second NIL span → FP
    r = span_metrics(predictions=p, gold=g)

    assert r.nil_total == 3
    assert r.nil_correct == 2
    assert r.nil_correct_rate == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# aggregate_results micro-average vs macro-average
# ---------------------------------------------------------------------------


def test_aggregate_nil_is_micro_not_macro():
    """aggregate_results uses micro-average for nil_correct_rate.

    Two rows, each with 3 NIL gold spans:
      - Row 1: 1 correctly unlinked → nil_correct_rate = 1/3
      - Row 2: 1 correctly unlinked → nil_correct_rate = 1/3

    Micro: (1+1) / (3+3) = 2/6 = 0.333...
    Macro: mean([1/3, 1/3]) = 0.333... — identical here.

    To distinguish micro from macro we need rows with different nil_total:
      - Row A: 1/3 correct  → per-row rate = 0.333
      - Row B: 2/2 correct  → per-row rate = 1.0

    Micro:  (1+2) / (3+2) = 3/5 = 0.60
    Macro:  mean([1/3, 1.0]) = 0.667  (different from micro!)
    """
    import dataclasses

    # Row A: 3 NIL gold, 1 correct (2 are FPs via predictions).
    row_a = span_metrics(
        predictions=[
            _pred(10, 15, eid="country/KEN"),  # overlaps second NIL → FP
            _pred(20, 25, eid="country/NGA"),  # overlaps third NIL → FP
        ],
        gold=[
            _gold(0, 5, eid=None),
            _gold(10, 15, eid=None),
            _gold(20, 25, eid=None),
        ],
    )
    # Row B: 2 NIL gold, both correctly unlinked.
    row_b = span_metrics(
        predictions=[],
        gold=[
            _gold(30, 35, eid=None),
            _gold(40, 45, eid=None),
        ],
    )

    assert row_a.nil_correct == 1
    assert row_a.nil_total == 3
    assert row_b.nil_correct == 2
    assert row_b.nil_total == 2

    agg = aggregate_results(
        [
            dataclasses.replace(row_a, row_count=1),
            dataclasses.replace(row_b, row_count=1),
        ]
    )

    # Micro: (1+2)/(3+2) = 3/5 = 0.60
    assert agg.nil_correct == 3
    assert agg.nil_total == 5
    assert agg.nil_correct_rate == pytest.approx(3 / 5)

    # Confirm this differs from the macro average (0.667).
    macro = (row_a.nil_correct_rate + row_b.nil_correct_rate) / 2
    assert abs(agg.nil_correct_rate - macro) > 0.01, (
        "micro and macro rates should differ for rows with unequal nil_total"
    )
