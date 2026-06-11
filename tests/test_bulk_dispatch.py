"""Tests for bulk() narwhals dispatch.

Covers:
- Native-shape return when ``to=`` is a scalar pivot
- BulkResult wrapping for ``to=None`` / ``output="record"`` / ``output="frame"``
- Pandas index/name preservation
- Dedup: resolver called once per unique value
- Null / NaN pass-through
- not_found / on_error / on_ambiguous contracts
- Generator input raises TypeError
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from resolvekit.core.api.bulk import _bulk_dispatch, _detect_input_kind
from resolvekit.core.model.bulk_result import BulkResult
from resolvekit.core.model.result import ReasonCode, ResolutionResult, ResolutionStatus

# ---------------------------------------------------------------------------
# Helpers: minimal mock resolver
# ---------------------------------------------------------------------------


def _make_result(
    status: ResolutionStatus = ResolutionStatus.RESOLVED,
    entity_id: str | None = "country/USA",
    query_text: str | None = None,
) -> ResolutionResult:
    return ResolutionResult(
        status=status,
        entity_id=entity_id,
        reasons=[ReasonCode.EXACT_NAME_MATCH],
        query_text=query_text,
    )


def _make_entity(entity_id: str = "country/USA", iso3: str = "USA") -> MagicMock:
    from resolvekit.core.model.entity import CodeRecord, EntityRecord

    return EntityRecord(
        entity_id=entity_id,
        entity_type="geo.country",
        canonical_name="United States",
        canonical_name_norm="united states",
        codes=[
            CodeRecord(system="iso3", value=iso3, value_norm=iso3.lower()),
            CodeRecord(system="iso2", value="US", value_norm="us"),
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


# ---------------------------------------------------------------------------
# _detect_input_kind
# ---------------------------------------------------------------------------


def test_detect_list():
    kind, vals = _detect_input_kind(["a", "b"])
    assert kind == "list"
    assert vals == ["a", "b"]


def test_detect_tuple():
    kind, _vals = _detect_input_kind(("a",))
    assert kind == "tuple"


def test_detect_numpy():
    np = pytest.importorskip("numpy")
    arr = np.array(["a", "b"])
    kind, _vals = _detect_input_kind(arr)
    assert kind == "numpy"


def test_detect_pandas():
    pd = pytest.importorskip("pandas")
    s = pd.Series(["a", "b"])
    kind, _vals = _detect_input_kind(s)
    assert kind == "pandas"


def test_detect_generator_raises():
    with pytest.raises(TypeError, match="materialize first"):
        _detect_input_kind(x for x in ["a"])


def test_detect_unsupported_raises():
    with pytest.raises(TypeError):
        _detect_input_kind(
            frozenset({"a"})
        )  # frozenset has __len__ but is not a supported kind


# ---------------------------------------------------------------------------
# Return-shape tests
# ---------------------------------------------------------------------------


def test_list_to_none_returns_bulk_result():
    resolver = _mock_resolver({"US": _make_result()})
    result = _bulk_dispatch(
        resolver=resolver,
        values=["US"],
        to=None,
        output="series",
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )
    assert isinstance(result, BulkResult)
    assert result.kind == "list"


def test_list_scalar_to_returns_list():
    entity = _make_entity()
    result_obj = _make_result()
    result_obj = result_obj.model_copy(update={"entity": entity})
    resolver = _mock_resolver({"United States": result_obj})

    out = _bulk_dispatch(
        resolver=resolver,
        values=["United States"],
        to="iso3",
        output="series",
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )
    assert isinstance(out, list)
    assert out == ["USA"]


def test_tuple_scalar_to_returns_tuple():
    entity = _make_entity()
    result_obj = _make_result()
    result_obj = result_obj.model_copy(update={"entity": entity})
    resolver = _mock_resolver({"US": result_obj})

    out = _bulk_dispatch(
        resolver=resolver,
        values=("US",),
        to="iso3",
        output="series",
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )
    assert isinstance(out, tuple)


def test_numpy_scalar_to_returns_ndarray():
    np = pytest.importorskip("numpy")
    entity = _make_entity()
    result_obj = _make_result()
    result_obj = result_obj.model_copy(update={"entity": entity})
    resolver = _mock_resolver({"US": result_obj})

    arr = np.array(["US"])
    out = _bulk_dispatch(
        resolver=resolver,
        values=arr,
        to="iso3",
        output="series",
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )
    assert isinstance(out, np.ndarray)


# ---------------------------------------------------------------------------
# Pandas index/name preservation
# ---------------------------------------------------------------------------


def test_pandas_preserves_index_and_name():
    pd = pytest.importorskip("pandas")
    entity = _make_entity()
    result_obj = _make_result()
    result_obj = result_obj.model_copy(update={"entity": entity})
    resolver = _mock_resolver({"United States": result_obj})

    s = pd.Series(["United States"], index=[42], name="country_col")
    out = _bulk_dispatch(
        resolver=resolver,
        values=s,
        to="iso3",
        output="series",
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )
    assert isinstance(out, pd.Series)
    assert list(out.index) == [42]
    assert out.name == "country_col"
    assert list(out) == ["USA"]


def test_pandas_to_none_returns_bulk_result_with_pandas_kind():
    pd = pytest.importorskip("pandas")
    resolver = _mock_resolver({"US": _make_result()})
    s = pd.Series(["US"], name="col")
    out = _bulk_dispatch(
        resolver=resolver,
        values=s,
        to=None,
        output="series",
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )
    assert isinstance(out, BulkResult)
    assert out.kind == "pandas"


# ---------------------------------------------------------------------------
# Dedup: resolver called once per unique
# ---------------------------------------------------------------------------


def test_dedup_calls_resolve_once_per_unique():
    pd = pytest.importorskip("pandas")

    call_log: list[list[str]] = []
    from resolvekit.core.model.result import ResolutionResultList

    def _resolve_many_internal(
        texts, *, domain=None, context=None, include_entity=False, timeout=None
    ):
        call_log.append(list(texts))
        return ResolutionResultList([_make_result() for _ in texts])

    resolver = MagicMock()
    resolver._routing_mode = None
    resolver._runner.available_packs = frozenset({"geo"})
    resolver._resolve_many_internal.side_effect = _resolve_many_internal

    s = pd.Series(["United States", "United States", "Germany", "United States"])
    _bulk_dispatch(
        resolver=resolver,
        values=s,
        to=None,
        output="series",
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )
    # resolve_many called once; texts = unique values only
    assert len(call_log) == 1
    assert sorted(call_log[0]) == ["Germany", "United States"]


# ---------------------------------------------------------------------------
# Null pass-through
# ---------------------------------------------------------------------------


def test_none_in_list_passes_through():
    resolver = _mock_resolver({})
    out = _bulk_dispatch(
        resolver=resolver,
        values=[None, "US"],
        to=None,
        output="series",
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )
    assert isinstance(out, BulkResult)
    assert out.to_list()[0] is None


def test_nan_in_pandas_passes_through():
    pd = pytest.importorskip("pandas")

    resolver = _mock_resolver({})
    s = pd.Series([float("nan"), "US"])
    out = _bulk_dispatch(
        resolver=resolver,
        values=s,
        to=None,
        output="series",
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )
    # First element should be None
    vals = out.to_list()
    assert vals[0] is None


# ---------------------------------------------------------------------------
# not_found contract
# ---------------------------------------------------------------------------


def test_not_found_null_returns_none():
    resolver = _mock_resolver({"X": _make_result(ResolutionStatus.NO_MATCH, None)})
    out = _bulk_dispatch(
        resolver=resolver,
        values=["X"],
        to="iso3",
        output="series",
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )
    assert out == [None]


def test_not_found_sentinel_returns_sentinel():
    resolver = _mock_resolver({"X": _make_result(ResolutionStatus.NO_MATCH, None)})
    out = _bulk_dispatch(
        resolver=resolver,
        values=["X"],
        to="iso3",
        output="series",
        domain=None,
        context=None,
        from_system=None,
        not_found="<unknown>",
        on_error="raise",
        on_ambiguous="null",
    )
    assert out == ["<unknown>"]


def test_not_found_raise():
    from resolvekit.core.errors import ResolutionError

    resolver = _mock_resolver({"X": _make_result(ResolutionStatus.NO_MATCH, None)})
    with pytest.raises(ResolutionError):
        _bulk_dispatch(
            resolver=resolver,
            values=["X"],
            to="iso3",
            output="series",
            domain=None,
            context=None,
            from_system=None,
            not_found="raise",
            on_error="raise",
            on_ambiguous="null",
        )


# ---------------------------------------------------------------------------
# on_ambiguous contract
# ---------------------------------------------------------------------------


def test_on_ambiguous_null_returns_none():
    from resolvekit.core.model.result import CandidateSummary

    candidates = [
        CandidateSummary(entity_id="country/USA"),
        CandidateSummary(entity_id="org/EU"),
    ]
    ambig = ResolutionResult(
        status=ResolutionStatus.AMBIGUOUS,
        candidates=candidates,
        reasons=[ReasonCode.AMBIGUOUS_LOW_GAP],
    )
    resolver = _mock_resolver({"EU": ambig})
    out = _bulk_dispatch(
        resolver=resolver,
        values=["EU"],
        to="iso3",
        output="series",
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )
    assert out == [None]


def test_on_ambiguous_raise():
    from resolvekit.core.errors import AmbiguousResolutionError
    from resolvekit.core.model.result import CandidateSummary

    candidates = [
        CandidateSummary(entity_id="country/USA"),
        CandidateSummary(entity_id="org/EU"),
    ]
    ambig = ResolutionResult(
        status=ResolutionStatus.AMBIGUOUS,
        candidates=candidates,
        reasons=[ReasonCode.AMBIGUOUS_LOW_GAP],
    )
    resolver = _mock_resolver({"European Union": ambig})
    with pytest.raises(AmbiguousResolutionError):
        _bulk_dispatch(
            resolver=resolver,
            values=["European Union"],
            to="iso3",
            output="series",
            domain=None,
            context=None,
            from_system=None,
            not_found="null",
            on_error="raise",
            on_ambiguous="raise",
        )


# ---------------------------------------------------------------------------
# output="record" / output="frame" always returns BulkResult
# ---------------------------------------------------------------------------


def test_output_record_returns_bulk_result_with_struct_records():
    """output='record' wraps a series-of-dict in BulkResult."""
    entity = _make_entity()
    result_obj = _make_result().model_copy(update={"entity": entity})
    resolver = _mock_resolver({"United States": result_obj})

    out = _bulk_dispatch(
        resolver=resolver,
        values=["United States"],
        to="iso3",
        output="record",
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )

    from resolvekit.core.model.bulk_result import BulkResult

    assert isinstance(out, BulkResult)
    record = next(iter(out.values))
    assert record["status"] == "resolved"
    assert record["entity_id"] == "country/USA"
    assert record["value"] == "USA"


def test_output_frame_returns_bulk_result_with_records_for_list_kind():
    """output='frame' on list/tuple/numpy input returns a list of dicts."""
    entity = _make_entity()
    result_obj = _make_result().model_copy(update={"entity": entity})
    resolver = _mock_resolver({"United States": result_obj})

    out = _bulk_dispatch(
        resolver=resolver,
        values=["United States"],
        to="iso3",
        output="frame",
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )

    from resolvekit.core.model.bulk_result import BulkResult

    assert isinstance(out, BulkResult)
    records = out.values
    assert isinstance(records, list)
    assert records[0]["entity_id"] == "country/USA"


def test_output_frame_returns_pandas_dataframe_for_pandas_input():
    """output='frame' on a pd.Series input materialises a pd.DataFrame."""
    pd = pytest.importorskip("pandas")
    entity = _make_entity()
    result_obj = _make_result().model_copy(update={"entity": entity})
    resolver = _mock_resolver({"United States": result_obj})

    out = _bulk_dispatch(
        resolver=resolver,
        values=pd.Series(["United States"], name="country"),
        to="iso3",
        output="frame",
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )

    from resolvekit.core.model.bulk_result import BulkResult

    assert isinstance(out, BulkResult)
    assert isinstance(out.values, pd.DataFrame)
    assert "entity_id" in out.values.columns


def test_output_invalid_value_raises_value_error():
    """Unknown ``output=`` values are rejected with a clear error."""
    resolver = _mock_resolver({})
    with pytest.raises(ValueError, match="output="):
        _bulk_dispatch(
            resolver=resolver,
            values=["United States"],
            to=None,
            output="bogus",
            domain=None,
            context=None,
            from_system=None,
            not_found="null",
            on_error="raise",
            on_ambiguous="null",
        )


# ---------------------------------------------------------------------------
# BulkResult.to_list parity helper
# ---------------------------------------------------------------------------


def test_bulk_result_to_list_returns_pivot_values():
    entity = _make_entity()
    result_obj = _make_result()
    result_obj = result_obj.model_copy(update={"entity": entity})
    resolver = _mock_resolver(
        {"US": result_obj, "DE": _make_result(ResolutionStatus.NO_MATCH, None)}
    )

    out = _bulk_dispatch(
        resolver=resolver,
        values=["US", "DE"],
        to=None,
        output="series",
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )
    assert isinstance(out, BulkResult)
    assert len(out.to_list()) == 2
