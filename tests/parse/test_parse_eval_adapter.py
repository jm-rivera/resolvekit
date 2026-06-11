"""Tests for ParseAdapter protocol and run_parse_eval_adapter.

Covers:
- A stub adapter with fixed PredSpan output is correctly scored by
  run_parse_eval_adapter.
- ResolverParseAdapter scoring over a fixture Resolver matches a direct
  run_parse_eval call with latency=False.
"""

from __future__ import annotations

import pytest

from benchmarks.parse.loader import GoldSpan, ParseEvalRow
from benchmarks.parse.metrics import PredSpan
from benchmarks.parse.runner import (
    ParseAdapter,
    ResolverParseAdapter,
    run_parse_eval,
    run_parse_eval_adapter,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gold(start: int, end: int, eid: str | None = "country/KEN") -> GoldSpan:
    return GoldSpan(start=start, end=end, expected_id=eid, entity_type="geo.country")


def _pred(start: int, end: int, eid: str | None = "country/KEN") -> PredSpan:
    return PredSpan(start=start, end=end, entity_id=eid, entity_type="geo.country")


def _row(text: str, *gold_spans: GoldSpan, row_id: str = "r0") -> ParseEvalRow:
    return ParseEvalRow(
        row_id=row_id,
        text=text,
        language="en",
        gold_spans=tuple(gold_spans),
    )


# ---------------------------------------------------------------------------
# Stub adapter
# ---------------------------------------------------------------------------


class _FixedAdapter:
    """Adapter that returns a preset prediction regardless of input text."""

    def __init__(self, preds: list[PredSpan]) -> None:
        self._preds = preds

    def predict(self, text: str) -> list[PredSpan]:
        return list(self._preds)


# ---------------------------------------------------------------------------
# Protocol structural conformance
# ---------------------------------------------------------------------------


def test_stub_adapter_conforms_to_protocol():
    """_FixedAdapter satisfies ParseAdapter structurally (no subclassing)."""
    assert isinstance(_FixedAdapter([]), ParseAdapter)


# ---------------------------------------------------------------------------
# Stub adapter scored correctly by run_parse_eval_adapter
# ---------------------------------------------------------------------------


def test_adapter_exact_match():
    """A stub adapter returning the gold span earns TP=1, FP=0, FN=0."""
    rows = [_row("Kenya", _gold(0, 5, "country/KEN"))]
    adapter = _FixedAdapter([_pred(0, 5, "country/KEN")])

    report = run_parse_eval_adapter(adapter=adapter, rows=rows)

    assert report.metrics.true_positives == 1
    assert report.metrics.false_positives == 0
    assert report.metrics.false_negatives == 0
    assert report.metrics.precision == pytest.approx(1.0)
    assert report.metrics.recall == pytest.approx(1.0)
    assert report.metrics.f1 == pytest.approx(1.0)
    assert report.row_count == 1
    # Latency is always None from run_parse_eval_adapter.
    assert report.latency is None


def test_adapter_false_positive():
    """A stub returning a span that doesn't match any gold span is an FP."""
    rows = [_row("no mentions here")]
    adapter = _FixedAdapter([_pred(0, 5, "country/NGA")])

    report = run_parse_eval_adapter(adapter=adapter, rows=rows)

    assert report.metrics.true_positives == 0
    assert report.metrics.false_positives == 1
    assert report.metrics.false_negatives == 0


def test_adapter_false_negative():
    """A stub returning no predictions for a gold span is an FN."""
    rows = [_row("Kenya", _gold(0, 5, "country/KEN"))]
    adapter = _FixedAdapter([])  # predicts nothing

    report = run_parse_eval_adapter(adapter=adapter, rows=rows)

    assert report.metrics.true_positives == 0
    assert report.metrics.false_positives == 0
    assert report.metrics.false_negatives == 1


def test_adapter_multi_row_aggregation():
    """Scoring two rows aggregates counts correctly."""
    row1 = _row("Kenya", _gold(0, 5, "country/KEN"), row_id="r1")
    row2 = _row("Somalia", _gold(0, 7, "country/SOM"), row_id="r2")

    # Adapter: correctly predicts Kenya but misses Somalia.
    class _SelectiveAdapter:
        def predict(self, text: str) -> list[PredSpan]:
            if "Kenya" in text:
                return [_pred(0, 5, "country/KEN")]
            return []

    report = run_parse_eval_adapter(adapter=_SelectiveAdapter(), rows=[row1, row2])

    assert report.metrics.true_positives == 1
    assert report.metrics.false_negatives == 1
    assert report.row_count == 2


# ---------------------------------------------------------------------------
# ResolverParseAdapter parity with run_parse_eval
# ---------------------------------------------------------------------------


def test_resolver_adapter_scores_identically_to_run_parse_eval(
    parse_geo_resolver,
):
    """ResolverParseAdapter scoring matches direct run_parse_eval (latency=None).

    Both paths call resolver.parse() under the hood; the scores must be
    bit-identical (same TP/FP/FN/precision/recall/F1).
    """
    from benchmarks.parse.loader import GoldSpan, ParseEvalRow

    # Build a small gold set from the fixture resolver's known entities.
    rows = [
        ParseEvalRow(
            row_id="r0",
            text="Kenya and Somalia",
            language="en",
            gold_spans=(
                GoldSpan(
                    start=0, end=5, expected_id="country/KEN", entity_type="geo.country"
                ),
                GoldSpan(
                    start=10,
                    end=17,
                    expected_id="country/SOM",
                    entity_type="geo.country",
                ),
            ),
        ),
    ]

    # run_parse_eval path (latency=False so latency block is None).
    report_direct = run_parse_eval(
        resolver=parse_geo_resolver,
        rows=rows,
        measure_latency=False,
    )

    # run_parse_eval_adapter path via ResolverParseAdapter.
    adapter = ResolverParseAdapter(parse_geo_resolver)
    report_adapter = run_parse_eval_adapter(adapter=adapter, rows=rows)

    m_direct = report_direct.metrics
    m_adapter = report_adapter.metrics

    assert m_direct.true_positives == m_adapter.true_positives
    assert m_direct.false_positives == m_adapter.false_positives
    assert m_direct.false_negatives == m_adapter.false_negatives
    assert m_direct.precision == pytest.approx(m_adapter.precision)
    assert m_direct.recall == pytest.approx(m_adapter.recall)
    assert m_direct.f1 == pytest.approx(m_adapter.f1)
    assert m_direct.nil_correct == m_adapter.nil_correct
    assert m_direct.nil_total == m_adapter.nil_total

    # run_parse_eval with measure_latency=False returns latency=None.
    assert report_direct.latency is None
    # run_parse_eval_adapter always returns latency=None.
    assert report_adapter.latency is None
