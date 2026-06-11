"""Tests for pipeline stage module functions in core.engine._stages.

Each test calls a stage function directly with constructed inputs to verify
its behavior. All tests MUST pass against the current code: a failure means
the test mis-states what the code does — fix the test, not _stages.py.
"""

import time
from collections import defaultdict

import pytest

from resolvekit.core.engine import _stages
from resolvekit.core.engine.config import PipelineConfig, StopCondition
from resolvekit.core.engine.decision import ThresholdDecisionPolicy
from resolvekit.core.engine.interfaces import CandidateSource
from resolvekit.core.engine.tier_utils import DEFAULT_FALLBACK_SCORE
from resolvekit.core.explain import NullTraceSink
from resolvekit.core.model import (
    Candidate,
    CandidateEvidence,
    GenerationContext,
    MatchTier,
    NormalizedText,
    Query,
    ResolutionContext,
    RetrievalSummary,
    ScoreSummary,
)
from resolvekit.core.store import EntityStore

# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


class _MockStore(EntityStore):
    """Minimal store: stage functions under test don't read entity data; only
    the store reference itself is needed for GenerationContext."""

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


def _make_runner(*, sources=None, store=None, config=None):
    """Build a minimal PipelineRunner — used only for its config/budget attributes
    when constructing explicit stage-function arguments."""
    from resolvekit.core.engine.runner import PipelineRunner

    return PipelineRunner(
        trace_sink=NullTraceSink(),
        store=store,
        sources=sources or [],
        decision_policy=ThresholdDecisionPolicy(
            confidence_threshold=0.8,
            min_gap=0.1,
            gap_inclusive=True,
        ),
        config=config,
    )


def _ev(
    entity_id,
    *,
    source_name="src",
    raw_score=None,
    rank=None,
    signals=None,
    match_tier=None,
) -> CandidateEvidence:
    """Build a CandidateEvidence for test inputs."""
    return CandidateEvidence(
        entity_id=entity_id,
        source_name=source_name,
        raw_score=raw_score,
        rank=rank,
        signals=signals or {},
        match_tier=match_tier,
    )


def _candidate(
    entity_id,
    *,
    sources,
    best_raw_score=None,
    best_source="src",
    best_rank=None,
    signals=None,
) -> Candidate:
    """Build a Candidate with a minimal valid shape."""
    placeholder = (
        best_raw_score if best_raw_score is not None else DEFAULT_FALLBACK_SCORE
    )
    return Candidate(
        entity_id=entity_id,
        sources=sources,
        retrieval=RetrievalSummary(
            best_source=best_source,
            best_rank=best_rank,
            best_raw_score=best_raw_score,
            signals=signals or {},
        ),
        scores=ScoreSummary(
            raw_score=placeholder,
            calibrated_score=min(max(placeholder, 0.0), 1.0),
        ),
    )


_QUERY = Query(
    raw_text="test",
    normalized=NormalizedText(original="test", normalized="test"),
)
_CONTEXT = ResolutionContext()


class _StaticSource(CandidateSource):
    """Returns a fixed evidence list; supports configuring reranker flag and tier."""

    def __init__(self, name, evidence, *, reranker=False, tier=None):
        self._name = name
        self._evidence = evidence
        self._reranker = reranker
        self._tier = tier

    @property
    def name(self):
        return self._name

    @property
    def requires_existing_candidates(self):
        return self._reranker

    @property
    def tier(self):
        return self._tier

    def supports(self, domain_pack_id):
        return True

    def generate(self, ctx: GenerationContext):
        return list(self._evidence)


class _RecordingSource(CandidateSource):
    """Appends to a caller-supplied list on generate() to detect whether it ran."""

    def __init__(self, name, calls, *, reranker=False, tier=None, evidence=None):
        self._name = name
        self._calls = calls
        self._reranker = reranker
        self._tier = tier
        self._evidence = evidence or []

    @property
    def name(self):
        return self._name

    @property
    def requires_existing_candidates(self):
        return self._reranker

    @property
    def tier(self):
        return self._tier

    def supports(self, domain_pack_id):
        return True

    def generate(self, ctx: GenerationContext):
        self._calls.append(self._name)
        return list(self._evidence)


# ---------------------------------------------------------------------------
# run_primary_sources
# ---------------------------------------------------------------------------


