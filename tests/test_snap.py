"""Tests for snap() — closest-match operator.

Verifies that snap() resolves a query, post-filters to the candidate set,
and applies the max_distance threshold and optional ``to=`` pivot.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from resolvekit.core.api.snap import _snap_dispatch
from resolvekit.core.model.entity import CodeRecord, EntityRecord
from resolvekit.core.model.result import (
    CandidateSummary,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(entity_id: str = "country/USA") -> EntityRecord:
    return EntityRecord(
        entity_id=entity_id,
        entity_type="geo.country",
        canonical_name="United States",
        canonical_name_norm="united states",
        codes=[
            CodeRecord(system="iso3", value="USA", value_norm="usa"),
            CodeRecord(system="iso2", value="US", value_norm="us"),
        ],
    )


def _make_resolver(
    search_results: list[CandidateSummary],
    entity: EntityRecord | None = None,
) -> MagicMock:
    resolver = MagicMock()
    resolver._search_internal.return_value = search_results
    resolver._runner.get_entity.return_value = entity
    return resolver


# ---------------------------------------------------------------------------
# Basic snap tests
# ---------------------------------------------------------------------------


def test_snap_returns_entity_id_from_candidates():
    candidates_input = ["country/USA", "country/DEU"]
    search_results = [
        CandidateSummary(entity_id="country/USA", confidence=0.9),
        CandidateSummary(entity_id="country/DEU", confidence=0.7),
    ]
    resolver = _make_resolver(search_results)

    result = _snap_dispatch(
        resolver=resolver,
        query="United States",
        candidates=candidates_input,
        max_distance=0.5,
        to=None,
        domain=None,
        context=None,
    )
    assert result == "country/USA"


def test_snap_filters_to_candidates_only():
    """snap() must ignore results not in the candidates list."""
    candidates_input = ["country/DEU"]
    search_results = [
        CandidateSummary(entity_id="country/USA", confidence=0.95),  # not in candidates
        CandidateSummary(entity_id="country/DEU", confidence=0.85),
    ]
    resolver = _make_resolver(search_results)

    result = _snap_dispatch(
        resolver=resolver,
        query="Germany",
        candidates=candidates_input,
        max_distance=0.5,
        to=None,
        domain=None,
        context=None,
    )
    assert result == "country/DEU"


def test_snap_returns_none_when_below_threshold():
    """If the best candidate's confidence is below 1 - max_distance, return None."""
    candidates_input = ["country/DEU"]
    search_results = [
        CandidateSummary(entity_id="country/DEU", confidence=0.3),  # below 0.5 floor
    ]
    resolver = _make_resolver(search_results)

    result = _snap_dispatch(
        resolver=resolver,
        query="Germmy",
        candidates=candidates_input,
        max_distance=0.5,  # min_confidence = 0.5
        to=None,
        domain=None,
        context=None,
    )
    assert result is None


def test_snap_returns_none_for_empty_candidates():
    resolver = _make_resolver([])
    result = _snap_dispatch(
        resolver=resolver,
        query="US",
        candidates=[],
        max_distance=0.5,
        to=None,
        domain=None,
        context=None,
    )
    assert result is None


def test_snap_returns_none_when_no_search_results():
    resolver = _make_resolver([])
    result = _snap_dispatch(
        resolver=resolver,
        query="Atlantis",
        candidates=["country/USA"],
        max_distance=0.5,
        to=None,
        domain=None,
        context=None,
    )
    assert result is None


# ---------------------------------------------------------------------------
# snap with to= pivot
# ---------------------------------------------------------------------------


def test_snap_with_to_returns_pivoted_value():
    entity = _make_entity("country/USA")
    candidates_input = ["country/USA"]
    search_results = [
        CandidateSummary(entity_id="country/USA", confidence=0.9),
    ]
    resolver = _make_resolver(search_results, entity)

    result = _snap_dispatch(
        resolver=resolver,
        query="United States",
        candidates=candidates_input,
        max_distance=0.5,
        to="iso3",
        domain=None,
        context=None,
    )
    assert result == "USA"


def test_snap_with_to_returns_none_when_entity_missing():
    candidates_input = ["country/USA"]
    search_results = [
        CandidateSummary(entity_id="country/USA", confidence=0.9),
    ]
    resolver = _make_resolver(search_results, entity=None)

    result = _snap_dispatch(
        resolver=resolver,
        query="United States",
        candidates=candidates_input,
        max_distance=0.5,
        to="iso3",
        domain=None,
        context=None,
    )
    assert result is None


# ---------------------------------------------------------------------------
# max_distance boundary conditions
# ---------------------------------------------------------------------------


def test_snap_exact_threshold():
    """A candidate exactly at 1 - max_distance should pass the filter."""
    candidates_input = ["country/USA"]
    search_results = [
        CandidateSummary(entity_id="country/USA", confidence=0.5),  # exactly at floor
    ]
    resolver = _make_resolver(search_results)

    result = _snap_dispatch(
        resolver=resolver,
        query="US",
        candidates=candidates_input,
        max_distance=0.5,  # floor = 0.5
        to=None,
        domain=None,
        context=None,
    )
    assert result == "country/USA"


def test_snap_strict_threshold_zero():
    """max_distance=0.0 → only confidence=1.0 passes."""
    candidates_input = ["country/USA"]
    search_results = [
        CandidateSummary(entity_id="country/USA", confidence=0.99),
    ]
    resolver = _make_resolver(search_results)

    result = _snap_dispatch(
        resolver=resolver,
        query="US",
        candidates=candidates_input,
        max_distance=0.0,
        to=None,
        domain=None,
        context=None,
    )
    assert result is None  # 0.99 < 1.0 required


# ---------------------------------------------------------------------------
# Module-level snap() delegates to default resolver
# ---------------------------------------------------------------------------


def test_snap_module_level_delegates_to_default():
    """resolvekit.snap() should resolve via the singleton default resolver."""
    from resolvekit._convenience import snap as convenience_snap

    mock_resolver = _make_resolver(
        [CandidateSummary(entity_id="country/USA", confidence=0.9)]
    )
    mock_resolver.snap.return_value = "country/USA"

    import resolvekit._convenience as conv_mod

    original_get_default = conv_mod._get_default
    conv_mod._get_default = lambda: mock_resolver
    try:
        result = convenience_snap(
            query="United States",
            candidates=["country/USA"],
            max_distance=0.5,
        )
    finally:
        conv_mod._get_default = original_get_default

    assert result == "country/USA"
    mock_resolver.snap.assert_called_once()
