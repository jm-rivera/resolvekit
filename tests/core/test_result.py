"""Tests for ResolutionResult and related models."""

import pytest
from pydantic import ValidationError

from resolvekit.core.model.result import (
    CandidateEvidenceSummary,
    CandidateSummary,
    ReasonCode,
    RefinementHint,
    ResolutionResult,
    ResolutionResultList,
    ResolutionStatus,
)


class TestResolutionStatus:
    """Tests for ResolutionStatus enum."""

    def test_status_values(self):
        from resolvekit.core.model.result import ResolutionStatus

        assert ResolutionStatus.RESOLVED == "resolved"
        assert ResolutionStatus.AMBIGUOUS == "ambiguous"
        assert ResolutionStatus.NO_MATCH == "no_match"
        assert ResolutionStatus.ERROR == "error"


class TestReasonCode:
    """Tests for ReasonCode enum."""

    def test_reason_code_values(self):
        from resolvekit.core.model.result import ReasonCode

        # Should have key reason codes
        assert ReasonCode.NO_CANDIDATES == "no_candidates"
        assert ReasonCode.EXACT_CODE_MATCH == "exact_code_match"
        assert ReasonCode.AMBIGUOUS_LOW_GAP == "ambiguous_low_gap"
        assert ReasonCode.BELOW_CONFIDENCE_THRESHOLD == "below_confidence_threshold"
        assert ReasonCode.INVALID_QUERY == "invalid_query"
        assert ReasonCode.AMBIGUOUS_DOMAIN_COLLISION == "ambiguous_domain_collision"
        assert ReasonCode.CONTEXT_PARENT_CONFLICT == "context_parent_conflict"


class TestMatchTier:
    """Tests for MatchTier enum."""

    def test_match_tier_values(self):
        from resolvekit.core.model.result import MatchTier

        assert MatchTier.EXACT_CODE == "exact_code"
        assert MatchTier.EXACT_NAME == "exact_name"
        assert MatchTier.ACRONYM == "acronym"
        assert MatchTier.FTS == "fts"
        assert MatchTier.FUZZY == "fuzzy"
        assert MatchTier.FALLBACK == "fallback"


class TestRefinementHint:
    """Tests for RefinementHint enum."""

    def test_refinement_hint_values(self):
        from resolvekit.core.model.result import RefinementHint

        assert RefinementHint.ENTITY_TYPES == "entity_types"
        assert RefinementHint.PARENT_IDS == "parent_ids"
        assert RefinementHint.COUNTRY == "country"
        assert RefinementHint.LANGUAGES == "languages"


class TestCandidateSummary:
    """Tests for CandidateSummary model."""

    def test_create_candidate_summary(self):
        from resolvekit.core.model.result import (
            CandidateEvidenceSummary,
            CandidateSummary,
            MatchTier,
        )

        cs = CandidateSummary(
            entity_id="country/USA",
            confidence=0.95,
            top_evidence=[
                CandidateEvidenceSummary(
                    source_name="exact_code", matched_field="code.iso2"
                )
            ],
            key_features={"exact_code_hit": True},
            canonical_name="United States of America",
            entity_type="geo.country",
            pack_id="geo",
            match_tier=MatchTier.EXACT_CODE,
        )
        assert cs.entity_id == "country/USA"
        assert cs.confidence == 0.95
        assert len(cs.top_evidence) == 1
        assert cs.key_features["exact_code_hit"] is True
        assert cs.canonical_name == "United States of America"
        assert cs.entity_type == "geo.country"
        assert cs.pack_id == "geo"
        assert cs.match_tier == MatchTier.EXACT_CODE