class TestRunPrimarySources:
    """Behaviors 1-5: run_primary_sources accumulation, guards, and deadline."""

    def test_evidence_accumulated_grouped_by_entity_id(self):
        """Behavior 1: non-reranker source emitting two entities populates all_evidence."""
        store = _MockStore()
        evidence = [
            _ev("geo/USA", source_name="src_a", raw_score=0.9),
            _ev("geo/CAN", source_name="src_a", raw_score=0.8),
        ]
        sources = [_StaticSource("src_a", evidence)]
        all_evidence = defaultdict(list)
        _stages.run_primary_sources(
            _QUERY,
            _CONTEXT,
            all_evidence,
            NullTraceSink(),
            sources=sources,
            store=store,
            budget=50,
            config=None,
        )

        assert set(all_evidence.keys()) == {"geo/USA", "geo/CAN"}
        assert len(all_evidence["geo/USA"]) == 1
        assert len(all_evidence["geo/CAN"]) == 1
        assert all_evidence["geo/USA"][0].raw_score == pytest.approx(0.9)

    def test_reranker_sources_skipped_in_primary_phase(self):
        """Behavior 2: source with requires_existing_candidates=True does not run."""
        store = _MockStore()
        calls = []
        sources = [
            _RecordingSource("primary_src", calls, reranker=False),
            _RecordingSource("reranker_src", calls, reranker=True),
        ]
        all_evidence = defaultdict(list)
        _stages.run_primary_sources(
            _QUERY,
            _CONTEXT,
            all_evidence,
            NullTraceSink(),
            sources=sources,
            store=store,
            budget=50,
            config=None,
        )

        assert "primary_src" in calls
        assert "reranker_src" not in calls

    def test_fuzzy_source_skipped_when_exactly_one_exact_name_entity(self):
        """Behavior 3 (skip case): fuzzy source skipped with exactly one EXACT_NAME entity."""
        store = _MockStore()
        pre_evidence = [_ev("geo/USA", match_tier=MatchTier.EXACT_NAME)]
        calls = []
        sources = [_RecordingSource("fuzzy_src", calls, tier=MatchTier.FUZZY)]
        all_evidence = defaultdict(list)
        all_evidence["geo/USA"].extend(pre_evidence)

        _stages.run_primary_sources(
            _QUERY,
            _CONTEXT,
            all_evidence,
            NullTraceSink(),
            sources=sources,
            store=store,
            budget=50,
            config=None,
        )

        assert "fuzzy_src" not in calls, (
            "fuzzy source must be skipped with exactly one EXACT_NAME entity"
        )

    def test_fuzzy_source_runs_when_zero_exact_name_entities(self):
        """Behavior 3 (control: zero): fuzzy source DOES run with no EXACT_NAME evidence."""
        store = _MockStore()
        calls = []
        sources = [_RecordingSource("fuzzy_src", calls, tier=MatchTier.FUZZY)]
        all_evidence = defaultdict(list)
        _stages.run_primary_sources(
            _QUERY,
            _CONTEXT,
            all_evidence,
            NullTraceSink(),
            sources=sources,
            store=store,
            budget=50,
            config=None,
        )

        assert "fuzzy_src" in calls

    def test_fuzzy_source_runs_when_two_exact_name_entities(self):
        """Behavior 3 (control: two): fuzzy source DOES run with two EXACT_NAME entities."""
        store = _MockStore()
        calls = []
        sources = [_RecordingSource("fuzzy_src", calls, tier=MatchTier.FUZZY)]
        all_evidence = defaultdict(list)
        all_evidence["geo/USA"].append(_ev("geo/USA", match_tier=MatchTier.EXACT_NAME))
        all_evidence["geo/CAN"].append(_ev("geo/CAN", match_tier=MatchTier.EXACT_NAME))

        _stages.run_primary_sources(
            _QUERY,
            _CONTEXT,
            all_evidence,
            NullTraceSink(),
            sources=sources,
            store=store,
            budget=50,
            config=None,
        )

        assert "fuzzy_src" in calls

    def test_stop_condition_halts_iteration_after_source_a(self):
        """Behavior 4: generation-phase stop condition after source A prevents source B."""
        store = _MockStore()
        config = PipelineConfig(
            stop_conditions=[
                StopCondition(
                    name="stop_after_src_a",
                    phase="generation",
                    source_name="src_a",
                )
            ]
        )
        calls_a = []
        calls_b = []
        # src_a emits one entity so stop condition can match (candidate_count > 0)
        src_a = _RecordingSource(
            "src_a",
            calls_a,
            evidence=[_ev("geo/USA", source_name="src_a", raw_score=0.9)],
        )
        src_b = _RecordingSource("src_b", calls_b)
        sources = [src_a, src_b]
        all_evidence = defaultdict(list)
        _stages.run_primary_sources(
            _QUERY,
            _CONTEXT,
            all_evidence,
            NullTraceSink(),
            sources=sources,
            store=store,
            budget=50,
            config=config,
        )

        assert "src_a" in calls_a, "src_a must have run"
        assert "src_b" not in calls_b, (
            "src_b must be skipped after stop condition fires"
        )

    def test_expired_deadline_runs_no_sources(self):
        """Behavior 5: already-expired deadline causes no source to run."""
        store = _MockStore()
        calls = []
        sources = [_RecordingSource("src", calls)]
        all_evidence = defaultdict(list)
        past_deadline = time.monotonic() - 1.0

        _stages.run_primary_sources(
            _QUERY,
            _CONTEXT,
            all_evidence,
            NullTraceSink(),
            sources=sources,
            store=store,
            budget=50,
            config=None,
            deadline=past_deadline,
        )

        assert not calls, "no source should run with an already-expired deadline"
        assert len(all_evidence) == 0


