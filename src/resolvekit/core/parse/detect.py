"""Span detection and cross-pack arbitration.

Per-pack detection calls ``PackAutomaton.find()`` which applies
leftmost-longest resolution within a pack.  Cross-pack positional overlap
is then resolved here by ``arbitrate_cross_pack``.

The two selection layers are distinct:
- Intra-pack (automaton): leftmost-longest AC; resolves "South Sudan" vs
  "Sudan" when both are geo.  Runs before linking.
- Cross-pack (arbitrate_cross_pack): after linking; each span already has
  a confidence score, so the winner is the better-linked span, not just the
  longer surface form.  This is NOT the same as ``MultiPackRunner._run``'s
  candidate merge — that merges candidates for a single query string; here
  each span is its own already-linked query and the conflict is purely
  positional.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from resolvekit.core.model.result import ResolutionResult, ResolutionStatus


# Lower value = higher priority when two spans have equal confidence.
# geo is preferred on ties: the geo pack has a calibrated confidence
# model (org has no calibrator).
_DOMAIN_PRIORITY: dict[str, int] = {"geo": 0, "org": 1}

# Large sentinel for packs not in the table — they lose all ties.
_DOMAIN_PRIORITY_DEFAULT = 99


class _LinkedSpan(NamedTuple):
    """A detected span together with its link outcome.

    Produced by ``link_span`` and consumed by ``arbitrate_cross_pack``
    and the engine assembler.

    Attributes:
        start: Start offset into the raw input string.
        end: End offset (exclusive) into the raw input string.
        surface: ``raw[start:end]``.
        entity_ids: Entity IDs from the automaton side-table (the hit
            payload; used for entity_types derivation in link.py).
        pack_id: Pack that produced the detection.
        result: Full ``ResolutionResult`` (may be NO_MATCH for NIL spans).
        status: Resolution status (mirrors ``result.status``).
        confidence: Calibrated confidence, or ``None`` for NIL spans
            where the engine found no candidates at all.
        entity_id: Resolved entity id (``None`` for NIL spans).
        entity_type: Entity type of the resolved entity (``None`` for NIL).
    """

    start: int
    end: int
    surface: str
    entity_ids: list[str]
    pack_id: str
    result: ResolutionResult
    status: ResolutionStatus
    confidence: float | None
    entity_id: str | None
    entity_type: str | None


def arbitrate_cross_pack(
    linked_spans: list[_LinkedSpan],
) -> list[_LinkedSpan]:
    """Resolve positional overlaps between spans from different packs.

    Two spans overlap when their ``[start, end)`` ranges intersect AND
    they come from different packs.  Same-pack overlaps are already
    resolved by the automaton's leftmost-longest algorithm, so this
    function only fires across packs.

    This is NOT the same as ``MultiPackRunner._run``'s candidate merge —
    that merges candidates for a single query string.  Here each span is
    an already-linked query; the conflict is purely positional.

    Algorithm: greedy sweep, ``O(m log m)`` in the number of spans.
    Sort spans by start offset, then scan forward keeping a "current
    winner" per overlapping cluster.  When a new span overlaps the winner,
    replace the winner only if the new span is strictly better (higher
    confidence, or equal confidence with higher domain priority).

    Selection rule (in preference order):
    1. RESOLVED beats NIL (NO_MATCH).  A span with ``status != NO_MATCH``
       always wins over a span with ``status == NO_MATCH``, regardless of
       confidence.
    2. Higher confidence wins.
    3. Tie-break by domain priority: ``_DOMAIN_PRIORITY["geo"] == 0``
       (lower = preferred), so geo wins when both have identical confidence.

    Non-overlapping spans pass through untouched.

    Args:
        linked_spans: Linked spans in any order; may come from multiple
            packs and may overlap across packs.

    Returns:
        De-overlapped list of ``_LinkedSpan``s, sorted by ``start``.
    """
    if len(linked_spans) <= 1:
        return list(linked_spans)

    # Sort by start; stable within same start (keep insertion order).
    spans = sorted(linked_spans, key=lambda s: s.start)

    result: list[_LinkedSpan] = []
    # winner: the span currently occupying the latest [start, end) range.
    winner: _LinkedSpan | None = None

    for span in spans:
        if winner is None:
            winner = span
            continue

        # No overlap: flush winner, start fresh.
        if span.start >= winner.end:
            result.append(winner)
            winner = span
            continue

        # Overlap between different packs — arbitrate.
        if span.pack_id == winner.pack_id:
            # Same pack shouldn't overlap (AC is leftmost-longest), but if it
            # somehow does, keep whichever ends later (longer match wins).
            if span.end > winner.end:
                winner = span
            continue

        # Different-pack overlap: pick the better-linked span.
        winner = _pick_winner(winner, span)

    if winner is not None:
        result.append(winner)

    return result


def _pick_winner(a: _LinkedSpan, b: _LinkedSpan) -> _LinkedSpan:
    """Return the better of two overlapping, differently-packed spans.

    Priority (desc): RESOLVED > NIL; higher confidence; lower domain rank.
    """
    from resolvekit.core.model.result import ResolutionStatus

    a_nil = a.status == ResolutionStatus.NO_MATCH
    b_nil = b.status == ResolutionStatus.NO_MATCH

    # Rule 1: RESOLVED beats NIL.
    if a_nil and not b_nil:
        return b
    if b_nil and not a_nil:
        return a

    # Rule 2: higher confidence wins (None = 0.0 for comparison purposes).
    a_conf = a.confidence if a.confidence is not None else 0.0
    b_conf = b.confidence if b.confidence is not None else 0.0

    if a_conf > b_conf:
        return a
    if b_conf > a_conf:
        return b

    # Rule 3: domain priority (lower value = preferred).
    a_pri = _DOMAIN_PRIORITY.get(a.pack_id, _DOMAIN_PRIORITY_DEFAULT)
    b_pri = _DOMAIN_PRIORITY.get(b.pack_id, _DOMAIN_PRIORITY_DEFAULT)

    return a if a_pri <= b_pri else b


__all__ = [
    "_DOMAIN_PRIORITY",
    "_LinkedSpan",
    "arbitrate_cross_pack",
]