class TestResolutionResult:
    """Tests for ResolutionResult model."""

    def test_create_resolved_result(self):
        from resolvekit.core.model.result import (
            CandidateSummary,
            MatchTier,
            ReasonCode,
            RefinementHint,
            ResolutionResult,
            ResolutionStatus,
        )

        result = ResolutionResult(
            status=ResolutionStatus.RESOLVED,
            entity_id="country/USA",
            confidence=0.97,
            pack_id="geo",
            match_tier=MatchTier.EXACT_CODE,
            candidates=[
                CandidateSummary(entity_id="country/USA", confidence=0.97),
            ],
            reasons=[ReasonCode.EXACT_CODE_MATCH],
            refinement_hints=[RefinementHint.COUNTRY],
        )
        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "country/USA"
        assert result.confidence == 0.97
        assert result.pack_id == "geo"
        assert result.match_tier == MatchTier.EXACT_CODE
        assert ReasonCode.EXACT_CODE_MATCH in result.reasons
        assert result.refinement_hints == [RefinementHint.COUNTRY]

    def test_create_no_match_result(self):
        from resolvekit.core.model.result import (
            ReasonCode,
            ResolutionResult,
            ResolutionStatus,
        )

        result = ResolutionResult(
            status=ResolutionStatus.NO_MATCH,
            reasons=[ReasonCode.NO_CANDIDATES],
        )
        assert result.status == ResolutionStatus.NO_MATCH
        assert result.entity_id is None
        assert result.confidence is None
        assert result.entity is None

    def test_create_ambiguous_result(self):
        from resolvekit.core.model.result import (
            CandidateSummary,
            ReasonCode,
            ResolutionResult,
            ResolutionStatus,
        )

        result = ResolutionResult(
            status=ResolutionStatus.AMBIGUOUS,
            candidates=[
                CandidateSummary(entity_id="city/Paris_FR", confidence=0.75),
                CandidateSummary(entity_id="city/Paris_TX", confidence=0.72),
            ],
            reasons=[ReasonCode.AMBIGUOUS_LOW_GAP],
        )
        assert result.status == ResolutionStatus.AMBIGUOUS
        assert len(result.candidates) == 2
        assert result.entity_id is None  # No single resolved entity

    def test_create_error_result(self):
        from resolvekit.core.model.result import (
            ReasonCode,
            ResolutionResult,
            ResolutionStatus,
        )

        result = ResolutionResult(
            status=ResolutionStatus.ERROR,
            reasons=[ReasonCode.STORE_ERROR],
        )
        assert result.status == ResolutionStatus.ERROR

    def test_result_explicit_status_required(self):
        """Result must have explicit status - no None allowed."""
        with pytest.raises(ValidationError):
            ResolutionResult(status=None)  # type: ignore

    def test_query_text_field_defaults_none(self):
        result = ResolutionResult(status=ResolutionStatus.NO_MATCH)
        assert result.query_text is None

    def test_query_text_stored(self):
        result = ResolutionResult(
            status=ResolutionStatus.AMBIGUOUS,
            query_text="Paris",
        )
        assert result.query_text == "Paris"

    def test_repr_ambiguous_with_query_text(self):
        result = ResolutionResult(
            status=ResolutionStatus.AMBIGUOUS,
            query_text="Paris",
            candidates=[
                CandidateSummary(
                    entity_id="city/Paris_FR",
                    confidence=0.75,
                    entity_type="geo.city",
                    canonical_name="Paris, France",
                ),
                CandidateSummary(
                    entity_id="city/Paris_TX",
                    confidence=0.72,
                    entity_type="geo.city",
                    canonical_name="Paris, Texas",
                ),
            ],
        )
        r = repr(result)
        assert "AMBIGUOUS" in r
        assert "resolvekit.resolve" in r
        assert "Paris" in r

    def test_repr_ambiguous_without_query_text(self):
        result = ResolutionResult(
            status=ResolutionStatus.AMBIGUOUS,
            candidates=[
                CandidateSummary(entity_id="city/Paris_FR", confidence=0.75),
            ],
        )
        r = repr(result)
        assert "ResolutionResult(status='ambiguous'" in r
        assert "candidates=1" in r


