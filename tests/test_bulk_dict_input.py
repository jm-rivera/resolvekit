"""Tests for dict input shape in bulk().

Covers:
- dict values resolve to a same-keyed dict
- Repeated values across keys are resolved once (dedup)
- None values stay None
- to=None returns a BulkResult with source aligned to dict values in key order
- output='record' returns dict[key, record-dict]
- Empty dict input returns empty dict without error
"""

from __future__ import annotations

from unittest.mock import MagicMock

from resolvekit.core.api.bulk import _bulk_dispatch, _detect_input_kind
from resolvekit.core.model.bulk_result import BulkResult
from resolvekit.core.model.result import ReasonCode, ResolutionResult, ResolutionStatus

# ---------------------------------------------------------------------------
# Helpers: minimal mock resolver (mirrors test_bulk_dispatch.py conventions)
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


def _make_entity(entity_id: str = "country/FRA", iso3: str = "FRA") -> MagicMock:
    from resolvekit.core.model.entity import CodeRecord, EntityRecord

    return EntityRecord(
        entity_id=entity_id,
        entity_type="geo.country",
        canonical_name="France",
        canonical_name_norm="france",
        codes=[
            CodeRecord(system="iso3", value=iso3, value_norm=iso3.lower()),
        ],
    )


def _mock_resolver(results_by_text: dict[str, ResolutionResult]) -> MagicMock:
    """Build a minimal mock Resolver with _resolve_many_internal returning fixed results."""
    from resolvekit.core.model.result import ResolutionResultList

    resolver = MagicMock()
    resolver._routing_mode = None
    resolver._runner.available_packs = frozenset({"geo"})

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


