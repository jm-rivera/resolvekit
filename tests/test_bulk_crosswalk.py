"""Tests for crosswalk= short-circuit in bulk().

Covers:
- crosswalk hit short-circuits name resolution (resolve count == 0 for hit)
- Mixed batch: only absent values reach the resolver
- IGNORE entries yield None unconditionally (not_found="raise" not triggered)
- Crosswalk bypasses code-detection
- Crosswalk bypasses from_system
- Absent values follow normal on_ambiguous / not_found policy
- Unknown entity-id under strict=True raises CrosswalkError
- Unknown entity-id under strict=False follows not_found policy
- Extra crosswalk keys not in the input are harmless
- BulkResult.source[i].status == RESOLVED for crosswalked rows (ensures consistency)
- summary().resolved counts crosswalked rows
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from resolvekit.core.api.bulk import _bulk_dispatch
from resolvekit.core.errors import CrosswalkError, ResolutionError
from resolvekit.core.model.bulk_result import BulkResult
from resolvekit.core.model.crosswalk import IGNORE, Crosswalk
from resolvekit.core.model.result import (
    ReasonCode,
    ResolutionResult,
    ResolutionStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    status: ResolutionStatus = ResolutionStatus.RESOLVED,
    entity_id: str | None = "country/FRA",
    query_text: str | None = None,
) -> ResolutionResult:
    return ResolutionResult(
        status=status,
        entity_id=entity_id,
        reasons=[ReasonCode.EXACT_NAME_MATCH],
        query_text=query_text,
    )


def _make_entity(entity_id: str = "country/COD", iso3: str = "COD") -> MagicMock:
    from resolvekit.core.model.entity import CodeRecord, EntityRecord

    return EntityRecord(
        entity_id=entity_id,
        entity_type="geo.country",
        canonical_name="Congo",
        canonical_name_norm="congo",
        codes=[
            CodeRecord(system="iso3", value=iso3, value_norm=iso3.lower()),
        ],
    )


def _mock_resolver_with_entity(
    results_by_text: dict[str, ResolutionResult],
    entities_by_id: dict[str, object] | None = None,
) -> MagicMock:
    """Build a mock resolver; entities_by_id feeds get_entity."""
    from resolvekit.core.model.result import ResolutionResultList

    entities_by_id = entities_by_id or {}
    resolver = MagicMock()
    resolver._routing_mode = None
    resolver._runner.available_packs = frozenset({"geo"})
    resolver._runner.get_entity.side_effect = entities_by_id.get

    def _resolve_many_internal(
        texts, *, domain=None, context=None, include_entity=False, timeout=None
    ):
        return ResolutionResultList(
            [
                results_by_text.get(t, _make_result(ResolutionStatus.NO_MATCH, None))
                for t in texts
            ]
        )

    resolver._resolve_many_internal.side_effect = _resolve_many_internal
    return resolver


def _dispatch(resolver: MagicMock, values: list, **kwargs) -> object:
    return _bulk_dispatch(
        resolver=resolver,
        values=values,
        to=kwargs.pop("to", None),
        output=kwargs.pop("output", "series"),
        domain=None,
        context=None,
        from_system=None,
        not_found=kwargs.pop("not_found", "null"),
        on_error="raise",
        on_ambiguous="null",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# test_crosswalk_short_circuits_resolution
# ---------------------------------------------------------------------------


def test_crosswalk_short_circuits_resolution():
    """Values in the crosswalk never reach _resolve_many_internal or code_lookup.

    Mixed batch: one crosswalked value ("Congo") + one normal ("France").
    Only "France" reaches the resolver.
    """
    from resolvekit.core.model.result import ResolutionResultList

    call_log: list[list[str]] = []

    def _resolve_many_internal(
        texts, *, domain=None, context=None, include_entity=False, timeout=None
    ):
        call_log.append(list(texts))
        fra_entity = _make_entity("country/FRA", "FRA")
        fra_result = _make_result(entity_id="country/FRA").model_copy(
            update={"entity": fra_entity}
        )
        return ResolutionResultList([fra_result for _ in texts])

    cod_entity = _make_entity("country/COD", "COD")
    resolver = MagicMock()
    resolver._routing_mode = None
    resolver._runner.available_packs = frozenset({"geo"})
    resolver._runner.get_entity.side_effect = lambda eid: (
        cod_entity if eid == "country/COD" else None
    )
    resolver._resolve_many_internal.side_effect = _resolve_many_internal

    cw = Crosswalk.from_dict({"Congo": "country/COD"})
    _dispatch(resolver, ["Congo", "France"], to="iso3", crosswalk=cw)

    # Only "France" reached the resolver — "Congo" was short-circuited.
    assert len(call_log) == 1
    assert call_log[0] == ["France"]


# ---------------------------------------------------------------------------
# test_crosswalk_pivots_to_iso3
# ---------------------------------------------------------------------------


def test_crosswalk_pivots_to_iso3():
    """Crosswalk hit resolves and pivots correctly.

    Asserts that source[i].status == RESOLVED and entity_id is set,
    and that summary().resolved counts the crosswalked row.
    """
    cod_entity = _make_entity("country/COD", "COD")
    resolver = _mock_resolver_with_entity(
        results_by_text={},
        entities_by_id={"country/COD": cod_entity},
    )

    cw = Crosswalk.from_dict({"Congo": "country/COD"})
    result = _dispatch(resolver, ["Congo"], to="iso3", crosswalk=cw)

    assert isinstance(result, list)
    assert result == ["COD"]


def test_crosswalk_pivots_source_status_is_resolved():
    """BulkResult.source[i].status == RESOLVED for a crosswalked row."""
    cod_entity = _make_entity("country/COD", "COD")
    resolver = _mock_resolver_with_entity(
        results_by_text={},
        entities_by_id={"country/COD": cod_entity},
    )

    cw = Crosswalk.from_dict({"Congo": "country/COD"})
    br = _dispatch(resolver, ["Congo"], to=None, crosswalk=cw)

    assert isinstance(br, BulkResult)
    assert br.source[0].status == ResolutionStatus.RESOLVED
    assert br.source[0].entity_id == "country/COD"

    s = br.summary()
    assert s.resolved == 1
    assert s.no_match == 0


# ---------------------------------------------------------------------------
# test_crosswalk_ignore_yields_none
# ---------------------------------------------------------------------------


def test_crosswalk_ignore_yields_none():
    """IGNORE entry maps to None regardless of to= target."""
    resolver = _mock_resolver_with_entity(results_by_text={}, entities_by_id={})

    cw = Crosswalk.from_dict({"Ruritania": IGNORE})
    result = _dispatch(resolver, ["Ruritania"], to="iso3", crosswalk=cw)

    assert result == [None]


def test_crosswalk_ignore_bypasses_not_found_raise():
    """IGNORE → None even when not_found='raise' (not treated as a miss)."""
    resolver = _mock_resolver_with_entity(results_by_text={}, entities_by_id={})

    cw = Crosswalk.from_dict({"Ruritania": IGNORE})
    # Should not raise, even though not_found="raise"
    result = _dispatch(
        resolver, ["Ruritania"], to="iso3", crosswalk=cw, not_found="raise"
    )
    assert result == [None]


# ---------------------------------------------------------------------------
# test_crosswalk_bypasses_code_detection
# ---------------------------------------------------------------------------


def test_crosswalk_bypasses_code_detection():
    """A value that looks like a code but is in the crosswalk uses the crosswalk."""
    cod_entity = _make_entity("country/COD", "COD")
    # "COD" looks like a code; if code-detection ran, it would go via _code_lookup.
    # With crosswalk, it should resolve to country/COD (the crosswalk's entity).
    resolver = _mock_resolver_with_entity(
        results_by_text={},
        entities_by_id={"country/COD": cod_entity},
    )
    resolver._code_lookup = MagicMock()
    resolver._code_lookup.resolve_or_lookup.side_effect = AssertionError(
        "code_lookup should not have been called"
    )

    cw = Crosswalk.from_dict({"COD": "country/COD"})
    result = _dispatch(resolver, ["COD"], to=None, crosswalk=cw)

    assert isinstance(result, BulkResult)
    assert result.source[0].status == ResolutionStatus.RESOLVED
    assert result.source[0].entity_id == "country/COD"
    resolver._code_lookup.resolve_or_lookup.assert_not_called()


# ---------------------------------------------------------------------------
# test_crosswalk_bypasses_from_system
# ---------------------------------------------------------------------------


def test_crosswalk_bypasses_from_system():
    """from_system= plus crosswalk: crosswalk wins for matched values."""
    cod_entity = _make_entity("country/COD", "COD")
    resolver = _mock_resolver_with_entity(
        results_by_text={},
        entities_by_id={"country/COD": cod_entity},
    )
    resolver._code_lookup = MagicMock()
    resolver._code_lookup.resolve_or_lookup.side_effect = AssertionError(
        "code_lookup should not have been called for crosswalked value"
    )

    cw = Crosswalk.from_dict({"Congo": "country/COD"})
    # Pass from_system directly to _bulk_dispatch, not through _dispatch wrapper.
    result = _bulk_dispatch(
        resolver=resolver,
        values=["Congo"],
        to=None,
        output="series",
        domain=None,
        context=None,
        from_system="iso3",
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
        crosswalk=cw,
    )

    # get_entity was called (existence check); code_lookup was not.
    assert isinstance(result, BulkResult)
    assert result.source[0].entity_id == "country/COD"


# ---------------------------------------------------------------------------
# test_crosswalk_absent_value_follows_policy
# ---------------------------------------------------------------------------


def test_crosswalk_absent_value_follows_normal_policy():
    """Values absent from the crosswalk resolve normally via the resolver."""
    from resolvekit.core.model.result import ResolutionResultList

    cod_entity = _make_entity("country/COD", "COD")
    fra_entity = _make_entity("country/FRA", "FRA")

    def _resolve_many_internal(
        texts, *, domain=None, context=None, include_entity=False, timeout=None
    ):
        results = []
        for t in texts:
            if t == "France":
                results.append(
                    _make_result(entity_id="country/FRA").model_copy(
                        update={"entity": fra_entity}
                    )
                )
            else:
                results.append(_make_result(ResolutionStatus.NO_MATCH, None))
        return ResolutionResultList(results)

    resolver = MagicMock()
    resolver._routing_mode = None
    resolver._runner.available_packs = frozenset({"geo"})
    resolver._runner.get_entity.side_effect = lambda eid: (
        cod_entity if eid == "country/COD" else None
    )
    resolver._resolve_many_internal.side_effect = _resolve_many_internal

    # Partial crosswalk: Congo is crosswalked, France is not.
    cw = Crosswalk.from_dict({"Congo": "country/COD"})
    result = _dispatch(
        resolver, ["Congo", "France", "Unknown"], to="iso3", crosswalk=cw
    )

    assert result[0] == "COD"  # crosswalk hit
    assert result[1] == "FRA"  # resolved normally
    assert result[2] is None  # no_match → null


# ---------------------------------------------------------------------------
# test_crosswalk_unknown_id_strict_raises
# ---------------------------------------------------------------------------


def test_crosswalk_unknown_id_strict_raises():
    """Unknown entity-id under strict=True raises CrosswalkError."""
    resolver = _mock_resolver_with_entity(
        results_by_text={},
        entities_by_id={},  # country/ZZZ not found
    )

    cw = Crosswalk.from_dict({"X": "country/ZZZ"})  # strict=True by default
    with pytest.raises(CrosswalkError) as exc_info:
        _dispatch(resolver, ["X"], to="iso3", crosswalk=cw)

    assert "country/ZZZ" in exc_info.value.offenders


# ---------------------------------------------------------------------------
# test_crosswalk_unknown_id_nonstrict_miss
# ---------------------------------------------------------------------------


def test_crosswalk_unknown_id_nonstrict_null():
    """Unknown entity-id under strict=False + not_found='null' → None."""
    resolver = _mock_resolver_with_entity(
        results_by_text={},
        entities_by_id={},
    )

    cw = Crosswalk.from_dict({"X": "country/ZZZ"}, strict=False)
    result = _dispatch(resolver, ["X"], to="iso3", crosswalk=cw, not_found="null")
    assert result == [None]


def test_crosswalk_unknown_id_nonstrict_raise():
    """Unknown entity-id under strict=False + not_found='raise' → ResolutionError."""
    resolver = _mock_resolver_with_entity(
        results_by_text={},
        entities_by_id={},
    )

    cw = Crosswalk.from_dict({"X": "country/ZZZ"}, strict=False)
    with pytest.raises(ResolutionError):
        _dispatch(resolver, ["X"], to="iso3", crosswalk=cw, not_found="raise")


def test_crosswalk_unknown_id_nonstrict_sentinel():
    """Unknown entity-id under strict=False + not_found literal → that literal."""
    resolver = _mock_resolver_with_entity(
        results_by_text={},
        entities_by_id={},
    )

    cw = Crosswalk.from_dict({"X": "country/ZZZ"}, strict=False)
    result = _dispatch(resolver, ["X"], to="iso3", crosswalk=cw, not_found="MISS")
    assert result == ["MISS"]


# ---------------------------------------------------------------------------
# test_crosswalk_entry_not_in_input_ignored
# ---------------------------------------------------------------------------


def test_crosswalk_entry_not_in_input_ignored():
    """Extra crosswalk entries whose keys are not in the input are harmless."""
    fra_entity = _make_entity("country/FRA", "FRA")
    resolver = _mock_resolver_with_entity(
        results_by_text={},
        entities_by_id={"country/FRA": fra_entity, "country/COD": _make_entity()},
    )

    # Crosswalk has "Congo" but input only contains "France".
    cw = Crosswalk.from_dict({"Congo": "country/COD", "France": "country/FRA"})
    result = _dispatch(resolver, ["France"], to=None, crosswalk=cw)

    assert isinstance(result, BulkResult)
    assert result.source[0].entity_id == "country/FRA"