class TestDisambiguateHint:
    """Tests for the AMBIGUOUS repr disambiguation hint.

    The hint must be a *proven* fix: it should either narrow the candidate
    set to one entity, or suggest exact-name selectors for each candidate.
    Suggesting an entity_types narrowing that wouldn't reduce the set is a
    credibility bug — the user runs the suggestion and gets the same result.
    """

    def test_same_type_candidates_use_exact_name_selectors(self):
        """When all candidates share an entity_type, narrowing by type would
        not reduce the set. The hint must offer exact-name selectors instead.
        """
        result = ResolutionResult(
            status=ResolutionStatus.AMBIGUOUS,
            query_text="Korea",
            candidates=[
                CandidateSummary(
                    entity_id="country/KOR",
                    canonical_name="South Korea",
                    entity_type="geo.country",
                ),
                CandidateSummary(
                    entity_id="country/PRK",
                    canonical_name="North Korea",
                    entity_type="geo.country",
                ),
            ],
        )
        r = repr(result)
        assert "resolvekit.resolve(text='South Korea')" in r
        assert "resolvekit.resolve(text='North Korea')" in r
        assert "entity_types" not in r

    def test_distinct_canonical_names_preferred_even_with_split_types(self):
        """When candidates have canonical names, prefer exact-name selectors
        — they're maximally precise and avoid filtering out the entities the
        user most likely wants by accident."""
        result = ResolutionResult(
            status=ResolutionStatus.AMBIGUOUS,
            query_text="Korea",
            candidates=[
                CandidateSummary(
                    entity_id="country/KOR",
                    canonical_name="South Korea",
                    entity_type="geo.country",
                ),
                CandidateSummary(
                    entity_id="country/PRK",
                    canonical_name="North Korea",
                    entity_type="geo.country",
                ),
                CandidateSummary(
                    entity_id="region/koreas",
                    canonical_name="Both Koreas",
                    entity_type="geo.region",
                ),
            ],
        )
        r = repr(result)
        assert "South Korea" in r
        assert "North Korea" in r
        assert "Both Koreas" in r

    def test_canonical_name_matching_query_is_skipped(self):
        """An exact-name selector that matches the original query would just
        loop back to the same ambiguous result, so it's filtered out."""
        result = ResolutionResult(
            status=ResolutionStatus.AMBIGUOUS,
            query_text="Foo",
            candidates=[
                CandidateSummary(entity_id="a", canonical_name="Foo"),
                CandidateSummary(entity_id="b", canonical_name="Foo Bar"),
            ],
        )
        r = repr(result)
        assert "resolvekit.resolve(text='Foo Bar')" in r
        assert "resolvekit.resolve(text='Foo')" not in r

    def test_type_narrowing_only_when_no_canonical_names(self):
        """When no canonical names are available, fall back to a type
        narrowing — but only if filtering by a single type would reduce
        the candidate set to one."""
        result = ResolutionResult(
            status=ResolutionStatus.AMBIGUOUS,
            query_text="Foo",
            candidates=[
                CandidateSummary(entity_id="a", entity_type="geo.country"),
                CandidateSummary(entity_id="b", entity_type="geo.country"),
                CandidateSummary(entity_id="c", entity_type="geo.region"),
            ],
        )
        r = repr(result)
        assert "entity_types={'geo.region'}" in r

    def test_no_disambiguator_when_same_type_no_names(self):
        """If candidates share a single entity_type and have no canonical
        names, no narrowing helps — fall back to the generic candidate-count
        repr rather than printing a misleading suggestion."""
        result = ResolutionResult(
            status=ResolutionStatus.AMBIGUOUS,
            query_text="Foo",
            candidates=[
                CandidateSummary(entity_id="a", entity_type="geo.country"),
                CandidateSummary(entity_id="b", entity_type="geo.country"),
            ],
        )
        r = repr(result)
        assert "AMBIGUOUS — try" not in r
        assert "candidates=2" in r


class TestRefinementHintDIDYouMean:
    def test_did_you_mean_value(self):
        assert RefinementHint.DID_YOU_MEAN == "did_you_mean"


