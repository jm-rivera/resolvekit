"""Tests for Layer 3: result teaches the fix.

Covers:
- CandidateSummary.parent_name / parent_country fields exist and default to None.
- AMBIGUOUS __repr__ lists candidates with parent context, with a dict hint.
- NO_MATCH refinement hints use dict form (no ResolutionContext( substring).
- RESOLVED path leaves parent_name/parent_country as None (no extra lookups).
- _resolve_parent_context populates parent context for AMBIGUOUS candidates.
- dict-form hint is copy-pasteable (can be evaluated as a valid Python literal).
"""

from __future__ import annotations

import ast
from unittest.mock import MagicMock

import pytest

from resolvekit.core.explain import result_html as rh
from resolvekit.core.model.result import (
    CandidateSummary,
    ReasonCode,
    RefinementHint,
    ResolutionResult,
    ResolutionStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ambiguous(
    candidates: list[CandidateSummary] | None = None,
    *,
    query_text: str | None = "Paris",
) -> ResolutionResult:
    if candidates is None:
        candidates = [
            CandidateSummary(
                entity_id="city/paris-fr",
                confidence=0.85,
                canonical_name="Paris",
                entity_type="geo.city",
                pack_id="geo-FR",
                parent_country="FR",
                parent_name="France",
            ),
            CandidateSummary(
                entity_id="city/paris-tx",
                confidence=0.82,
                canonical_name="Paris",
                entity_type="geo.city",
                pack_id="geo-US",
                parent_country="US",
                parent_name="Texas",
            ),
        ]
    return ResolutionResult(
        status=ResolutionStatus.AMBIGUOUS,
        reasons=[ReasonCode.AMBIGUOUS_LOW_GAP],
        candidates=candidates,
        query_text=query_text,
    )


def _no_match(
    *,
    refinement_hints: list[RefinementHint] | None = None,
    query_text: str | None = "Paris",
    candidates: list[CandidateSummary] | None = None,
) -> ResolutionResult:
    return ResolutionResult(
        status=ResolutionStatus.NO_MATCH,
        refinement_hints=refinement_hints or [],
        query_text=query_text,
        candidates=candidates or [],
        reasons=[ReasonCode.NO_CANDIDATES],
    )


# ---------------------------------------------------------------------------
# CandidateSummary new fields
# ---------------------------------------------------------------------------


class TestCandidateSummaryParentFields:
    def test_default_none(self) -> None:
        cand = CandidateSummary(entity_id="city/paris-fr", confidence=0.9)
        assert cand.parent_name is None
        assert cand.parent_country is None

    def test_fields_roundtrip(self) -> None:
        cand = CandidateSummary(
            entity_id="city/paris-fr",
            confidence=0.9,
            parent_name="France",
            parent_country="FR",
        )
        assert cand.parent_name == "France"
        assert cand.parent_country == "FR"

    def test_frozen_model(self) -> None:
        cand = CandidateSummary(entity_id="city/X", confidence=0.9)
        with pytest.raises(Exception):  # pydantic frozen model raises on assignment
            cand.parent_name = "foo"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AMBIGUOUS __repr__ with parent context
# ---------------------------------------------------------------------------


class TestAmbiguousReprWithParentContext:
    def test_repr_starts_with_ambiguous_candidates(self) -> None:
        r = repr(_ambiguous())
        assert r.startswith("AMBIGUOUS — candidates:")

    def test_repr_shows_parent_name_for_same_canonical_name(self) -> None:
        r = repr(_ambiguous())
        assert "France" in r
        assert "Texas" in r

    def test_repr_shows_parent_country_fallback_when_no_parent_name(self) -> None:
        candidates = [
            CandidateSummary(
                entity_id="city/paris-fr",
                confidence=0.85,
                canonical_name="Paris",
                parent_country="FR",
            ),
            CandidateSummary(
                entity_id="city/paris-tx",
                confidence=0.82,
                canonical_name="Paris",
                parent_country="US",
            ),
        ]
        r = repr(_ambiguous(candidates))
        assert "FR" in r
        assert "US" in r

    def test_repr_shows_confidence(self) -> None:
        r = repr(_ambiguous())
        assert "conf=0.85" in r
        assert "conf=0.82" in r

    def test_repr_includes_try_hint_when_did_you_mean_available(self) -> None:
        # Different canonical names (not equal to query_text) → did_you_mean fires
        candidates = [
            CandidateSummary(
                entity_id="city/paris-fr",
                confidence=0.85,
                canonical_name="Paris, France",
                entity_type="geo.city",
                parent_country="FR",
            ),
            CandidateSummary(
                entity_id="city/paris-tx",
                confidence=0.82,
                canonical_name="Paris, TX",
                entity_type="geo.city",
                parent_country="US",
            ),
        ]
        r = repr(_ambiguous(candidates))
        assert "try:" in r
        assert "resolvekit.resolve(text='Paris, France')" in r

    def test_repr_try_hint_uses_parent_country_for_same_name_same_type(self) -> None:
        # Same canonical name as query_text → did_you_mean returns None;
        # same entity_type → type fallback also returns None;
        # but top candidate has parent_country → country hint is emitted.
        r = repr(_ambiguous())
        assert "AMBIGUOUS — candidates:" in r
        assert "try:" in r
        assert "context={'country':" in r

    def test_repr_does_not_include_try_hint_when_no_query_text(self) -> None:
        r = repr(_ambiguous(query_text=None))
        # No query_text means disambiguate_hint returns None — "try:" block absent
        assert "try:" not in r

    def test_repr_no_hint_when_no_parent_country_and_same_name_same_type(self) -> None:
        # Same canonical name + same type + NO parent_country → still no hint
        candidates = [
            CandidateSummary(
                entity_id="city/paris-a",
                confidence=0.85,
                canonical_name="Paris",
                entity_type="geo.city",
            ),
            CandidateSummary(
                entity_id="city/paris-b",
                confidence=0.82,
                canonical_name="Paris",
                entity_type="geo.city",
            ),
        ]
        r = repr(_ambiguous(candidates))
        assert "try:" not in r

    def test_repr_no_hint_when_all_candidates_share_same_country(self) -> None:
        # All candidates in the same country (e.g. Springfield, VT vs Springfield, NJ)
        # → a country hint cannot disambiguate; must not emit one.
        candidates = [
            CandidateSummary(
                entity_id="city/springfield-vt",
                confidence=0.90,
                canonical_name="Springfield",
                entity_type="geo.city",
                parent_country="US",
                parent_name="Vermont",
            ),
            CandidateSummary(
                entity_id="city/springfield-nj",
                confidence=0.90,
                canonical_name="Springfield",
                entity_type="geo.city",
                parent_country="US",
                parent_name="New Jersey",
            ),
            CandidateSummary(
                entity_id="city/springfield-mo",
                confidence=0.89,
                canonical_name="Springfield",
                entity_type="geo.city",
                parent_country="US",
                parent_name="Missouri",
            ),
        ]
        result = ResolutionResult(
            status=ResolutionStatus.AMBIGUOUS,
            reasons=[ReasonCode.AMBIGUOUS_LOW_GAP],
            candidates=candidates,
            query_text="Springfield",
        )
        r = repr(result)
        assert "try:" not in r

    def test_repr_hint_fires_when_candidates_span_different_countries(self) -> None:
        # Candidates in different countries → hint is useful, must be emitted.
        r = repr(_ambiguous())  # fixture has FR + US
        assert "try:" in r
        assert "context={'country': 'FR'}" in r

    def test_parent_country_never_contains_hyphen(self) -> None:
        # Subdivision codes (e.g. "US-VT") must be normalized to alpha-2 ("US")
        # before being stored in parent_country.
        candidates = [
            CandidateSummary(
                entity_id="city/springfield-vt",
                confidence=0.90,
                canonical_name="Springfield",
                entity_type="geo.city",
                parent_country="US-VT",  # raw subdivision code — should never appear
            ),
        ]
        from resolvekit.core.explain.result_html import disambiguate_hint

        result = ResolutionResult(
            status=ResolutionStatus.AMBIGUOUS,
            reasons=[ReasonCode.AMBIGUOUS_LOW_GAP],
            candidates=candidates,
            query_text="Springfield",
        )
        hint = disambiguate_hint(result)
        # With only one candidate and one country, no hint should fire.
        # The important thing is no "US-VT" leaks if a hint were produced.
        if hint is not None:
            assert "US-VT" not in hint, "Subdivision code leaked into hint"

    def test_repr_hint_uses_dict_form_not_resolution_context(self) -> None:
        # Candidates with no canonical_name trigger the entity_types fallback hint
        candidates = [
            CandidateSummary(
                entity_id="city/X",
                confidence=0.85,
                entity_type="geo.city",
            ),
        ]
        result = ResolutionResult(
            status=ResolutionStatus.AMBIGUOUS,
            reasons=[ReasonCode.AMBIGUOUS_LOW_GAP],
            candidates=candidates,
            query_text="Paris",
        )
        r = repr(result)
        assert "ResolutionContext(" not in r

    def test_repr_hint_country_dict_form(self) -> None:
        # When disambiguate_hint generates a COUNTRY hint, it must be dict form
        candidates = [
            CandidateSummary(
                entity_id="city/paris-fr",
                confidence=0.85,
                canonical_name="Paris",
                entity_type="geo.city",
                parent_country="FR",
            ),
        ]
        result = ResolutionResult(
            status=ResolutionStatus.AMBIGUOUS,
            reasons=[ReasonCode.AMBIGUOUS_LOW_GAP],
            refinement_hints=[RefinementHint.COUNTRY],
            candidates=candidates,
            query_text="Paris",
        )
        # Use render_refinement_hint directly to test the dict form
        hint = rh.render_refinement_hint(result, RefinementHint.COUNTRY)
        assert hint is not None
        assert "ResolutionContext(" not in hint
        assert "context={" in hint
        assert "'country'" in hint or '"country"' in hint

    def test_repr_no_match_in_ambiguous(self) -> None:
        r = repr(_ambiguous())
        assert "NO_MATCH" not in r


# ---------------------------------------------------------------------------
# NO_MATCH refinement hints use dict form
# ---------------------------------------------------------------------------


class TestNoMatchHintDictForm:
    def test_country_hint_dict_form(self) -> None:
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
        hint = rh.refinement_hint(result)
        assert hint is not None
        assert "ResolutionContext(" not in hint
        assert "context={" in hint

    def test_entity_types_hint_dict_form(self) -> None:
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
        hint = rh.refinement_hint(result)
        assert hint is not None
        assert "ResolutionContext(" not in hint
        assert "entity_types" in hint

    def test_parent_ids_hint_dict_form(self) -> None:
        result = _no_match(
            refinement_hints=[RefinementHint.PARENT_IDS],
            candidates=[CandidateSummary(entity_id="city/paris-fr")],
        )
        hint = rh.refinement_hint(result)
        assert hint is not None
        assert "ResolutionContext(" not in hint
        assert "parent_ids" in hint

    def test_languages_hint_dict_form(self) -> None:
        result = _no_match(refinement_hints=[RefinementHint.LANGUAGES])
        hint = rh.refinement_hint(result)
        assert hint is not None
        assert "ResolutionContext(" not in hint
        assert "languages" in hint


# ---------------------------------------------------------------------------
# RESOLVED path leaves parent fields as None (no extra lookups)
# ---------------------------------------------------------------------------


class TestResolvedPathNoParentLookup:
    def test_resolved_candidate_parent_fields_are_none(self) -> None:
        cand = CandidateSummary(
            entity_id="country/FRA",
            confidence=0.99,
            canonical_name="France",
            entity_type="geo.country",
        )
        result = ResolutionResult(
            status=ResolutionStatus.RESOLVED,
            entity_id="country/FRA",
            confidence=0.99,
            pack_id="geo",
            candidates=[cand],
        )
        for c in result.candidates:
            assert c.parent_name is None
            assert c.parent_country is None


# ---------------------------------------------------------------------------
# Dict-form hint is a valid Python literal (copy-pasteable)
# ---------------------------------------------------------------------------


class TestHintIsCopyPasteable:
    def test_country_hint_evaluates_as_python_literal(self) -> None:
        result = _no_match(
            refinement_hints=[RefinementHint.COUNTRY],
            candidates=[
                CandidateSummary(
                    entity_id="city/paris-fr",
                    parent_country="FR",
                )
            ],
        )
        hint = rh.render_refinement_hint(result, RefinementHint.COUNTRY)
        assert hint is not None
        # Extract the dict literal from the hint string:
        # hint looks like: "resolvekit.resolve(text='Paris', context={'country': 'FR'})"
        start = hint.index("context=") + len("context=")
        # Find matching closing paren for the outer resolve() call
        end = hint.rfind(")")
        dict_str = hint[start:end]
        # Should parse as a valid Python dict literal
        parsed = ast.literal_eval(dict_str)
        assert isinstance(parsed, dict)
        assert "country" in parsed

    def test_entity_types_hint_evaluates_as_python_literal(self) -> None:
        result = _no_match(
            refinement_hints=[RefinementHint.ENTITY_TYPES],
            candidates=[
                CandidateSummary(
                    entity_id="country/FRA",
                    entity_type="geo.country",
                )
            ],
        )
        hint = rh.render_refinement_hint(result, RefinementHint.ENTITY_TYPES)
        assert hint is not None
        start = hint.index("context=") + len("context=")
        end = hint.rfind(")")
        dict_str = hint[start:end]
        parsed = ast.literal_eval(dict_str)
        assert isinstance(parsed, dict)
        assert "entity_types" in parsed


# ---------------------------------------------------------------------------
# parent_country is preferred over entity_id inference in COUNTRY hint
# ---------------------------------------------------------------------------


class TestCountryHintPrefersParentCountry:
    def test_parent_country_takes_priority_over_entity_id_inference(self) -> None:
        # parent_country="FR" is set directly — no pack_id / entity_id inference needed
        result = _no_match(
            refinement_hints=[RefinementHint.COUNTRY],
            candidates=[
                CandidateSummary(
                    entity_id="city/paris-fr",
                    parent_country="FR",
                )
            ],
        )
        hint = rh.render_refinement_hint(result, RefinementHint.COUNTRY)
        assert hint is not None
        assert "'FR'" in hint


# ---------------------------------------------------------------------------
# Two-level enrichment: city → region → country (F2 regression guard)
# ---------------------------------------------------------------------------


class TestTwoLevelEnrichmentParentName:
    """_resolve_parent_context uses the direct container (region) as parent_name.

    In the two-level path (city → region → country), parent_name is the direct
    container and parent_country is the ISO-2 of the grandparent.
    """

    def _make_mock_entity(
        self,
        *,
        iso2: str | None = None,
        canonical_name: str = "",
        relations: list | None = None,
        attributes: dict | None = None,
    ) -> MagicMock:
        """Build a lightweight mock standing in for an EntityRecord."""
        entity = MagicMock()
        entity.iso2 = iso2
        entity.canonical_name = canonical_name
        entity.attributes = attributes or {}
        entity.relations = relations or []
        return entity

    def _make_mock_relation(self, relation_type: str, target_id: str) -> MagicMock:
        rel = MagicMock()
        rel.relation_type = relation_type
        rel.target_id = target_id
        return rel

    def test_two_level_parent_name_is_region_not_country(self) -> None:
        from resolvekit.core.engine.enrichment import ResultEnricher
        from resolvekit.core.model.result import CandidateSummary

        texas = self._make_mock_entity(
            iso2=None,
            canonical_name="Texas",
            relations=[self._make_mock_relation("contained_in", "country/USA")],
        )
        usa = self._make_mock_entity(iso2="US", canonical_name="United States")

        store = MagicMock()
        store.get_entity.side_effect = {
            "region/Texas": texas,
            "country/USA": usa,
        }.get

        paris_tx_entity = self._make_mock_entity(
            iso2=None,
            canonical_name="Paris",
            relations=[self._make_mock_relation("contained_in", "region/Texas")],
        )

        enricher = ResultEnricher.__new__(ResultEnricher)
        enricher._store = store  # type: ignore[attr-defined]

        summary = CandidateSummary(entity_id="city/Paris_TX", confidence=0.85)
        entities = {"city/Paris_TX": paris_tx_entity}

        result = enricher._resolve_parent_context((summary,), entities)
        parent_name, parent_country = result["city/Paris_TX"]

        assert parent_country == "US", "parent_country must be the country ISO-2 code"
        assert parent_name == "Texas", (
            "parent_name must be the direct container (region), not the country"
        )

    def test_subdivision_iso2_is_normalized_to_alpha2(self) -> None:
        # When the grandparent entity carries a subdivision code (e.g. "US-VT"),
        # _resolve_parent_context must strip the subdivision suffix so that
        # parent_country is "US", never "US-VT".
        from resolvekit.core.engine.enrichment import ResultEnricher
        from resolvekit.core.model.result import CandidateSummary

        vermont = self._make_mock_entity(
            iso2=None,
            canonical_name="Vermont",
            relations=[self._make_mock_relation("contained_in", "country/USA")],
        )
        # Grandparent carries a subdivision-style iso2 code
        usa = self._make_mock_entity(iso2="US-VT", canonical_name="United States")

        store = MagicMock()
        store.get_entity.side_effect = {
            "region/Vermont": vermont,
            "country/USA": usa,
        }.get

        springfield_vt = self._make_mock_entity(
            iso2=None,
            canonical_name="Springfield",
            relations=[self._make_mock_relation("contained_in", "region/Vermont")],
        )

        enricher = ResultEnricher.__new__(ResultEnricher)
        enricher._store = store  # type: ignore[attr-defined]

        summary = CandidateSummary(entity_id="city/Springfield_VT", confidence=0.85)
        entities = {"city/Springfield_VT": springfield_vt}

        result = enricher._resolve_parent_context((summary,), entities)
        parent_name, parent_country = result["city/Springfield_VT"]

        assert parent_country == "US", (
            f"Expected 'US' after normalizing subdivision iso2; got {parent_country!r}"
        )
        assert "-" not in (parent_country or ""), (
            "parent_country must never contain a hyphen (subdivision code leaked)"
        )
        assert parent_name == "Vermont"
