from __future__ import annotations

import pytest

from resolvekit.core.model import (
    CandidateSummary,
    MatchClass,
    MatchTier,
    ResolutionResult,
    ResolutionStatus,
    SuggestionResult,
)
from scripts.benchmark.benchmark_autocomplete import (
    WorkerAccumulator,
    prefix_len_bucket,
    prefix_sequence,
    suggest_surfaced_entity_ids,
    surfaced_entity_ids,
)
from scripts.benchmark.benchmark_common import QueryCase


def test_prefix_sequence_starts_at_min_length_and_includes_full_query() -> None:
    assert prefix_sequence("Paris", 2) == ["Pa", "Par", "Pari", "Paris"]


def test_prefix_sequence_includes_short_full_query() -> None:
    assert prefix_sequence("U", 2) == ["U"]


def test_prefix_sequence_preserves_intermediate_spaces() -> None:
    assert prefix_sequence("New York", 3) == [
        "New",
        "New ",
        "New Y",
        "New Yo",
        "New Yor",
        "New York",
    ]


def test_surfaced_entity_ids_prefers_resolved_entity_and_dedupes_candidates() -> None:
    result = ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        entity_id="country/USA",
        candidates=[
            CandidateSummary(
                entity_id="country/USA",
                confidence=0.95,
                match_tier=MatchTier.EXACT_CODE,
            ),
            CandidateSummary(
                entity_id="country/GBR",
                confidence=0.42,
                match_tier=MatchTier.FTS,
            ),
        ],
    )

    assert surfaced_entity_ids(result) == ["country/USA", "country/GBR"]


def test_prefix_len_bucket_groups_ranges() -> None:
    assert prefix_len_bucket(1) == "1"
    assert prefix_len_bucket(2) == "2-3"
    assert prefix_len_bucket(4) == "4-5"
    assert prefix_len_bucket(7) == "6-8"
    assert prefix_len_bucket(10) == "9-12"
    assert prefix_len_bucket(20) == "13+"


def test_record_result_counts_hit_when_any_expected_id_surfaced() -> None:
    """A multi-id QueryCase counts as a returned_hit when any expected id is surfaced."""
    case = QueryCase(
        query="Tokyo",
        expected_ids=("geo.admin1/JPN-13", "geo.city/Q1490"),
        category=None,
        difficulty=None,
    )
    # Resolver surfaces only the second expected id.
    result = ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        entity_id="geo.city/Q1490",
        candidates=[],
    )
    accumulator = WorkerAccumulator()
    flags = accumulator.record_result(
        case=case,
        prefix="Tokyo",
        result=result,
        latency_ms=1.0,
    )

    assert flags.returned_hit is True
    assert accumulator.returned_hit_count == 1
    assert accumulator.expected_prefix_count == 1


# ---------------------------------------------------------------------------
# suggest_surfaced_entity_ids
# ---------------------------------------------------------------------------


def _make_suggestion(entity_id: str) -> SuggestionResult:
    return SuggestionResult(
        entity_id=entity_id,
        entity_type="geo.country",
        canonical_name=entity_id,
        display=entity_id,
        match_class=MatchClass.EXACT_PREFIX,
        fuzzy_score=None,
        highlight_ranges=[],
        ranking_quality="ranked",
    )


def test_suggest_surfaced_entity_ids_preserves_order() -> None:
    suggestions = [
        _make_suggestion("country/USA"),
        _make_suggestion("country/GBR"),
        _make_suggestion("country/DEU"),
    ]
    assert suggest_surfaced_entity_ids(suggestions) == [
        "country/USA",
        "country/GBR",
        "country/DEU",
    ]


def test_suggest_surfaced_entity_ids_deduplicates_first_seen_wins() -> None:
    suggestions = [
        _make_suggestion("country/USA"),
        _make_suggestion("country/GBR"),
        _make_suggestion("country/USA"),  # duplicate — should be dropped
    ]
    assert suggest_surfaced_entity_ids(suggestions) == ["country/USA", "country/GBR"]


def test_suggest_surfaced_entity_ids_returns_empty_for_no_suggestions() -> None:
    assert suggest_surfaced_entity_ids([]) == []


# ---------------------------------------------------------------------------
# WorkerAccumulator.record_mrr — MRR and success@k
# ---------------------------------------------------------------------------