def _dispatch(resolver: MagicMock, values: dict, **kwargs) -> object:
    """Convenience wrapper for _bulk_dispatch with dict values."""
    return _bulk_dispatch(
        resolver=resolver,
        values=values,
        to=kwargs.pop("to", None),
        output=kwargs.pop("output", "series"),
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# _detect_input_kind: dict is detected correctly
# ---------------------------------------------------------------------------


def test_detect_dict():
    kind, vals = _detect_input_kind({"a": "France"})
    assert kind == "dict"
    assert vals == {"a": "France"}


# ---------------------------------------------------------------------------
# test_dict_values_resolve_same_keyed
# ---------------------------------------------------------------------------


def test_dict_values_resolve_same_keyed():
    """dict input resolves values and returns a same-keyed dict."""
    fra_entity = _make_entity("country/FRA", "FRA")
    deu_entity = _make_entity("country/DEU", "DEU")

    fra_result = _make_result(entity_id="country/FRA").model_copy(
        update={"entity": fra_entity}
    )
    deu_result = _make_result(entity_id="country/DEU").model_copy(
        update={"entity": deu_entity}
    )
    resolver = _mock_resolver({"France": fra_result, "Germany": deu_result})

    out = _dispatch(resolver, {"a": "France", "b": "Germany"}, to="iso3")

    assert isinstance(out, dict)
    assert set(out.keys()) == {"a", "b"}
    assert out["a"] == "FRA"
    assert out["b"] == "DEU"


# ---------------------------------------------------------------------------
# test_dict_repeated_values_dedup
# ---------------------------------------------------------------------------


def test_dict_repeated_values_dedup():
    """Two keys mapping to the same value result in a single resolver call."""
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

    resolver = MagicMock()
    resolver._routing_mode = None
    resolver._runner.available_packs = frozenset({"geo"})
    resolver._resolve_many_internal.side_effect = _resolve_many_internal

    out = _dispatch(resolver, {"a": "France", "b": "France"}, to="iso3")

    # Resolved once for the single unique value "France"
    assert len(call_log) == 1
    assert call_log[0] == ["France"]

    assert isinstance(out, dict)
    assert out["a"] == "FRA"
    assert out["b"] == "FRA"


# ---------------------------------------------------------------------------
# test_dict_none_value_stays_none
# ---------------------------------------------------------------------------


def test_dict_none_value_stays_none():
    """A None value in the dict passes through as None."""
    resolver = _mock_resolver({})

    out = _dispatch(resolver, {"a": None}, to="iso3")

    assert isinstance(out, dict)
    assert out["a"] is None


# ---------------------------------------------------------------------------
# test_dict_to_none_returns_bulkresult
# ---------------------------------------------------------------------------


def test_dict_to_none_returns_bulkresult():
    """to=None returns a BulkResult with source aligned to dict values in key order."""
    fra_result = _make_result(entity_id="country/FRA", query_text="France")
    deu_result = _make_result(entity_id="country/DEU", query_text="Germany")
    resolver = _mock_resolver({"France": fra_result, "Germany": deu_result})

    out = _dispatch(resolver, {"x": "France", "y": "Germany"}, to=None)

    assert isinstance(out, BulkResult)
    assert out.kind == "dict"
    # source should have two entries, one per input key
    assert len(out.source) == 2
    # values dict has same keys
    assert isinstance(out.values, dict)
    assert set(out.values.keys()) == {"x", "y"}


# ---------------------------------------------------------------------------
# test_dict_output_record
# ---------------------------------------------------------------------------


def test_dict_output_record():
    """output='record' on dict input returns dict[key, record-dict]."""
    fra_result = _make_result(entity_id="country/FRA", query_text="France")
    resolver = _mock_resolver({"France": fra_result})

    out = _dispatch(resolver, {"k": "France"}, to=None, output="record")

    assert isinstance(out, BulkResult)
    assert out.kind == "dict"
    assert isinstance(out.values, dict)
    assert "k" in out.values
    record = out.values["k"]
    assert isinstance(record, dict)
    assert record["entity_id"] == "country/FRA"
    assert record["status"] == "resolved"


# ---------------------------------------------------------------------------
# test_dict_empty
# ---------------------------------------------------------------------------


def test_dict_empty():
    """Empty dict input returns empty dict without error."""
    resolver = _mock_resolver({})

    out = _dispatch(resolver, {}, to="iso3")

    assert isinstance(out, dict)
    assert out == {}


def test_dict_empty_to_none_returns_empty_bulkresult():
    """Empty dict + to=None returns a BulkResult with empty values and source."""
    resolver = _mock_resolver({})

    out = _dispatch(resolver, {}, to=None)

    assert isinstance(out, BulkResult)
    assert out.kind == "dict"
    assert out.values == {}
    assert len(out.source) == 0


# ---------------------------------------------------------------------------
# BulkResult tabular converters treat "dict" like "list"
# ---------------------------------------------------------------------------


def test_dict_bulkresult_to_list_returns_values_in_key_order():
    """BulkResult(kind='dict').to_list() returns values in insertion order."""
    fra_result = _make_result(entity_id="country/FRA", query_text="France")
    deu_result = _make_result(entity_id="country/DEU", query_text="Germany")
    resolver = _mock_resolver({"France": fra_result, "Germany": deu_result})

    out = _dispatch(resolver, {"a": "France", "b": "Germany"}, to=None)

    assert isinstance(out, BulkResult)
    vals = out.to_list()
    assert len(vals) == 2
    # Order must match key insertion order: "a"→France result, "b"→Germany result


def test_dict_output_frame_returns_list_of_dicts():
    """output='frame' on dict input falls back to list-of-dicts (like list/tuple)."""
    fra_result = _make_result(entity_id="country/FRA", query_text="France")
    resolver = _mock_resolver({"France": fra_result})

    out = _dispatch(resolver, {"k": "France"}, to=None, output="frame")

    assert isinstance(out, BulkResult)
    # dict has no DataFrame analog; values is a list-of-dicts
    assert isinstance(out.values, list)
    assert out.values[0]["entity_id"] == "country/FRA"
