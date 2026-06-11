"""Tests for prominence helpers: compute_prominence + per-source fetchers."""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import pytest

from resolvekit.builder.sources.datacommons.geo.prominence import (
    compute_prominence,
    fetch_population,
)
from resolvekit.builder.sources.wikidata.sitelinks import fetch_sitelinks_by_qid

# ---------------------------------------------------------------------------
# compute_prominence unit tests (no DC client needed)
# ---------------------------------------------------------------------------


def test_sitelinks_only_normalization() -> None:
    result = compute_prominence(sitelinks={"a": 100, "b": 25}, populations={})
    assert result == {"a": 1.0, "b": 0.0}


def test_population_only_normalization() -> None:
    result = compute_prominence(
        sitelinks={},
        populations={"a": 1_000_000, "b": 100, "c": 1},
    )
    assert set(result) == {"a", "b", "c"}
    assert result["a"] == pytest.approx(1.0)
    assert result["c"] == pytest.approx(0.0)
    # b should be strictly between 0 and 1
    assert 0.0 < result["b"] < 1.0
    # log10 values: a=6, b≈2, c=log10(2)≈0.301
    log_a = math.log10(1_000_000 + 1)
    log_b = math.log10(100 + 1)
    log_c = math.log10(1 + 1)
    denom = log_a - log_c
    assert result["b"] == pytest.approx((log_b - log_c) / denom)


def test_sitelinks_beats_population_on_collision() -> None:
    result = compute_prominence(
        sitelinks={"a": 50},
        populations={"a": 100, "b": 10},
    )
    # Both a and b should be present
    assert "a" in result
    assert "b" in result
    # a's value from single-entity sitelinks bucket → 0.5
    assert result["a"] == pytest.approx(0.5)
    # b is in population-only single-entity bucket → 0.5
    assert result["b"] == pytest.approx(0.5)


def test_sitelinks_beats_population_two_sitelink_entities() -> None:
    result = compute_prominence(
        sitelinks={"a": 100, "c": 10},
        populations={"a": 999, "b": 50},
    )
    assert set(result) == {"a", "b", "c"}
    # a derived from sitelinks bucket (max → 1.0), not population
    assert result["a"] == pytest.approx(1.0)
    # c derived from sitelinks bucket (min → 0.0)
    assert result["c"] == pytest.approx(0.0)
    # b from population single-entity bucket → 0.5
    assert result["b"] == pytest.approx(0.5)


def test_empty_inputs_return_empty() -> None:
    assert compute_prominence(sitelinks={}, populations={}) == {}


def test_degenerate_sitelinks_bucket_emits_half() -> None:
    result = compute_prominence(sitelinks={"a": 100}, populations={})
    assert result == {"a": 0.5}


def test_degenerate_population_bucket_emits_half() -> None:
    result = compute_prominence(sitelinks={}, populations={"a": 500_000})
    assert result == {"a": 0.5}


def test_output_clipped_to_unit_interval() -> None:
    result = compute_prominence(
        sitelinks={"a": 100, "b": 25, "c": 75},
        populations={},
    )
    for v in result.values():
        assert 0.0 <= v <= 1.0


# ---------------------------------------------------------------------------
# fetch_sitelinks_by_qid tests (stubbed Wikidata SPARQL)
# ---------------------------------------------------------------------------

_SPARQL_TARGET = "resolvekit.builder.sources.wikidata.sitelinks.sparql_request"


def _binding(qid: str, sitelinks: str | None) -> dict:
    out: dict = {"item": {"value": f"http://www.wikidata.org/entity/{qid}"}}
    if sitelinks is not None:
        out["sitelinks"] = {"value": sitelinks}
    return out


def test_fetch_sitelinks_by_qid_basic() -> None:
    with patch(_SPARQL_TARGET) as mock_sparql:
        mock_sparql.return_value = [_binding("Q30", "250"), _binding("Q148", "180")]
        result = fetch_sitelinks_by_qid(qids=["Q30", "Q148"], request_delay=0)

    assert result == {"Q30": 250, "Q148": 180}
    assert mock_sparql.call_count == 1


def test_fetch_sitelinks_by_qid_normalizes_case_and_dedups() -> None:
    with patch(_SPARQL_TARGET) as mock_sparql:
        mock_sparql.return_value = [_binding("Q30", "5")]
        result = fetch_sitelinks_by_qid(qids=["q30", "Q30", "Q30"], request_delay=0)

    assert result == {"Q30": 5}
    # The VALUES clause should contain "Q30" exactly once.
    sent_query: str = mock_sparql.call_args.kwargs["query"]
    assert sent_query.count("wd:Q30") == 1


def test_fetch_sitelinks_by_qid_skips_malformed_qids() -> None:
    with patch(_SPARQL_TARGET) as mock_sparql:
        mock_sparql.return_value = []
        result = fetch_sitelinks_by_qid(
            qids=["not-a-qid", "P31", "Q0", "Q12"], request_delay=0
        )

    assert result == {}
    sent_query: str = mock_sparql.call_args.kwargs["query"]
    assert "wd:Q12" in sent_query
    # Only Q12 should make it through QID validation.
    assert "wd:Q0" not in sent_query
    assert "wd:P31" not in sent_query


def test_fetch_sitelinks_by_qid_batches_over_batch_size() -> None:
    qids = [f"Q{n}" for n in range(1, 6)]
    with patch(_SPARQL_TARGET) as mock_sparql:
        mock_sparql.side_effect = [
            [_binding("Q1", "10"), _binding("Q2", "20")],
            [_binding("Q3", "30"), _binding("Q4", "40")],
            [_binding("Q5", "50")],
        ]
        result = fetch_sitelinks_by_qid(qids=qids, batch_size=2, request_delay=0)

    assert result == {"Q1": 10, "Q2": 20, "Q3": 30, "Q4": 40, "Q5": 50}
    assert mock_sparql.call_count == 3


def test_fetch_sitelinks_by_qid_drops_unparseable_bindings() -> None:
    with patch(_SPARQL_TARGET) as mock_sparql:
        mock_sparql.return_value = [
            _binding("Q1", "42"),
            _binding("Q2", "not-a-number"),
            _binding("Q3", None),
            {"item": {"value": "garbage"}, "sitelinks": {"value": "7"}},
        ]
        result = fetch_sitelinks_by_qid(qids=["Q1", "Q2", "Q3"], request_delay=0)

    assert result == {"Q1": 42}


def test_fetch_sitelinks_by_qid_empty_input_short_circuits() -> None:
    with patch(_SPARQL_TARGET) as mock_sparql:
        result = fetch_sitelinks_by_qid(qids=[], request_delay=0)

    assert result == {}
    mock_sparql.assert_not_called()


# ---------------------------------------------------------------------------
# fetch_population tests (stubbed DC)
# ---------------------------------------------------------------------------


def test_fetch_population_delegates_to_fetch_observations() -> None:
    dc = MagicMock()
    dc.fetch_observations.return_value = {"country/USA": 331_000_000.0}
    result = fetch_population(dc=dc, entity_ids=["country/USA"])
    dc.fetch_observations.assert_called_once_with(
        ["country/USA"], variable_dcid="Count_Person"
    )
    assert result == {"country/USA": 331_000_000.0}
