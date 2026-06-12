"""Unit tests for FuzzyRetrievalBruteSource.

Covers: typo evidence shape, short-input gates, cap, memoization, warm(),
store-error degradation, and the backward-compatible choices= param on
fuzzy_candidates.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

from resolvekit.core.engine.suggest_rank import fuzzy_candidates
from resolvekit.core.explain import NullTraceSink
from resolvekit.core.model import (
    GenerationContext,
    MatchTier,
    NormalizedText,
    Query,
    ResolutionContext,
)
from resolvekit.core.store import EntityStore
from resolvekit.shared.sources.fuzzy_retrieval_brute_base import (
    FuzzyRetrievalBruteSource,
)

# ---------------------------------------------------------------------------
# Stub store
# ---------------------------------------------------------------------------


class _StubStore(EntityStore):
    """Minimal stub: returns a fixed name list from iter_suggest_names."""

    def __init__(
        self,
        names: list[tuple[str, str, str, bool, str]],
    ) -> None:
        self._names = names
        # Counts calls to iter_suggest_names so memoization tests can spy.
        self.iter_suggest_names_call_count = 0

    def iter_suggest_names(
        self,
        *,
        entity_type_prefixes=None,
        entity_type_exclude_prefixes=None,
    ) -> Iterator[tuple[str, str, str, bool, str]]:
        self.iter_suggest_names_call_count += 1
        yield from self._names

    # EntityStore ABC stubs -----------------------------------------------
    def get_entity(self, entity_id):
        return None

    def lookup_code(self, system, value_norm):
        return []

    def lookup_name_exact(self, value_norm, name_kinds=None):
        return []

    def search_fulltext(self, query_norm, fields=None, limit=10):
        return []

    def bulk_get_entities(self, entity_ids):
        return {}


class _RaisingStore(_StubStore):
    """Like _StubStore but iter_suggest_names raises NotImplementedError."""

    def iter_suggest_names(
        self, *, entity_type_prefixes=None, entity_type_exclude_prefixes=None
    ):
        raise NotImplementedError("store does not support enumeration")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# 5-tuple shape: (value_norm, entity_id, name_kind, is_preferred, value)
_ANDEAN_ROW = ("andean water trust", "A5", "canonical", True, "Andean Water Trust")
_RIVERBEND_ROW = (
    "riverbend foundation",
    "A2",
    "canonical",
    True,
    "Riverbend Foundation",
)
_ROWS_2 = [_ANDEAN_ROW, _RIVERBEND_ROW]


def _make_ctx(query: str, store: EntityStore) -> GenerationContext:
    return GenerationContext(
        query=Query(
            raw_text=query,
            normalized=NormalizedText(original=query, normalized=query),
        ),
        context=ResolutionContext(),
        store=store,
        budget=25,
        trace=NullTraceSink(),
    )


def _make_source(**kwargs) -> FuzzyRetrievalBruteSource:
    defaults = {"name": "test_fuzzy_retrieval", "domain": "custom"}
    defaults.update(kwargs)
    return FuzzyRetrievalBruteSource(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTypoEvidence:
    def test_typo_query_yields_evidence_for_correct_entity(self) -> None:
        store = _StubStore(_ROWS_2)
        source = _make_source()
        ctx = _make_ctx("andean watr trust", store)

        evidence = source.generate(ctx)

        assert len(evidence) >= 1
        # The closest match must be A5 (Andean Water Trust)
        eid = evidence[0].entity_id
        assert eid == "A5"

    def test_match_tier_is_fuzzy(self) -> None:
        store = _StubStore(_ROWS_2)
        source = _make_source()
        ctx = _make_ctx("andean watr trust", store)

        evidence = source.generate(ctx)

        assert evidence, "expected at least one evidence entry"
        for ev in evidence:
            assert ev.match_tier == MatchTier.FUZZY

    def test_raw_score_in_range(self) -> None:
        store = _StubStore(_ROWS_2)
        source = _make_source()
        ctx = _make_ctx("andean watr trust", store)

        evidence = source.generate(ctx)

        assert evidence, "expected at least one evidence entry"
        for ev in evidence:
            assert ev.raw_score is not None
            assert 0.0 < ev.raw_score <= 1.0

    def test_matched_value_is_original_cased(self) -> None:
        store = _StubStore(_ROWS_2)
        source = _make_source()
        ctx = _make_ctx("andean watr trust", store)

        evidence = source.generate(ctx)

        assert evidence
        # matched_value must be the original-cased string, not the norm
        matched = {ev.matched_value for ev in evidence}
        assert "Andean Water Trust" in matched

    def test_source_name_stamped(self) -> None:
        store = _StubStore(_ROWS_2)
        source = _make_source(name="my_fuzzy")
        ctx = _make_ctx("andean watr trust", store)

        evidence = source.generate(ctx)

        assert evidence
        assert all(ev.source_name == "my_fuzzy" for ev in evidence)


class TestShortInputGates:
    def test_min_length_gate_two_chars_returns_empty(self) -> None:
        store = _StubStore(_ROWS_2)
        source = _make_source(min_query_length=3)
        ctx = _make_ctx("ab", store)

        assert source.generate(ctx) == []

    def test_degenerate_na_returns_empty(self) -> None:
        store = _StubStore(_ROWS_2)
        source = _make_source()
        assert source.generate(_make_ctx("NA", store)) == []

    def test_degenerate_hash_na_returns_empty(self) -> None:
        store = _StubStore(_ROWS_2)
        source = _make_source()
        assert source.generate(_make_ctx("#N/A", store)) == []

    def test_degenerate_double_dash_returns_empty(self) -> None:
        store = _StubStore(_ROWS_2)
        source = _make_source()
        assert source.generate(_make_ctx("--", store)) == []

    def test_single_lowercase_letter_returns_empty(self) -> None:
        store = _StubStore(_ROWS_2)
        source = _make_source()
        assert source.generate(_make_ctx("x", store)) == []

    def test_single_uppercase_letter_returns_empty(self) -> None:
        # Single letter, any case, should be blocked.
        store = _StubStore(_ROWS_2)
        source = _make_source()
        assert source.generate(_make_ctx("A", store)) == []


class TestCapCheck:
    def test_cap_exceeded_returns_empty(self) -> None:
        # max_names=1 but store has 2 rows → skip brute-force.
        store = _StubStore(_ROWS_2)
        source = _make_source(max_names=1)
        ctx = _make_ctx("andean watr trust", store)

        assert source.generate(ctx) == []

    def test_cap_at_limit_still_runs(self) -> None:
        # max_names=2, store has exactly 2 rows → runs.
        store = _StubStore(_ROWS_2)
        source = _make_source(max_names=2)
        ctx = _make_ctx("andean watr trust", store)

        evidence = source.generate(ctx)
        assert len(evidence) >= 1


class TestMemoization:
    def test_iter_suggest_names_called_once_across_two_generate_calls(self) -> None:
        store = _StubStore(_ROWS_2)
        source = _make_source()
        ctx = _make_ctx("andean watr trust", store)

        source.generate(ctx)
        source.generate(ctx)

        assert store.iter_suggest_names_call_count == 1

    def test_memoization_across_generate_calls(self) -> None:
        """Two generate() calls must call iter_suggest_names exactly once.

        warm() is a no-op (CandidateSource.warm() has no store param), so the
        cache is built on the first generate() call and reused on subsequent ones.
        """
        store = _StubStore(_ROWS_2)
        source = _make_source()
        ctx = _make_ctx("andean watr trust", store)

        # First generate builds the cache.
        source.generate(ctx)
        assert store.iter_suggest_names_call_count == 1

        # Second generate must not re-build.
        source.generate(ctx)
        assert store.iter_suggest_names_call_count == 1

    def test_warm_is_noop(self) -> None:
        """warm() must not populate the cache (no store reference is available).

        The real build happens on the first generate() call; warm() on the base
        CandidateSource interface has no store parameter, so it cannot pre-build.
        """
        source = _make_source()

        source.warm()

        assert source._names_cache is None
        assert source._choices_cache is None
        assert not source._built

    def test_cache_is_populated_after_first_generate(self) -> None:
        store = _StubStore(_ROWS_2)
        source = _make_source()
        ctx = _make_ctx("andean watr trust", store)

        source.generate(ctx)

        assert source._names_cache is not None
        assert source._choices_cache is not None
        assert len(source._names_cache) == 2
        assert len(source._choices_cache) == 2


class TestStoreError:
    def test_raising_store_returns_empty_no_raise(self) -> None:
        store = _RaisingStore([])
        source = _make_source()
        ctx = _make_ctx("andean watr trust", store)

        # Must not raise; must return [].
        result = source.generate(ctx)
        assert result == []

    def test_generate_never_raises_on_unexpected_exception(self) -> None:
        store = _StubStore(_ROWS_2)
        source = _make_source()
        ctx = _make_ctx("andean watr trust", store)

        # Monkey-patch fuzzy_candidates to raise an unexpected error.
        with patch(
            "resolvekit.shared.sources.fuzzy_retrieval_brute_base.fuzzy_candidates",
            side_effect=RuntimeError("unexpected"),
        ):
            result = source.generate(ctx)

        assert result == []


class TestChoicesParam:
    """The additive choices= param on fuzzy_candidates is behavior-preserving."""

    def test_choices_param_same_result_as_without(self) -> None:
        names = _ROWS_2
        choices = [row[0] for row in names]

        result_without = fuzzy_candidates(
            "andean watr trust",
            names,
            top_k=10,
        )
        result_with = fuzzy_candidates(
            "andean watr trust",
            names,
            top_k=10,
            choices=choices,
        )

        assert len(result_without) == len(result_with)
        for a, b in zip(result_without, result_with, strict=True):
            assert a.entity_id == b.entity_id
            assert a.match_score == b.match_score
            assert a.matched_value == b.matched_value

    def test_choices_none_is_backward_compatible(self) -> None:
        """Calling without choices= (None default) must work as before."""
        names = _ROWS_2
        result = fuzzy_candidates("andean watr trust", names, top_k=10, choices=None)
        assert len(result) >= 1
