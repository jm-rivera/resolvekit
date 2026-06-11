"""Mention-level span metrics for the parse evaluation harness.

Computes precision, recall, F1, boundary exactness, and NIL correctness
from a set of predicted spans vs. the hand-authored gold spans.

Public surface:

    PredSpan(start, end, entity_id, entity_type)
        One predicted span from ``resolver.parse()``.

    ParseEvalResult(precision, recall, f1, boundary_exact_rate,
                    nil_correct_rate, nil_correct, nil_total,
                    true_positives, false_positives, false_negatives, row_count)
        Aggregated result across all rows in an eval run.

    span_metrics(*, predictions, gold) -> ParseEvalResult
        Score one document (or a flattened pass over many documents).
"""

from __future__ import annotations

from dataclasses import dataclass

from benchmarks.parse.loader import GoldSpan


@dataclass(frozen=True, slots=True)
class PredSpan:
    """One predicted span produced by ``resolver.parse()``.

    Attributes:
        start:       Char offset of the span start (inclusive) in the source text.
        end:         Char offset of the span end (exclusive) in the source text.
        entity_id:   Linked entity id, or None for unlinked/NIL predictions.
        entity_type: Entity type returned by the resolver, or None.
    """

    start: int
    end: int
    entity_id: str | None
    entity_type: str | None


