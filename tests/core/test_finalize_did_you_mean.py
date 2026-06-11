"""Characterization tests for _finalize_result two-pass DID_YOU_MEAN suppression.

Pins the invariant: when did_you_mean_active=True (spelling suggestions found),
the second _derive_refinement_hints call is skipped — call-count == 1.
When no suggestions are found, did_you_mean_active stays False and
the second call runs — call-count == 2.
"""

from resolvekit.core.engine.decision import ThresholdDecisionPolicy
from resolvekit.core.engine.interfaces import CandidateSource
from resolvekit.core.engine.runner import PipelineRunner
from resolvekit.core.model import (
    Candidate,
    CandidateEvidence,
    GenerationContext,
    Query,
    ReasonCode,
    RefinementHint,
    ResolutionContext,
    ResolutionResult,
    ResolutionStatus,
)
from resolvekit.core.model.entity import EntityRecord
from resolvekit.core.store import EntityStore
from tests.conftest import MockEntityStore, make_query

# ---------------------------------------------------------------------------
# Local stubs (re-declared; not re-exported from test_did_you_mean.py)
# ---------------------------------------------------------------------------


class _SpellingSuggestion:
    """Minimal stand-in for symspellpy's SuggestItem."""

    def __init__(self, term: str, distance: int = 1) -> None:
        self.term = term
        self.distance = distance


class _MockSpellSource(CandidateSource):
    """A CandidateSource that returns no retrieval candidates but exposes
    spelling_suggestions, allowing the test to control whether DID_YOU_MEAN fires.
    """

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


def _make_entity(entity_id: str, name: str = "Some Entity") -> EntityRecord:
    return EntityRecord(
        entity_id=entity_id,
        entity_type="geo.country",
        canonical_name=name,
        canonical_name_norm=name.lower(),
    )


def _no_match_result() -> ResolutionResult:
    return ResolutionResult(
        status=ResolutionStatus.NO_MATCH,
        reasons=[ReasonCode.NO_CANDIDATES],
    )


# ---------------------------------------------------------------------------
# Spy subclass: counts _derive_refinement_hints calls
# ---------------------------------------------------------------------------


class _SpyRunner(PipelineRunner):
    """PipelineRunner subclass that counts calls to _derive_refinement_hints."""

    def __init__(
        self,
        store: "EntityStore | None" = None,
        sources: "list[CandidateSource] | None" = None,
    ) -> None:
        super().__init__(
            store=store,  # type: ignore[arg-type]
            sources=sources,
            decision_policy=ThresholdDecisionPolicy(
                confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
            ),
        )
        self.hint_call_count = 0

    def _derive_refinement_hints(  # type: ignore[override]
        self,
        result: ResolutionResult,
        close_candidates: list[Candidate],
        entities: dict[str, EntityRecord],
        context: ResolutionContext,
        query: Query | None = None,
    ) -> list[RefinementHint]:
        self.hint_call_count += 1
        return super()._derive_refinement_hints(
            result=result,
            close_candidates=close_candidates,
            entities=entities,
            context=context,
            query=query,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFinalizeTwoPass:
    """Pins the two-pass _derive_refinement_hints call-count invariant."""

    def test_did_you_mean_active_suppresses_second_hint_pass(self) -> None:
        """When DID_YOU_MEAN fires (suggestions found), call #2 is skipped → count == 1.

        Also asserts that DID_YOU_MEAN hint survives in the output and that
        spelling-suggestion candidates are attached to the result.
        """
        store = MockEntityStore(
            entities={"country/USA": _make_entity("country/USA", "United States")},
            names={"united states": ["country/USA"]},
        )
        suggestions = [_SpellingSuggestion("united states", distance=1)]
        source = _MockSpellSource("mock_spell", suggestions)
        runner = _SpyRunner(store=store, sources=[source])

        finalized = runner._finalize_result(
            result=_no_match_result(),
            final_candidates=None,
            context=ResolutionContext(),
            query=make_query("untied sttas"),
        )

        assert runner.hint_call_count == 1, (
            f"expected 1 _derive_refinement_hints call when did_you_mean_active=True, "
            f"got {runner.hint_call_count}"
        )
        assert RefinementHint.DID_YOU_MEAN in finalized.refinement_hints
        assert len(finalized.candidates) >= 1
        assert finalized.candidates[0].entity_id == "country/USA"

    def test_no_suggestions_runs_second_hint_pass(self) -> None:
        """When no suggestions are found, did_you_mean_active stays False → count == 2."""
        store = MockEntityStore(entities={}, names={})
        source = _MockSpellSource("mock_spell", suggestions=[])
        runner = _SpyRunner(store=store, sources=[source])

        runner._finalize_result(
            result=_no_match_result(),
            final_candidates=None,
            context=ResolutionContext(),
            query=make_query("gost cuntry"),
        )

        assert runner.hint_call_count == 2, (
            f"expected 2 _derive_refinement_hints calls when did_you_mean_active=False, "
            f"got {runner.hint_call_count}"
        )
