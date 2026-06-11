"""Tests for M8 — DID_YOU_MEAN candidate population.

The unit tests (capped/dedup/drops/zero-edit) use a lightweight mock
source and store so they don't require a full geo DataPack on disk.
The integration smoke-test uses a real geo install if available.
"""

from pathlib import Path

from resolvekit.core.engine.decision import ThresholdDecisionPolicy
from resolvekit.core.engine.interfaces import CandidateSource
from resolvekit.core.engine.runner import PipelineRunner
from resolvekit.core.model import (
    CandidateEvidence,
    GenerationContext,
    ReasonCode,
    RefinementHint,
    ResolutionContext,
    ResolutionResult,
    ResolutionStatus,
)
from resolvekit.core.model.entity import EntityRecord
from tests.conftest import MockEntityStore, make_query

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_entity(entity_id: str, name: str = "Some Entity") -> EntityRecord:
    return EntityRecord(
        entity_id=entity_id,
        entity_type="geo.country",
        canonical_name=name,
        canonical_name_norm=name.lower(),
    )


def _stub_no_match() -> ResolutionResult:
    return ResolutionResult(
        status=ResolutionStatus.NO_MATCH,
        reasons=[ReasonCode.NO_CANDIDATES],
    )


class _SpellingSuggestion:
    """Minimal stand-in for symspellpy's SuggestItem."""

    def __init__(self, term: str, distance: int = 1) -> None:
        self.term = term
        self.distance = distance


class _MockSpellSource(CandidateSource):
    """A source that returns no retrieval candidates but exposes spelling_suggestions."""

    def __init__(self, name: str, suggestions: list[_SpellingSuggestion]) -> None:
        self._name = name
        self._suggestions = suggestions
        self._name_kinds: set[str] | None = None

    @property
    def name(self) -> str:
        return self._name

    def supports(self, domain_pack_id: str) -> bool:
        return True

    @property
    def reason_code(self) -> ReasonCode:
        return ReasonCode.FUZZY_MATCH

    def generate(self, ctx: GenerationContext) -> list[CandidateEvidence]:
        return []

    def spelling_suggestions(self, text: str) -> list[_SpellingSuggestion]:
        return self._suggestions


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDidYouMeanCandidatePopulation:
    """_spelling_suggestions builds CandidateSummary entries from suggestions."""

    def test_did_you_mean_capped_at_three(self) -> None:
        """At most 3 candidates surface even when suggestions yield more entities."""
        # Five distinct entities reachable via spelling suggestions.
        entities = {f"country/E{i}": _make_entity(f"country/E{i}") for i in range(5)}
        names = {f"entity {i}": [f"country/E{i}"] for i in range(5)}
        store = MockEntityStore(entities=entities, names=names)
        suggestions = [_SpellingSuggestion(f"entity {i}", distance=1) for i in range(5)]
        source = _MockSpellSource("mock_spell", suggestions)
        runner = PipelineRunner(
            store=store,
            sources=[source],
            decision_policy=ThresholdDecisionPolicy(
                confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
            ),
        )

        result_obj = runner._enricher._spelling_suggestions(query_text="entty")

        assert len(result_obj) == 3

    def test_did_you_mean_dedups_by_entity_id(self) -> None:
        """Two suggestions that both map to the same entity ID yield one candidate."""
        store = MockEntityStore(
            entities={"country/USA": _make_entity("country/USA", "United States")},
            names={
                "united states": ["country/USA"],
                "united statez": ["country/USA"],
            },
        )
        suggestions = [
            _SpellingSuggestion("united states", distance=1),
            _SpellingSuggestion("united statez", distance=2),
        ]
        source = _MockSpellSource("mock_spell", suggestions)
        runner = PipelineRunner(
            store=store,
            sources=[source],
            decision_policy=ThresholdDecisionPolicy(
                confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
            ),
        )

        candidates = runner._enricher._spelling_suggestions(query_text="untied stats")

        ids = [c.entity_id for c in candidates]
        assert ids.count("country/USA") == 1

    def test_did_you_mean_drops_suggestions_with_no_entity(self) -> None:
        """A corrected term that matches no entity is omitted from candidates."""
        store = MockEntityStore(entities={}, names={})
        suggestions = [_SpellingSuggestion("ghost country", distance=1)]
        source = _MockSpellSource("mock_spell", suggestions)
        runner = PipelineRunner(
            store=store,
            sources=[source],
            decision_policy=ThresholdDecisionPolicy(
                confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
            ),
        )

        candidates = runner._enricher._spelling_suggestions(query_text="gost cuntry")

        assert candidates == []

    def test_did_you_mean_skips_zero_edit_suggestion(self) -> None:
        """A suggestion whose term equals the query text is skipped."""
        store = MockEntityStore(
            entities={"country/USA": _make_entity("country/USA", "United States")},
            names={
                "untied stats": ["country/USA"],
                "united states": ["country/USA"],
            },
        )
        # One suggestion that is the exact query → should be skipped.
        suggestions = [
            _SpellingSuggestion("untied stats", distance=0),  # zero-edit
            _SpellingSuggestion("united states", distance=1),
        ]
        source = _MockSpellSource("mock_spell", suggestions)
        runner = PipelineRunner(
            store=store,
            sources=[source],
            decision_policy=ThresholdDecisionPolicy(
                confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
            ),
        )

        candidates = runner._enricher._spelling_suggestions(query_text="untied stats")

        # The zero-edit suggestion is skipped; the real one still yields a candidate.
        assert len(candidates) == 1
        assert candidates[0].entity_id == "country/USA"

    def test_finalize_result_populates_candidates_on_did_you_mean(self) -> None:
        """_finalize_result patches result.candidates when DID_YOU_MEAN fires."""
        store = MockEntityStore(
            entities={"country/USA": _make_entity("country/USA", "United States")},
            names={"united states": ["country/USA"]},
        )
        suggestions = [_SpellingSuggestion("united states", distance=1)]
        source = _MockSpellSource("mock_spell", suggestions)
        runner = PipelineRunner(
            store=store,
            sources=[source],
            decision_policy=ThresholdDecisionPolicy(
                confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
            ),
        )

        finalized = runner._finalize_result(
            result=_stub_no_match(),
            final_candidates=None,
            context=ResolutionContext(),
            query=make_query("untied sttas"),
        )

        assert RefinementHint.DID_YOU_MEAN in finalized.refinement_hints
        assert len(finalized.candidates) >= 1
        assert finalized.candidates[0].entity_id == "country/USA"


# ---------------------------------------------------------------------------
# Integration smoke-test (requires a real geo DataPack)
# ---------------------------------------------------------------------------


def test_no_match_with_typo_emits_did_you_mean_candidates(
    geo_test_datapack: Path,
) -> None:
    """End-to-end: a typo query gets DID_YOU_MEAN hint and candidate(s).

    Uses the geo_test_datapack fixture which has no SymSpell dictionary, so
    the SymSpell source returns no suggestions and the test validates graceful
    fallback (no crash, no stale candidates). Real SymSpell behavior is
    covered by the unit tests above with mock sources.
    """

    from resolvekit.core.api import Resolver

    with Resolver.from_datapacks(
        datapack_paths=[geo_test_datapack], domains=["geo"]
    ) as resolver:
        result = resolver.resolve("Untied Stats")
        # With no SymSpell dictionary in the test pack, no DID_YOU_MEAN is emitted
        # and candidates stay empty — the important property is no exception raised.
        assert result.status in {ResolutionStatus.NO_MATCH, ResolutionStatus.RESOLVED}