# ---------------------------------------------------------------------------
# run_reranker_sources
# ---------------------------------------------------------------------------


class TestRunRerankerSources:
    """Behaviors 6-8: run_reranker_sources guards, injection, and deadline."""

    def test_only_reranker_sources_run(self):
        """Behavior 6: non-reranker source is skipped; reranker source runs."""
        store = _MockStore()
        calls = []
        sources = [
            _RecordingSource("primary_src", calls, reranker=False),
            _RecordingSource("reranker_src", calls, reranker=True),
        ]
        candidates = [
            _candidate("geo/USA", sources=[_ev("geo/USA", source_name="reranker_src")])
        ]
        _stages.run_reranker_sources(
            _QUERY,
            _CONTEXT,
            candidates,
            NullTraceSink(),
            sources=sources,
            store=store,
            budget=50,
        )

        assert "reranker_src" in calls
        assert "primary_src" not in calls

    def test_reranker_evidence_appended_to_existing_candidate(self):
        """Behavior 7 (known entity): reranker evidence appended; unknown entity silently dropped."""
        store = _MockStore()
        reranker_ev_known = _ev("geo/USA", source_name="reranker_src", raw_score=0.95)
        reranker_ev_unknown = _ev("geo/ZZZ", source_name="reranker_src", raw_score=0.7)

        sources = [
            _StaticSource(
                "reranker_src",
                [reranker_ev_known, reranker_ev_unknown],
                reranker=True,
            )
        ]
        initial_ev = _ev("geo/USA", source_name="primary_src", raw_score=0.8)
        candidates = [_candidate("geo/USA", sources=[initial_ev])]

        _stages.run_reranker_sources(
            _QUERY,
            _CONTEXT,
            candidates,
            NullTraceSink(),
            sources=sources,
            store=store,
            budget=50,
        )

        # Candidate list length unchanged (no new candidate for unknown entity)
        assert len(candidates) == 1
        # Reranker evidence was appended to the existing candidate
        assert len(candidates[0].sources) == 2
        assert candidates[0].sources[-1].source_name == "reranker_src"

    def test_reranker_unknown_entity_silently_dropped(self):
        """Behavior 7 (unknown entity only): candidate list stays the same length."""
        store = _MockStore()
        sources = [
            _StaticSource(
                "reranker_src",
                [_ev("geo/ZZZ", source_name="reranker_src", raw_score=0.7)],
                reranker=True,
            )
        ]
        initial_ev = _ev("geo/USA", source_name="primary_src", raw_score=0.8)
        candidates = [_candidate("geo/USA", sources=[initial_ev])]
        original_sources_count = len(candidates[0].sources)

        _stages.run_reranker_sources(
            _QUERY,
            _CONTEXT,
            candidates,
            NullTraceSink(),
            sources=sources,
            store=store,
            budget=50,
        )

        assert len(candidates) == 1
        assert len(candidates[0].sources) == original_sources_count

    def test_expired_deadline_runs_no_rerankers(self):
        """Behavior 8: already-expired deadline skips reranker sources."""
        store = _MockStore()
        calls = []
        sources = [_RecordingSource("reranker_src", calls, reranker=True)]
        candidates = [
            _candidate("geo/USA", sources=[_ev("geo/USA", source_name="src")])
        ]
        past_deadline = time.monotonic() - 1.0

        _stages.run_reranker_sources(
            _QUERY,
            _CONTEXT,
            candidates,
            NullTraceSink(),
            sources=sources,
            store=store,
            budget=50,
            deadline=past_deadline,
        )

        assert not calls, "no reranker should run with an already-expired deadline"