def _spans_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Return True when two half-open intervals share at least one character."""
    return a_start < b_end and b_start < a_end


@dataclass(frozen=True)
class ParseEvalResult:
    """Aggregated span-level metrics for one eval run.

    Attributes:
        precision:            TP / (TP + FP); 0.0 when no predictions.
        recall:               TP / (TP + FN); 0.0 when no gold spans.
        f1:                   Harmonic mean of precision and recall; 0.0 when both are 0.
        boundary_exact_rate:  Of matched-id spans, fraction with exact (start, end);
                              0.0 when TP == 0.
        nil_correct_rate:     Micro-average: nil_correct / nil_total; 1.0 when
                              nil_total == 0 (no NIL gold spans in the corpus).
        nil_correct:          Raw count of NIL gold spans correctly left unlinked.
        nil_total:            Raw count of NIL gold spans seen.
        true_positives:       Number of correctly linked spans.
        false_positives:      Number of spurious predictions (no matching gold).
        false_negatives:      Number of gold spans with no matching prediction.
        row_count:            Number of documents scored.
    """

    precision: float
    recall: float
    f1: float
    boundary_exact_rate: float
    nil_correct_rate: float
    nil_correct: int
    nil_total: int
    true_positives: int
    false_positives: int
    false_negatives: int
    row_count: int


def span_metrics(
    *,
    predictions: list[PredSpan],
    gold: list[GoldSpan],
) -> ParseEvalResult:
    """Score predicted spans against a gold set for one document.

    Matching rule (greedy, left-to-right by gold order):
    - A prediction matches a gold span when ``p.entity_id == g.expected_id``
      AND their offsets overlap.  Each prediction is consumed at most once.
    - Boundary exactness: a matched pair also earns a boundary-exact count
      when ``(p.start, p.end) == (g.start, g.end)``.
    - NIL gold spans (``expected_id is None``): correct when NO prediction
      links that region; a prediction that overlaps a NIL gold span is an FP.

    Empty-input edge: when both ``predictions`` and ``gold`` are empty,
    precision = recall = f1 = 0.0 (not NaN).

    Args:
        predictions: Predicted spans from the resolver for one document.
        gold:        Gold spans for that document.

    Returns:
        :class:`ParseEvalResult` with aggregated scores.
    """
    non_nil_gold = [g for g in gold if g.expected_id is not None]
    nil_gold = [g for g in gold if g.expected_id is None]

    used_pred_indices: set[int] = set()
    tp = 0
    fn = 0
    boundary_exact = 0

    # Greedy match: for each gold span find the first unused prediction that
    # has the same entity_id and overlapping offsets.
    for g in non_nil_gold:
        matched = False
        for pi, p in enumerate(predictions):
            if pi in used_pred_indices:
                continue
            if p.entity_id != g.expected_id:
                continue
            if not _spans_overlap(p.start, p.end, g.start, g.end):
                continue
            # Match found.
            tp += 1
            used_pred_indices.add(pi)
            if p.start == g.start and p.end == g.end:
                boundary_exact += 1
            matched = True
            break
        if not matched:
            fn += 1

    # NIL gold: correct when no prediction overlaps the NIL region; FP otherwise.
    nil_correct = 0
    nil_false_positives: list[int] = []
    for ng in nil_gold:
        overlapping = [
            pi
            for pi, p in enumerate(predictions)
            if pi not in used_pred_indices
            and _spans_overlap(p.start, p.end, ng.start, ng.end)
        ]
        if overlapping:
            # Consume the overlapping predictions as FPs.
            nil_false_positives.extend(overlapping)
            used_pred_indices.update(overlapping)
        else:
            nil_correct += 1

    # Any unmatched prediction (not used by a gold span, not consumed by a NIL check)
    # is an FP from spurious linking.
    fp = len(nil_false_positives) + sum(
        1 for pi in range(len(predictions)) if pi not in used_pred_indices
    )

    # Precision / recall / F1.
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    boundary_exact_rate = boundary_exact / tp if tp > 0 else 0.0
    nil_total = len(nil_gold)
    nil_correct_rate = nil_correct / nil_total if nil_total else 1.0

    return ParseEvalResult(
        precision=precision,
        recall=recall,
        f1=f1,
        boundary_exact_rate=boundary_exact_rate,
        nil_correct_rate=nil_correct_rate,
        nil_correct=nil_correct,
        nil_total=nil_total,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        row_count=1,
    )


def aggregate_results(results: list[ParseEvalResult]) -> ParseEvalResult:
    """Aggregate a list of per-document ParseEvalResult into one corpus-level result.

    Recomputes precision, recall, F1, boundary_exact_rate, and nil_correct_rate
    from the raw TP/FP/FN/boundary_exact/nil counts rather than averaging per-row
    ratios (macro vs. micro — micro is what the gate uses).

    Args:
        results: Per-document results from :func:`span_metrics`.

    Returns:
        A single :class:`ParseEvalResult` over all documents.
    """
    if not results:
        return ParseEvalResult(
            precision=0.0,
            recall=0.0,
            f1=0.0,
            boundary_exact_rate=0.0,
            nil_correct_rate=1.0,
            nil_correct=0,
            nil_total=0,
            true_positives=0,
            false_positives=0,
            false_negatives=0,
            row_count=0,
        )

    tp = sum(r.true_positives for r in results)
    fp = sum(r.false_positives for r in results)
    fn = sum(r.false_negatives for r in results)
    row_count = sum(r.row_count for r in results)

    # Recompute boundary_exact from the weighted rate stored per row.
    # Each row's boundary_exact_rate * tp gives the exact count.
    total_boundary_exact = sum(
        round(r.boundary_exact_rate * r.true_positives) for r in results
    )

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    boundary_exact_rate = total_boundary_exact / tp if tp > 0 else 0.0

    # Micro-average NIL correctness: sum raw counts, then divide once.
    # This matches GERBIL convention and avoids macro-averaging artefacts
    # when rows have different NIL span counts.
    nil_correct_total = sum(r.nil_correct for r in results)
    nil_total_total = sum(r.nil_total for r in results)
    nil_correct_rate = nil_correct_total / nil_total_total if nil_total_total else 1.0

    return ParseEvalResult(
        precision=precision,
        recall=recall,
        f1=f1,
        boundary_exact_rate=boundary_exact_rate,
        nil_correct_rate=nil_correct_rate,
        nil_correct=nil_correct_total,
        nil_total=nil_total_total,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        row_count=row_count,
    )
