"""Regression tests for AmbiguousResolutionError hint/message.

Covers:
- the hint must be candidate-aware — suggesting ``entity_types`` only
  when the near-tied finalists span more than one entity type, never when they
  share a type (e.g. ``country/COD`` vs ``country/COG`` for "Congo").
- ``str(e)`` must preview the top candidates and reference ``.candidates``.
"""

from __future__ import annotations

from resolvekit.core.errors import (
    AmbiguousResolutionError,
    entity_types_would_disambiguate,
)
from resolvekit.core.model import CandidateSummary


def _cand(entity_id: str, entity_type: str, confidence: float) -> CandidateSummary:
    return CandidateSummary(
        entity_id=entity_id, entity_type=entity_type, confidence=confidence
    )


class TestEntityTypesWouldDisambiguate:
    def test_same_type_finalists_returns_false(self) -> None:
        """Congo-shape: both near-tied finalists are geo.country."""
        candidates = [
            _cand("country/COD", "geo.country", 0.922),
            _cand("country/COG", "geo.country", 0.918),
            _cand("wikidataId/Q1", "geo.admin2", 0.876),
        ]
        assert entity_types_would_disambiguate(candidates) is False

    def test_distinct_top_two_types_returns_true(self) -> None:
        """A genuine cross-type ambiguity: top two carry different types."""
        candidates = [
            _cand("city/X", "geo.city", 0.90),
            _cand("admin1/Y", "geo.admin1", 0.89),
        ]
        assert entity_types_would_disambiguate(candidates) is True

    def test_empty_or_single_returns_false(self) -> None:
        assert entity_types_would_disambiguate(None) is False
        assert entity_types_would_disambiguate([]) is False
        assert entity_types_would_disambiguate([_cand("a/X", "t", 0.9)]) is False

    def test_missing_type_returns_false(self) -> None:
        candidates = [
            CandidateSummary(entity_id="a/X", confidence=0.9),
            _cand("b/Y", "geo.city", 0.89),
        ]
        assert entity_types_would_disambiguate(candidates) is False


class TestAmbiguousResolutionErrorHint:
    def test_same_type_hint_omits_entity_types(self) -> None:
        candidates = [
            _cand("country/COD", "geo.country", 0.922),
            _cand("country/COG", "geo.country", 0.918),
        ]
        err = AmbiguousResolutionError(candidates=candidates)
        assert err.hint is not None
        assert "entity_types=" not in err.hint
        assert ".candidates" in err.hint
        assert "on_ambiguous='best'" in err.hint

    def test_cross_type_hint_suggests_entity_types(self) -> None:
        candidates = [
            _cand("city/X", "geo.city", 0.90),
            _cand("admin1/Y", "geo.admin1", 0.89),
        ]
        err = AmbiguousResolutionError(candidates=candidates)
        assert err.hint is not None
        assert "entity_types=" in err.hint

    def test_no_candidates_hint_omits_entity_types(self) -> None:
        err = AmbiguousResolutionError(candidates=None)
        assert err.hint is not None
        assert "entity_types=" not in err.hint
        assert ".candidates" in err.hint

    def test_caller_supplied_hint_wins(self) -> None:
        err = AmbiguousResolutionError(candidates=None, hint="custom hint")
        assert err.hint == "custom hint"


class TestAmbiguousResolutionErrorMessage:
    def test_message_previews_candidates_and_references_attribute(self) -> None:
        candidates = [
            _cand("country/COD", "geo.country", 0.922),
            _cand("country/COG", "geo.country", 0.918),
            _cand("wikidataId/Q1", "geo.admin2", 0.876),
            _cand("wikidataId/Q2", "geo.city", 0.873),
        ]
        msg = str(AmbiguousResolutionError(candidates=candidates))
        assert "country/COD" in msg
        assert "0.92" in msg
        assert ".candidates" in msg
        # Preview is capped, so a "..." marker appears for >3 candidates.
        assert "..." in msg

    def test_message_without_candidates_is_bare_count(self) -> None:
        msg = str(AmbiguousResolutionError(candidates=None))
        assert "0 candidates" in msg
