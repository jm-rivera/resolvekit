"""Regression tests for snap() label-candidate support (regression) and
_apply_to error propagation (regression).

Finding #5: snap() must resolve free-text candidate labels to entity IDs before
filtering, so candidates=['France','Spain'] works as documented.

Finding #13: _apply_to must propagate TypeError (list to=) and
UnknownCodeSystemError instead of swallowing them as None.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from resolvekit.core.api.snap import _apply_to, _snap_dispatch
from resolvekit.core.errors import UnknownCodeSystemError
from resolvekit.core.model.entity import CodeRecord, EntityRecord
from resolvekit.core.model.result import CandidateSummary

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(
    entity_id: str = "country/FRA", *, canonical_name: str = "France"
) -> EntityRecord:
    return EntityRecord(
        entity_id=entity_id,
        entity_type="geo.country",
        canonical_name=canonical_name,
        canonical_name_norm=canonical_name.lower(),
        codes=[
            CodeRecord(
                system="iso3",
                value=entity_id.split("/")[1],
                value_norm=entity_id.split("/")[1].lower(),
            ),
            CodeRecord(system="iso2", value="FR", value_norm="fr"),
        ],
    )


def _make_resolver(
    search_results: list[CandidateSummary],
    entity: EntityRecord | None = None,
    *,
    resolve_id_map: dict[str, str | None] | None = None,
) -> MagicMock:
    """Build a mock Resolver.

    ``resolve_id_map`` maps label strings to entity IDs (or None for
    unresolvable labels). Strings containing '/' are never passed to
    resolve_id; they pass through _resolve_candidate_to_id unchanged.
    """
    resolver = MagicMock()
    resolver._search_internal.return_value = search_results
    resolver._runner.get_entity.return_value = entity

    if resolve_id_map:

        def _resolve_id(text: str, *, on_ambiguous: str = "raise") -> str | None:
            return resolve_id_map.get(text)

        resolver.resolve_id.side_effect = _resolve_id
    else:
        resolver.resolve_id.return_value = None

    return resolver


# ---------------------------------------------------------------------------
# Finding #5 — label candidates are resolved to entity IDs before filtering
# ---------------------------------------------------------------------------


def test_label_candidates_resolve_to_entity_ids():
    """snap() with free-text labels in candidates matches correctly."""
    search_results = [
        CandidateSummary(entity_id="country/FRA", confidence=0.9),
        CandidateSummary(entity_id="country/ESP", confidence=0.5),
    ]
    resolver = _make_resolver(
        search_results,
        entity=_make_entity("country/FRA"),
        resolve_id_map={"France": "country/FRA", "Spain": "country/ESP"},
    )

    result = _snap_dispatch(
        resolver=resolver,
        query="Frnace",  # typo of France
        candidates=["France", "Spain"],
        max_distance=0.5,
        domain=None,
        context=None,
    )
    assert result == "country/FRA"


def test_label_candidates_unresolvable_label_skipped():
    """A label that cannot be resolved is silently skipped (does not prevent other matches)."""
    search_results = [
        CandidateSummary(entity_id="country/FRA", confidence=0.9),
    ]
    resolver = _make_resolver(
        search_results,
        entity=_make_entity("country/FRA"),
        resolve_id_map={"France": "country/FRA", "NotACountry": None},
    )

    result = _snap_dispatch(
        resolver=resolver,
        query="France",
        candidates=["France", "NotACountry"],
        max_distance=0.5,
        domain=None,
        context=None,
    )
    assert result == "country/FRA"


def test_label_candidates_all_unresolvable_returns_none():
    """When every label candidate fails resolution, snap() returns None."""
    resolver = _make_resolver(
        [],
        resolve_id_map={"NotACountry": None, "AlsoNothing": None},
    )

    result = _snap_dispatch(
        resolver=resolver,
        query="Something",
        candidates=["NotACountry", "AlsoNothing"],
        max_distance=0.5,
        domain=None,
        context=None,
    )
    assert result is None


def test_entity_id_candidates_unchanged():
    """Entity-ID candidates still work after the label-resolution refactor."""
    search_results = [
        CandidateSummary(entity_id="country/FRA", confidence=0.9),
    ]
    resolver = _make_resolver(
        search_results,
        entity=_make_entity("country/FRA"),
    )

    result = _snap_dispatch(
        resolver=resolver,
        query="France",
        candidates=["country/FRA", "country/ESP"],
        max_distance=0.5,
        domain=None,
        context=None,
    )
    # resolve_id should NOT be called for entity IDs (strings with '/')
    resolver.resolve_id.assert_not_called()
    assert result == "country/FRA"


def test_mixed_candidates_label_and_entity_id():
    """Mixed list: one entity ID and one free-text label both work."""
    search_results = [
        CandidateSummary(entity_id="country/FRA", confidence=0.9),
        CandidateSummary(entity_id="country/ESP", confidence=0.7),
    ]
    resolver = _make_resolver(
        search_results,
        entity=_make_entity("country/FRA"),
        resolve_id_map={"Spain": "country/ESP"},
    )

    result = _snap_dispatch(
        resolver=resolver,
        query="Frnace",
        candidates=["country/FRA", "Spain"],  # one ID, one label
        max_distance=0.5,
        domain=None,
        context=None,
    )
    assert result == "country/FRA"
    # resolve_id called only for the label, not the entity ID
    resolver.resolve_id.assert_called_once_with("Spain", on_ambiguous="null")


def test_label_candidates_with_to_pivot():
    """Label candidates + to= pivot returns the pivoted value."""
    search_results = [
        CandidateSummary(entity_id="country/FRA", confidence=0.9),
    ]
    entity = _make_entity("country/FRA")
    resolver = _make_resolver(
        search_results,
        entity=entity,
        resolve_id_map={"France": "country/FRA", "Spain": "country/ESP"},
    )

    result = _snap_dispatch(
        resolver=resolver,
        query="France",
        candidates=["France", "Spain"],
        max_distance=0.5,
        to="iso3",
        domain=None,
        context=None,
    )
    assert result == "FRA"


# ---------------------------------------------------------------------------
# Finding #13 — _apply_to propagates TypeError and UnknownCodeSystemError
# ---------------------------------------------------------------------------


def test_apply_to_list_raises_type_error():
    """snap() with to=['iso3','name'] raises TypeError, not silently returns None."""
    search_results = [
        CandidateSummary(entity_id="country/FRA", confidence=0.9),
    ]
    entity = _make_entity("country/FRA")
    resolver = _make_resolver(search_results, entity=entity)

    with pytest.raises(TypeError, match="to= takes a single target string"):
        _snap_dispatch(
            resolver=resolver,
            query="France",
            candidates=["country/FRA"],
            max_distance=0.5,
            to=["iso3", "name"],
            domain=None,
            context=None,
        )


def test_apply_to_unknown_code_system_raises():
    """snap() with an unknown to= system raises UnknownCodeSystemError."""
    search_results = [
        CandidateSummary(entity_id="country/FRA", confidence=0.9),
    ]
    entity = _make_entity("country/FRA")
    resolver = _make_resolver(search_results, entity=entity)

    with pytest.raises(UnknownCodeSystemError):
        _snap_dispatch(
            resolver=resolver,
            query="France",
            candidates=["country/FRA"],
            max_distance=0.5,
            to="not_a_real_system",
            domain=None,
            context=None,
        )


def test_apply_to_returns_none_when_entity_missing():
    """_apply_to still returns None when the entity cannot be fetched (legitimate miss)."""
    resolver = _make_resolver([], entity=None)

    result = _apply_to(resolver, "country/FRA", "iso3")
    assert result is None


def test_apply_to_returns_entity_id_when_to_is_none():
    """_apply_to(to=None) returns the entity_id directly."""
    resolver = _make_resolver([])
    result = _apply_to(resolver, "country/FRA", None)
    assert result == "country/FRA"
    resolver._runner.get_entity.assert_not_called()