# ---------------------------------------------------------------------------
# merge_candidates
# ---------------------------------------------------------------------------


class TestMergeCandidates:
    """Behaviors 9-13: merge_candidates dedup, best-score, signal aggregation, scores."""

    def test_dedup_by_entity_id_into_one_candidate(self):
        """Behavior 9: three evidence entries for same entity_id → exactly one Candidate."""
        evidence_by_entity = {
            "geo/USA": [
                _ev("geo/USA", source_name="src1", raw_score=0.9),
                _ev("geo/USA", source_name="src2", raw_score=0.8),
                _ev("geo/USA", source_name="src3", raw_score=0.7),
            ]
        }
        candidates = _stages.merge_candidates(evidence_by_entity)

        assert len(candidates) == 1
        assert candidates[0].entity_id == "geo/USA"
        assert len(candidates[0].sources) == 3

    def test_best_fields_from_highest_raw_score_evidence(self):
        """Behavior 10: best_source / best_rank / best_raw_score come from max-score evidence."""
        evidence_by_entity = {
            "geo/USA": [
                _ev("geo/USA", source_name="low_src", raw_score=0.5, rank=3),
                _ev("geo/USA", source_name="high_src", raw_score=0.95, rank=1),
                _ev("geo/USA", source_name="mid_src", raw_score=0.7, rank=2),
            ]
        }
        candidates = _stages.merge_candidates(evidence_by_entity)

        retrieval = candidates[0].retrieval
        assert retrieval.best_source == "high_src"
        assert retrieval.best_rank == 1
        assert retrieval.best_raw_score == pytest.approx(0.95)

    def test_signals_aggregate_last_writer_wins(self):
        """Behavior 11: overlapping signal keys resolve to the last evidence in iteration order."""
        evidence_by_entity = {
            "geo/USA": [
                _ev(
                    "geo/USA",
                    source_name="src1",
                    signals={"overlap": 0.1, "only_a": 0.5},
                ),
                _ev(
                    "geo/USA",
                    source_name="src2",
                    signals={"overlap": 0.9, "only_b": 0.3},
                ),
            ]
        }
        candidates = _stages.merge_candidates(evidence_by_entity)

        signals = candidates[0].retrieval.signals
        # Last writer wins for overlap
        assert signals["overlap"] == pytest.approx(0.9)
        # Non-overlapping keys both survive
        assert signals["only_a"] == pytest.approx(0.5)
        assert signals["only_b"] == pytest.approx(0.3)

    def test_placeholder_score_when_best_raw_score_is_none(self):
        """Behavior 12 (None path): all raw_score None → placeholder DEFAULT_FALLBACK_SCORE."""
        evidence_by_entity = {
            "geo/USA": [
                _ev("geo/USA", source_name="src1", raw_score=None),
            ]
        }
        candidates = _stages.merge_candidates(evidence_by_entity)

        scores = candidates[0].scores
        assert scores.raw_score == pytest.approx(DEFAULT_FALLBACK_SCORE)
        assert scores.calibrated_score == pytest.approx(DEFAULT_FALLBACK_SCORE)

    def test_placeholder_score_when_raw_score_above_one(self):
        """Behavior 12 (>1.0 path): raw_score > 1.0 is preserved; calibrated capped at 1.0."""
        evidence_by_entity = {
            "geo/USA": [
                _ev("geo/USA", source_name="src1", raw_score=2.5),
            ]
        }
        candidates = _stages.merge_candidates(evidence_by_entity)

        scores = candidates[0].scores
        assert scores.raw_score == pytest.approx(2.5)
        assert scores.calibrated_score == pytest.approx(1.0)

    def test_empty_input_returns_empty_list(self):
        """Behavior 13: empty evidence dict → empty candidate list."""
        candidates = _stages.merge_candidates({})

        assert candidates == []


# ---------------------------------------------------------------------------
# add_evidence_to_candidates
# ---------------------------------------------------------------------------