def test_record_mrr_exact_top1_hit() -> None:
    """Expected id at rank 1 → RR=1.0, success@1=1, success@5=1."""
    acc = WorkerAccumulator()
    acc.record_mrr(
        surfaced_ids=["country/USA", "country/GBR"],
        expected_ids=("country/USA",),
    )
    assert acc.mrr_query_count == 1
    assert acc.mrr_sum == 1.0
    assert acc.success_at_1_count == 1
    assert acc.success_at_5_count == 1


def test_record_mrr_hit_at_rank_2() -> None:
    """Expected id at rank 2 → RR=0.5, success@1=0, success@5=1."""
    acc = WorkerAccumulator()
    acc.record_mrr(
        surfaced_ids=["country/GBR", "country/USA"],
        expected_ids=("country/USA",),
    )
    assert acc.mrr_query_count == 1
    assert acc.mrr_sum == pytest.approx(0.5)
    assert acc.success_at_1_count == 0
    assert acc.success_at_5_count == 1


def test_record_mrr_hit_at_rank_6() -> None:
    """Expected id at rank 6 → RR=1/6, success@1=0, success@5=0."""
    acc = WorkerAccumulator()
    surfaced = [f"country/X{i}" for i in range(5)] + ["country/USA"]
    acc.record_mrr(
        surfaced_ids=surfaced,
        expected_ids=("country/USA",),
    )
    assert acc.mrr_query_count == 1
    assert acc.mrr_sum == pytest.approx(1.0 / 6)
    assert acc.success_at_1_count == 0
    assert acc.success_at_5_count == 0


def test_record_mrr_miss_contributes_zero() -> None:
    """Expected id not in results → RR=0, counts not incremented."""
    acc = WorkerAccumulator()
    acc.record_mrr(
        surfaced_ids=["country/GBR", "country/FRA"],
        expected_ids=("country/USA",),
    )
    assert acc.mrr_query_count == 1
    assert acc.mrr_sum == 0.0
    assert acc.success_at_1_count == 0
    assert acc.success_at_5_count == 0


def test_record_mrr_no_expected_ids_skips_query() -> None:
    """Empty expected_ids → query not counted in MRR."""
    acc = WorkerAccumulator()
    acc.record_mrr(surfaced_ids=["country/USA"], expected_ids=())
    assert acc.mrr_query_count == 0
    assert acc.mrr_sum == 0.0


def test_record_mrr_accumulates_across_multiple_calls() -> None:
    """MRR sums correctly across multiple queries."""
    acc = WorkerAccumulator()
    # Query 1: hit at rank 1 → RR=1.0
    acc.record_mrr(surfaced_ids=["country/USA"], expected_ids=("country/USA",))
    # Query 2: hit at rank 2 → RR=0.5
    acc.record_mrr(
        surfaced_ids=["country/GBR", "country/DEU"],
        expected_ids=("country/DEU",),
    )
    assert acc.mrr_query_count == 2
    assert acc.mrr_sum == pytest.approx(1.5)
    assert acc.success_at_1_count == 1
    assert acc.success_at_5_count == 2


def test_record_mrr_first_expected_id_matched_stops_search() -> None:
    """When multiple expected ids, the first match in surfaced_ids wins."""
    acc = WorkerAccumulator()
    # USA at rank 2, GBR at rank 1 — GBR is also expected; rank 1 wins
    acc.record_mrr(
        surfaced_ids=["country/GBR", "country/USA"],
        expected_ids=("country/USA", "country/GBR"),
    )
    assert acc.mrr_sum == pytest.approx(1.0)  # GBR at rank 1 wins


# ---------------------------------------------------------------------------
# suggest-mode worker: hits read from SuggestionResult.entity_id
# ---------------------------------------------------------------------------


def test_suggest_mode_worker_records_hit_from_suggestion_entity_id() -> None:
    """suggest-mode run_worker reads entity IDs from SuggestionResult, not ResolutionResult."""
    from resolvekit import Resolver
    from scripts.benchmark.benchmark_autocomplete import run_worker

    resolver = Resolver.auto()

    case = QueryCase(
        query="unit",
        expected_ids=("country/USA",),
        category=None,
        difficulty=None,
    )
    result = run_worker(
        resolver,
        [case],
        domains=None,
        min_prefix_len=4,
        mode="suggest",
        suggest_top_k=20,
    )
    # In suggest mode the worker should surface country/USA and record at least
    # one returned_hit.
    assert result.returned_hit_count >= 1, (
        f"suggest-mode worker did not record a returned_hit for 'unit' → country/USA; "
        f"returned_hit_count={result.returned_hit_count}"
    )