class TestReasonCodeTimeout:
    def test_timeout_value(self):
        assert ReasonCode.TIMEOUT == "timeout"


class TestCandidateSummaryRepr:
    def test_repr_with_all_fields(self):
        cs = CandidateSummary(
            entity_id="country/USA",
            confidence=0.95,
            pack_id="geo",
            top_evidence=[
                CandidateEvidenceSummary(
                    source_name="exact_code", matched_field="code.iso2"
                )
            ],
        )
        r = repr(cs)
        assert r == "CandidateSummary('country/USA', conf=0.95 [geo] (1 evidence))"

    def test_repr_no_confidence(self):
        cs = CandidateSummary(entity_id="country/USA")
        r = repr(cs)
        assert "conf=?" in r

    def test_repr_no_pack(self):
        cs = CandidateSummary(entity_id="country/USA", confidence=0.80)
        r = repr(cs)
        assert "[" not in r

    def test_repr_no_evidence(self):
        cs = CandidateSummary(entity_id="country/USA", confidence=0.80)
        r = repr(cs)
        assert "evidence" not in r


class TestResolutionResultList:
    def test_empty_list(self):
        rrl = ResolutionResultList()
        assert len(rrl) == 0
        assert repr(rrl) == "ResolutionResultList(0 results, 0 resolved)"

    def test_repr_counts(self):
        rrl = ResolutionResultList(
            [
                ResolutionResult(
                    status=ResolutionStatus.RESOLVED,
                    entity_id="a",
                    confidence=0.9,
                    pack_id="geo",
                ),
                ResolutionResult(status=ResolutionStatus.NO_MATCH),
                ResolutionResult(status=ResolutionStatus.AMBIGUOUS),
            ]
        )
        assert repr(rrl) == "ResolutionResultList(3 results, 1 resolved)"

    def test_resolved_property(self):
        rrl = ResolutionResultList(
            [
                ResolutionResult(
                    status=ResolutionStatus.RESOLVED,
                    entity_id="a",
                    confidence=0.9,
                    pack_id="geo",
                ),
                ResolutionResult(status=ResolutionStatus.NO_MATCH),
            ]
        )
        resolved = rrl.resolved
        assert isinstance(resolved, ResolutionResultList)
        assert len(resolved) == 1
        assert resolved[0].entity_id == "a"

    def test_entity_ids_property(self):
        rrl = ResolutionResultList(
            [
                ResolutionResult(
                    status=ResolutionStatus.RESOLVED,
                    entity_id="country/USA",
                    confidence=0.9,
                    pack_id="geo",
                ),
                ResolutionResult(status=ResolutionStatus.NO_MATCH),
            ]
        )
        assert rrl.entity_ids == ["country/USA", None]

    def test_statuses_property(self):
        rrl = ResolutionResultList(
            [
                ResolutionResult(
                    status=ResolutionStatus.RESOLVED,
                    entity_id="a",
                    confidence=0.9,
                    pack_id="geo",
                ),
                ResolutionResult(status=ResolutionStatus.NO_MATCH),
            ]
        )
        assert rrl.statuses == [ResolutionStatus.RESOLVED, ResolutionStatus.NO_MATCH]

    def test_repr_html_returns_table(self):
        rrl = ResolutionResultList(
            [
                ResolutionResult(
                    status=ResolutionStatus.RESOLVED,
                    entity_id="country/USA",
                    confidence=0.9,
                    pack_id="geo",
                ),
            ]
        )
        html = rrl._repr_html_()
        assert "<table" in html
        assert "country/USA" in html
        assert "resolved" in html

    def test_list_operations(self):
        r1 = ResolutionResult(
            status=ResolutionStatus.RESOLVED,
            entity_id="a",
            confidence=0.9,
            pack_id="geo",
        )
        r2 = ResolutionResult(status=ResolutionStatus.NO_MATCH)
        rrl = ResolutionResultList([r1])
        rrl.append(r2)
        assert len(rrl) == 2