class TestAddEvidenceToCandidates:
    """Behaviors 14-17: add_evidence_to_candidates injection and guards."""

    def test_unknown_entity_id_silently_dropped(self):
        """Behavior 14: evidence for an unknown entity_id does not create a new candidate."""
        initial_ev = _ev("geo/USA", source_name="src", raw_score=0.8)
        candidates = [_candidate("geo/USA", sources=[initial_ev])]

        unknown_ev = _ev("geo/ZZZ", source_name="reranker", raw_score=0.9)
        _stages.add_evidence_to_candidates([unknown_ev], candidates)

        assert len(candidates) == 1
        assert len(candidates[0].sources) == 1

    def test_evidence_appended_to_matching_candidate(self):
        """Behavior 15: evidence for a known entity_id is appended; original preserved."""
        initial_ev = _ev("geo/USA", source_name="primary_src", raw_score=0.8)
        candidates = [_candidate("geo/USA", sources=[initial_ev])]

        new_ev = _ev("geo/USA", source_name="reranker", raw_score=0.85)
        _stages.add_evidence_to_candidates([new_ev], candidates)

        assert len(candidates[0].sources) == 2
        assert candidates[0].sources[0].source_name == "primary_src"
        assert candidates[0].sources[1].source_name == "reranker"

    def test_signals_merge_new_over_old(self):
        """Behavior 16: signals = {**old, **new_ev.signals} — new values override old."""
        initial_ev = _ev(
            "geo/USA",
            source_name="src",
            raw_score=0.8,
            signals={"overlap": 0.1, "only_old": 0.5},
        )
        candidates = [
            _candidate(
                "geo/USA",
                sources=[initial_ev],
                signals={"overlap": 0.1, "only_old": 0.5},
            )
        ]

        new_ev = _ev(
            "geo/USA",
            source_name="reranker",
            raw_score=0.85,
            signals={"overlap": 0.9, "only_new": 0.3},
        )
        _stages.add_evidence_to_candidates([new_ev], candidates)

        merged = candidates[0].retrieval.signals
        assert merged["overlap"] == pytest.approx(0.9)  # new wins
        assert merged["only_old"] == pytest.approx(0.5)  # old survives
        assert merged["only_new"] == pytest.approx(0.3)  # new survives

    def test_best_score_updated_when_strictly_better(self):
        """Behavior 17 (better): ev.raw_score > current_best → best_* switches to new evidence."""
        initial_ev = _ev("geo/USA", source_name="primary_src", raw_score=0.7, rank=2)
        candidates = [
            _candidate(
                "geo/USA",
                sources=[initial_ev],
                best_raw_score=0.7,
                best_source="primary_src",
                best_rank=2,
            )
        ]

        better_ev = _ev("geo/USA", source_name="reranker", raw_score=0.95, rank=1)
        _stages.add_evidence_to_candidates([better_ev], candidates)

        retrieval = candidates[0].retrieval
        assert retrieval.best_source == "reranker"
        assert retrieval.best_rank == 1
        assert retrieval.best_raw_score == pytest.approx(0.95)

    def test_best_score_not_updated_when_not_better(self):
        """Behavior 17 (not better): ev.raw_score <= current_best → prior best_* preserved."""
        initial_ev = _ev("geo/USA", source_name="primary_src", raw_score=0.9, rank=1)
        candidates = [
            _candidate(
                "geo/USA",
                sources=[initial_ev],
                best_raw_score=0.9,
                best_source="primary_src",
                best_rank=1,
            )
        ]

        weaker_ev = _ev("geo/USA", source_name="reranker", raw_score=0.6, rank=5)
        _stages.add_evidence_to_candidates([weaker_ev], candidates)

        retrieval = candidates[0].retrieval
        assert retrieval.best_source == "primary_src"
        assert retrieval.best_rank == 1
        assert retrieval.best_raw_score == pytest.approx(0.9)

    def test_best_score_not_updated_when_new_raw_score_is_none(self):
        """Behavior 17 (None path): ev.raw_score=None → prior best_* preserved; signals still merge."""
        initial_ev = _ev(
            "geo/USA",
            source_name="primary_src",
            raw_score=0.8,
            rank=1,
            signals={"old_sig": 0.5},
        )
        candidates = [
            _candidate(
                "geo/USA",
                sources=[initial_ev],
                best_raw_score=0.8,
                best_source="primary_src",
                best_rank=1,
                signals={"old_sig": 0.5},
            )
        ]

        none_ev = _ev(
            "geo/USA",
            source_name="reranker",
            raw_score=None,
            signals={"new_sig": 0.7},
        )
        _stages.add_evidence_to_candidates([none_ev], candidates)

        retrieval = candidates[0].retrieval
        # best_* unchanged
        assert retrieval.best_source == "primary_src"
        assert retrieval.best_rank == 1
        assert retrieval.best_raw_score == pytest.approx(0.8)
        # signals still merged
        assert retrieval.signals["new_sig"] == pytest.approx(0.7)
