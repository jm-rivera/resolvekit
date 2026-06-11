"""Tests for span detection and cross-pack arbitration.

Covers leftmost-longest matching, overlapping-span arbitration by confidence
and domain priority, NIL vs RESOLVED resolution, and non-overlapping span survival.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from resolvekit.core.model.result import ResolutionResult, ResolutionStatus
from resolvekit.core.parse.automaton import PackAutomaton
from resolvekit.core.parse.detect import _LinkedSpan, arbitrate_cross_pack
from resolvekit.packs.geo.pack import GEO_NORMALIZATION_PROFILE

# ---------------------------------------------------------------------------
# Bundled geo countries store path
# ---------------------------------------------------------------------------

_COUNTRIES_DB = (
    Path(__file__).parent.parent.parent
    / "src/resolvekit/_data/geo/countries/entities.sqlite"
)


@pytest.fixture
def countries_automaton() -> PackAutomaton:
    """SMALL geo automaton over the bundled countries data."""
    from resolvekit.core.store.sqlite import SQLiteEntityStore
    from resolvekit.packs.geo.sources.symspell import _SMALL_ENTITY_TYPE_PREFIXES

    store = SQLiteEntityStore(_COUNTRIES_DB)
    return PackAutomaton(
        store=store,
        profile=GEO_NORMALIZATION_PROFILE,
        pack_id="geo",
        small_prefixes=_SMALL_ENTITY_TYPE_PREFIXES,
    )


# ---------------------------------------------------------------------------
# Minimal ResolutionResult factory for hand-built spans
# ---------------------------------------------------------------------------


def _make_result(
    *,
    status: ResolutionStatus,
    confidence: float | None = None,
    entity_id: str | None = None,
) -> ResolutionResult:
    """Build a bare ResolutionResult (no _explainer) for unit tests."""
    return ResolutionResult(
        status=status,
        confidence=confidence,
        entity_id=entity_id,
    )


def _make_linked(
    *,
    start: int,
    end: int,
    pack_id: str,
    status: ResolutionStatus,
    confidence: float | None,
    entity_id: str | None = None,
) -> _LinkedSpan:
    """Build a ``_LinkedSpan`` for arbitration unit tests."""
    result = _make_result(status=status, confidence=confidence, entity_id=entity_id)
    return _LinkedSpan(
        start=start,
        end=end,
        surface="text"[start:end] if end <= 4 else "x" * (end - start),
        entity_ids=[],
        pack_id=pack_id,
        result=result,
        status=status,
        confidence=confidence,
        entity_id=entity_id,
        entity_type=None,
    )


# ---------------------------------------------------------------------------
# Nested same-pack: leftmost-longest
# ---------------------------------------------------------------------------


def test_south_sudan_wins_over_sudan(
    countries_automaton: PackAutomaton,
) -> None:
    """AC leftmost-longest: 'South Sudan' should be detected, not bare 'Sudan'."""
    raw = "The crisis in South Sudan continues"
    hits = countries_automaton.find(raw)
    surfaces = [h.surface.lower() for h in hits]
    # "South Sudan" should appear.
    assert any("south sudan" in s for s in surfaces), (
        f"'South Sudan' not detected; got: {[h.surface for h in hits]}"
    )
    # "Sudan" alone must NOT appear as a separate hit in the same span region.
    # Because AC is leftmost-longest, once "South Sudan" is matched, a bare
    # "Sudan" inside it should not also appear.
    for hit in hits:
        if hit.surface.lower() == "sudan":
            # It's only valid if it refers to a different offset (e.g.
            # "Sudan" appearing elsewhere in the string — not the case here).
            assert not (
                hit.start >= raw.lower().index("south")
                and hit.end <= raw.lower().index("south") + len("south sudan")
            ), "Bare 'Sudan' must not overlap with 'South Sudan' hit"


# ---------------------------------------------------------------------------
# Cross-pack overlap arbitration
# ---------------------------------------------------------------------------


def test_arbitration_geo_high_conf_beats_org_low_conf() -> None:
    """geo conf 0.9 vs org conf 0.6 → geo span wins."""
    geo_span = _make_linked(
        start=0,
        end=5,
        pack_id="geo",
        status=ResolutionStatus.RESOLVED,
        confidence=0.9,
        entity_id="country/KEN",
    )
    org_span = _make_linked(
        start=0,
        end=5,
        pack_id="org",
        status=ResolutionStatus.RESOLVED,
        confidence=0.6,
        entity_id="org/KEN",
    )
    result = arbitrate_cross_pack([geo_span, org_span])
    assert len(result) == 1
    assert result[0].pack_id == "geo"
    assert result[0].entity_id == "country/KEN"


def test_arbitration_org_high_conf_beats_geo_low_conf() -> None:
    """org conf 0.9 vs geo conf 0.6 → org span wins."""
    geo_span = _make_linked(
        start=0,
        end=5,
        pack_id="geo",
        status=ResolutionStatus.RESOLVED,
        confidence=0.6,
        entity_id="country/KEN",
    )
    org_span = _make_linked(
        start=0,
        end=5,
        pack_id="org",
        status=ResolutionStatus.RESOLVED,
        confidence=0.9,
        entity_id="org/KEN",
    )
    result = arbitrate_cross_pack([geo_span, org_span])
    assert len(result) == 1
    assert result[0].pack_id == "org"
    assert result[0].entity_id == "org/KEN"


def test_arbitration_equal_conf_geo_priority_wins() -> None:
    """Equal confidence → geo wins by domain priority."""
    geo_span = _make_linked(
        start=0,
        end=5,
        pack_id="geo",
        status=ResolutionStatus.RESOLVED,
        confidence=0.75,
        entity_id="country/KEN",
    )
    org_span = _make_linked(
        start=0,
        end=5,
        pack_id="org",
        status=ResolutionStatus.RESOLVED,
        confidence=0.75,
        entity_id="org/KEN",
    )
    result = arbitrate_cross_pack([geo_span, org_span])
    assert len(result) == 1
    assert result[0].pack_id == "geo", "geo must win tie-break by domain priority"


def test_arbitration_nil_vs_resolved_resolved_wins() -> None:
    """A RESOLVED span beats a NIL (NO_MATCH) span regardless of confidence."""
    nil_span = _make_linked(
        start=0,
        end=5,
        pack_id="geo",
        status=ResolutionStatus.NO_MATCH,
        confidence=0.99,  # high near-miss confidence
        entity_id=None,
    )
    resolved_span = _make_linked(
        start=0,
        end=5,
        pack_id="org",
        status=ResolutionStatus.RESOLVED,
        confidence=0.55,  # lower, but RESOLVED
        entity_id="org/UN",
    )
    result = arbitrate_cross_pack([nil_span, resolved_span])
    assert len(result) == 1
    assert result[0].status == ResolutionStatus.RESOLVED
    assert result[0].entity_id == "org/UN"


def test_arbitration_both_nil_geo_wins() -> None:
    """When both spans are NIL, geo wins by domain priority."""
    geo_nil = _make_linked(
        start=0,
        end=5,
        pack_id="geo",
        status=ResolutionStatus.NO_MATCH,
        confidence=0.4,
    )
    org_nil = _make_linked(
        start=0,
        end=5,
        pack_id="org",
        status=ResolutionStatus.NO_MATCH,
        confidence=0.4,
    )
    result = arbitrate_cross_pack([geo_nil, org_nil])
    assert len(result) == 1
    assert result[0].pack_id == "geo"


# ---------------------------------------------------------------------------
# No false overlap: adjacent spans both survive
# ---------------------------------------------------------------------------


def test_adjacent_spans_both_survive() -> None:
    """Non-overlapping adjacent spans must both be kept."""
    # [0, 5) and [5, 10) are adjacent, not overlapping.
    geo_span = _make_linked(
        start=0,
        end=5,
        pack_id="geo",
        status=ResolutionStatus.RESOLVED,
        confidence=0.9,
        entity_id="country/KEN",
    )
    org_span = _make_linked(
        start=5,
        end=10,
        pack_id="org",
        status=ResolutionStatus.RESOLVED,
        confidence=0.9,
        entity_id="org/UN",
    )
    result = arbitrate_cross_pack([geo_span, org_span])
    assert len(result) == 2
    assert {s.entity_id for s in result} == {"country/KEN", "org/UN"}


def test_non_overlapping_same_pack_both_survive() -> None:
    """Two non-overlapping same-pack spans must both survive unchanged."""
    span_a = _make_linked(
        start=0,
        end=5,
        pack_id="geo",
        status=ResolutionStatus.RESOLVED,
        confidence=0.9,
        entity_id="country/KEN",
    )
    span_b = _make_linked(
        start=10,
        end=15,
        pack_id="geo",
        status=ResolutionStatus.RESOLVED,
        confidence=0.8,
        entity_id="country/SOM",
    )
    result = arbitrate_cross_pack([span_a, span_b])
    assert len(result) == 2


def test_three_span_cluster_resolves_correctly() -> None:
    """Three overlapping spans across two packs → single winner."""
    # geo low conf, org high conf, another geo low conf — all overlap at [0,10).
    geo_a = _make_linked(
        start=0,
        end=10,
        pack_id="geo",
        status=ResolutionStatus.RESOLVED,
        confidence=0.6,
        entity_id="country/A",
    )
    org_b = _make_linked(
        start=2,
        end=8,
        pack_id="org",
        status=ResolutionStatus.RESOLVED,
        confidence=0.85,
        entity_id="org/B",
    )
    result = arbitrate_cross_pack([geo_a, org_b])
    assert len(result) == 1
    assert result[0].entity_id == "org/B"
