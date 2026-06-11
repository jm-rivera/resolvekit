"""Tests for ResolutionResult.__repr__ NO_MATCH refinement-hint branch."""

from __future__ import annotations

from resolvekit.core.model.result import (
    CandidateSummary,
    ReasonCode,
    RefinementHint,
    ResolutionResult,
    ResolutionStatus,
)


def _no_match(
    *,
    refinement_hints: list[RefinementHint] | None = None,
    query_text: str | None = "Paris",
    candidates: list[CandidateSummary] | None = None,
    reasons: list[ReasonCode] | None = None,
) -> ResolutionResult:
    return ResolutionResult(
        status=ResolutionStatus.NO_MATCH,
        refinement_hints=refinement_hints or [],
        query_text=query_text,
        candidates=candidates or [],
        reasons=reasons or [ReasonCode.NO_CANDIDATES],
    )


# ---------------------------------------------------------------------------
# Test 1 — COUNTRY hint with inferrable ISO2
# ---------------------------------------------------------------------------


def test_no_match_with_country_hint_renders_runnable_line() -> None:
    result = _no_match(
        refinement_hints=[RefinementHint.COUNTRY],
        candidates=[
            CandidateSummary(
                entity_id="city/paris-fr",
                pack_id="geo",
                entity_type="geo.city",
                canonical_name="Paris",
            )
        ],
    )
    r = repr(result)
    assert r.startswith("NO_MATCH — try:")
    assert "resolvekit.resolve(text='Paris'," in r
    assert "context=ResolutionContext(country=" in r


# ---------------------------------------------------------------------------
# Test 2 — ENTITY_TYPES hint
# ---------------------------------------------------------------------------


def test_no_match_with_entity_types_hint_renders_runnable_line() -> None:
    result = _no_match(
        refinement_hints=[RefinementHint.ENTITY_TYPES],
        candidates=[
            CandidateSummary(
                entity_id="country/FRA",
                entity_type="geo.country",
                canonical_name="France",
            )
        ],
    )
    r = repr(result)
    assert r.startswith("NO_MATCH — try:")
    assert "entity_types={'geo.country'}" in r


# ---------------------------------------------------------------------------
# Test 3 — DID_YOU_MEAN hint renders canonical names
# ---------------------------------------------------------------------------


def test_no_match_with_did_you_mean_hint_renders_canonical_resolves() -> None:
    result = _no_match(
        refinement_hints=[RefinementHint.DID_YOU_MEAN],
        candidates=[
            CandidateSummary(entity_id="city/paris-fr", canonical_name="Paris"),
            CandidateSummary(entity_id="city/paris-tx", canonical_name="Paris, TX"),
        ],
    )
    r = repr(result)
    assert r.startswith("NO_MATCH — try:")
    # canonical names from candidates (excluding query_text itself)
    assert "resolvekit.resolve(text='Paris, TX')" in r


# ---------------------------------------------------------------------------
# Test 4 — no refinement_hints → terse form unchanged
# ---------------------------------------------------------------------------


def test_no_match_without_refinement_hints_renders_terse_form() -> None:
    result = _no_match(refinement_hints=[], reasons=[ReasonCode.NO_CANDIDATES])
    assert (
        repr(result) == "ResolutionResult(status='no_match', reasons=['no_candidates'])"
    )


# ---------------------------------------------------------------------------
# Test 5 — query_text=None → terse form (helper returns None)
# ---------------------------------------------------------------------------


def test_no_match_without_query_text_renders_terse_form() -> None:
    result = _no_match(
        refinement_hints=[RefinementHint.COUNTRY],
        query_text=None,
    )
    assert repr(result).startswith("ResolutionResult(status='no_match'")
    assert "NO_MATCH — try:" not in repr(result)


# ---------------------------------------------------------------------------
# Test 6 — DID_YOU_MEAN with no candidates → terse fallback
# ---------------------------------------------------------------------------


def test_no_match_with_unactionable_did_you_mean_falls_back_to_terse() -> None:
    result = _no_match(
        refinement_hints=[RefinementHint.DID_YOU_MEAN],
        candidates=[],
    )
    assert repr(result).startswith("ResolutionResult(status='no_match'")
    assert "NO_MATCH — try:" not in repr(result)


# ---------------------------------------------------------------------------
# Test 7 — RESOLVED repr unchanged
# ---------------------------------------------------------------------------


def test_resolved_repr_unchanged() -> None:
    result = ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        entity_id="country/USA",
        confidence=0.99,
        pack_id="geo",
    )
    r = repr(result)
    assert r == (
        "ResolutionResult(status='resolved', entity_id='country/USA', "
        "confidence=0.99, pack_id='geo')"
    )


# ---------------------------------------------------------------------------
# Test 8 — AMBIGUOUS repr unchanged (regression guard)
# ---------------------------------------------------------------------------


def test_ambiguous_repr_unchanged() -> None:
    result = ResolutionResult(
        status=ResolutionStatus.AMBIGUOUS,
        query_text="Paris",
        candidates=[
            CandidateSummary(entity_id="city/paris-fr", canonical_name="Paris, France"),
            CandidateSummary(entity_id="city/paris-tx", canonical_name="Paris, TX"),
        ],
    )
    r = repr(result)
    # Must use the AMBIGUOUS branch, not the NO_MATCH branch
    assert r.startswith("AMBIGUOUS — try:")
    assert "resolvekit.resolve(text='Paris, France')" in r
    assert "resolvekit.resolve(text='Paris, TX')" in r
    # Must NOT contain "NO_MATCH"
    assert "NO_MATCH" not in r
