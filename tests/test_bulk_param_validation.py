"""Regression tests for bulk() parameter validation, output building, and result pickling.

Each test class corresponds to one finding and runs with minimal mocks to avoid
flaky data-dependency. Integration probes using the real resolver are grouped at
the bottom.
"""

from __future__ import annotations

import pickle
from typing import Any
from unittest.mock import MagicMock

import pytest

from resolvekit.core.api.bulk import _bulk_dispatch, _detect_input_kind
from resolvekit.core.model.bulk_result import BulkResult
from resolvekit.core.model.result import ReasonCode, ResolutionResult, ResolutionStatus

# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------


def _make_resolved(
    entity_id: str = "country/FRA", query: str = "France"
) -> ResolutionResult:
    return ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        entity_id=entity_id,
        reasons=[ReasonCode.EXACT_NAME_MATCH],
        query_text=query,
    )


def _make_no_match(query: str = "n/a") -> ResolutionResult:
    return ResolutionResult(
        status=ResolutionStatus.NO_MATCH,
        reasons=[ReasonCode.NO_CANDIDATES],
        query_text=query,
    )


def _mock_resolver(results_by_text: dict[str, ResolutionResult]) -> MagicMock:
    from resolvekit.core.model.result import ResolutionResultList

    resolver = MagicMock()
    resolver._routing_mode = None
    resolver._runner.available_packs = frozenset({"geo"})

    def _resolve_many_internal(
        texts, *, domain=None, context=None, include_entity=False, timeout=None
    ):
        return ResolutionResultList(
            [results_by_text.get(t, _make_no_match(t)) for t in texts]
        )

    resolver._resolve_many_internal.side_effect = _resolve_many_internal
    return resolver


def _dispatch(
    resolver: Any,
    values: Any,
    *,
    to: Any = None,
    output: str = "series",
    on_error: str = "raise",
    on_ambiguous: str = "null",
    on_missing: str = "auto",
    not_found: str = "null",
) -> Any:
    """Thin wrapper so callers don't have to repeat all kwargs."""
    return _bulk_dispatch(
        resolver=resolver,
        values=values,
        to=to,
        output=output,
        domain=None,
        context=None,
        from_system=None,
        not_found=not_found,
        on_error=on_error,
        on_ambiguous=on_ambiguous,
        on_missing=on_missing,
    )


# ---------------------------------------------------------------------------
# #3 — polars Series path: no NameError from TYPE_CHECKING Explainer forward ref
# ---------------------------------------------------------------------------


class TestFinding3PolarsNameError:
    def test_polars_bulk_result_no_crash(self) -> None:
        """bulk() on pl.Series must return BulkResult without NameError."""
        pl = pytest.importorskip("polars")
        resolver = _mock_resolver({"France": _make_resolved()})
        result = _dispatch(resolver, pl.Series(["France", "Spain"]))
        assert isinstance(result, BulkResult)
        assert result.kind == "polars"

    def test_polars_series_stored_as_object_dtype(self) -> None:
        """Values series uses pl.Object so polars never introspects pydantic models."""
        pl = pytest.importorskip("polars")
        resolver = _mock_resolver({"France": _make_resolved()})
        result = _dispatch(resolver, pl.Series(["France"]))
        assert isinstance(result, BulkResult)
        # The inner pl.Series must be pl.Object, not inferred from pydantic.
        assert result.values.dtype == pl.Object

    def test_polars_output_record_no_crash(self) -> None:
        """output='record' with polars input must not crash with 'nested objects'."""
        pl = pytest.importorskip("polars")
        resolver = _mock_resolver({"France": _make_resolved()})
        result = _dispatch(resolver, pl.Series(["France"]), output="record")
        assert isinstance(result, BulkResult)
        # The records must be Struct-typed (polars can handle dicts of primitives).
        assert isinstance(result.values[0], dict)
        # value field must be a primitive (entity_id string), not a ResolutionResult.
        assert isinstance(result.values[0]["value"], str | type(None))


# ---------------------------------------------------------------------------
# #22 — pandas None not coerced to NaN
# ---------------------------------------------------------------------------


class TestFinding22PandasNone:
    def test_none_preserved_not_nan(self) -> None:
        """Unresolved rows in pandas output must be None, not NaN."""
        pd = pytest.importorskip("pandas")
        resolver = _mock_resolver({"France": _make_resolved(entity_id="country/FRA")})
        # Patch dispatch_pivot to return the entity_id string for "iso3"
        from unittest.mock import patch

        def fake_pivot(entity: Any, to: str) -> str | None:
            if to == "iso3":
                return "FRA"
            return None

        from resolvekit.core.api import bulk as bulk_mod

        with patch.object(bulk_mod, "dispatch_pivot", side_effect=fake_pivot):
            series = _dispatch(
                resolver,
                pd.Series(["France", "n/a"]),
                to="iso3",
            )

        assert isinstance(series, pd.Series)
        assert series.dtype == object
        assert series.iloc[0] == "FRA"
        assert series.iloc[1] is None

    def test_pandas_series_dtype_object_when_no_pivot(self) -> None:
        """Even without a pivot, pandas series must use dtype=object."""
        pd = pytest.importorskip("pandas")
        resolver = _mock_resolver({"France": _make_resolved()})
        result = _dispatch(resolver, pd.Series(["France"]))
        # BulkResult.values is the underlying pandas Series.
        assert isinstance(result, BulkResult)
        assert result.values.dtype == object


# ---------------------------------------------------------------------------
# #24 — ResolutionResult pickle round-trip
# ---------------------------------------------------------------------------


class TestFinding24Pickle:
    def test_pickle_round_trip(self) -> None:
        """ResolutionResult must survive pickle.dumps / pickle.loads."""
        r = _make_resolved()
        unpickled = pickle.loads(pickle.dumps(r))
        assert unpickled.status == ResolutionStatus.RESOLVED
        assert unpickled.entity_id == "country/FRA"

    def test_pickle_with_private_attrs(self) -> None:
        """Pickle must work even when _explainer / _resolve_context are set."""
        import weakref

        class _Sentinel:
            """Weakref-able sentinel."""

        r = ResolutionResult(
            status=ResolutionStatus.RESOLVED,
            entity_id="country/FRA",
            reasons=[ReasonCode.EXACT_NAME_MATCH],
        )
        # Simulate a live explainer backref using a weakref-able object.
        sentinel = _Sentinel()
        priv = r.__pydantic_private__
        assert priv is not None
        priv["_explainer"] = weakref.ref(sentinel)

        unpickled = pickle.loads(pickle.dumps(r))
        assert unpickled.entity_id == "country/FRA"
        # The explainer must be dropped — no weakref in the unpickled object.
        unpriv = unpickled.__pydantic_private__
        assert unpriv is not None
        assert unpriv["_explainer"] is None

    def test_explain_on_unpickled_raises_gracefully(self) -> None:
        """explain() on an unpickled result must raise ExplainNotAvailableError."""
        from resolvekit.core.errors_base import ExplainNotAvailableError

        r = _make_resolved(query="France")
        unpickled = pickle.loads(pickle.dumps(r))
        with pytest.raises(ExplainNotAvailableError):
            unpickled.explain()


# ---------------------------------------------------------------------------
# #25 — output='record' without pivot: primitives only, to_polars safe
# ---------------------------------------------------------------------------


class TestFinding25RecordPrimitives:
    def test_record_value_is_entity_id_when_no_pivot(self) -> None:
        """When no pivot is set, 'value' in output='record' must be entity_id string."""
        resolver = _mock_resolver({"France": _make_resolved()})
        result = _dispatch(resolver, ["France"], output="record")
        assert isinstance(result, BulkResult)
        records = result.to_list()
        assert records[0]["value"] == "country/FRA"

    def test_record_value_none_when_no_match(self) -> None:
        """For no-match rows, 'value' must be None."""
        resolver = _mock_resolver({})
        result = _dispatch(resolver, ["unknown"], output="record")
        records = result.to_list()
        assert records[0]["value"] is None

    def test_to_polars_on_record_result_no_crash(self) -> None:
        """BulkResult from output='record' with no pivot must convert to polars."""
        pl = pytest.importorskip("polars")
        resolver = _mock_resolver({"France": _make_resolved()})
        result = _dispatch(resolver, ["France"], output="record")
        # This must not raise 'nested objects are not allowed'.
        polars_series = result.to_polars()
        assert isinstance(polars_series, pl.Series)

    def test_pandas_record_to_polars_no_crash(self) -> None:
        """BulkResult from pandas input, output='record', to_polars() must work."""
        pl = pytest.importorskip("polars")
        pd = pytest.importorskip("pandas")
        resolver = _mock_resolver({"France": _make_resolved()})
        result = _dispatch(resolver, pd.Series(["France"]), output="record")
        polars_series = result.to_polars()
        assert isinstance(polars_series, pl.Series)


# ---------------------------------------------------------------------------
# #30 — enum-ish param validation: on_error, on_ambiguous, on_missing
# ---------------------------------------------------------------------------


class TestFinding30ParamValidation:
    def _base_dispatch(self, **kwargs: Any) -> Any:
        resolver = _mock_resolver({"France": _make_resolved()})
        return _dispatch(resolver, ["France"], **kwargs)

    def test_on_error_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="on_error="):
            self._base_dispatch(on_error="raise2")

    def test_on_error_did_you_mean(self) -> None:
        with pytest.raises(ValueError, match="did you mean 'raise'"):
            self._base_dispatch(on_error="raise2")

    def test_on_ambiguous_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="on_ambiguous="):
            self._base_dispatch(on_ambiguous="Null")

    def test_on_ambiguous_did_you_mean(self) -> None:
        with pytest.raises(ValueError, match="did you mean 'null'"):
            self._base_dispatch(on_ambiguous="Null")

    def test_on_missing_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="on_missing="):
            self._base_dispatch(on_missing="Raise")

    def test_on_missing_did_you_mean(self) -> None:
        with pytest.raises(ValueError, match="did you mean 'raise'"):
            self._base_dispatch(on_missing="Raise")

    def test_valid_values_do_not_raise(self) -> None:
        """Valid parameter strings must not raise."""
        resolver = _mock_resolver({"France": _make_resolved()})
        for on_error in ("raise", "null", "keep"):
            _dispatch(resolver, ["France"], on_error=on_error)
        for on_ambiguous in ("raise", "null", "best"):
            _dispatch(resolver, ["France"], on_ambiguous=on_ambiguous)
        for on_missing in ("raise", "null", "auto"):
            _dispatch(resolver, ["France"], on_missing=on_missing)

    def test_output_still_validated(self) -> None:
        """The existing output= validation must still work after adding new checks."""
        resolver = _mock_resolver({"France": _make_resolved()})
        with pytest.raises(ValueError, match="output="):
            _dispatch(resolver, ["France"])  # type: ignore[call-arg]
            # call via _bulk_dispatch directly
            _bulk_dispatch(
                resolver=resolver,
                values=["France"],
                to=None,
                output="badvalue",
                domain=None,
                context=None,
                from_system=None,
                not_found="null",
                on_error="raise",
                on_ambiguous="null",
                on_missing="auto",
            )


# ---------------------------------------------------------------------------
# #34 — BulkResult repr: angle-bracket style
# ---------------------------------------------------------------------------


class TestFinding34BulkResultRepr:
    def test_repr_starts_with_angle_bracket(self) -> None:
        resolver = _mock_resolver({"France": _make_resolved()})
        result = _dispatch(resolver, ["France"])
        assert isinstance(result, BulkResult)
        r = repr(result)
        assert r.startswith("<BulkResult"), f"Expected angle-bracket repr, got: {r}"
        assert r.endswith(">"), f"Expected repr to end with >, got: {r}"

    def test_repr_contains_counts(self) -> None:
        resolver = _mock_resolver({"France": _make_resolved()})
        result = _dispatch(resolver, ["France"])
        r = repr(result)
        assert "total=1" in r
        assert "resolved=1" in r

    def test_repr_not_eval_able_as_constructor(self) -> None:
        """The repr must not be parseable as BulkResult(...) constructor syntax."""
        resolver = _mock_resolver({"France": _make_resolved()})
        result = _dispatch(resolver, ["France"])
        r = repr(result)
        # angle-bracket form cannot be eval'd as a constructor
        assert "BulkResult(" not in r


# ---------------------------------------------------------------------------
# #36 — TypeError message includes dict and DataFrame hint
# ---------------------------------------------------------------------------


class TestFinding36TypeErrorMessage:
    def test_message_includes_dict(self) -> None:
        """TypeError message must list 'dict' as an accepted type."""

        with pytest.raises(TypeError, match="dict"):
            _detect_input_kind(42)

    def test_polars_dataframe_hint(self) -> None:
        """Passing a polars DataFrame must mention column extraction."""
        pl = pytest.importorskip("polars")
        df = pl.DataFrame({"name": ["France"]})
        with pytest.raises(TypeError, match="col_name"):
            _detect_input_kind(df)

    def test_pandas_dataframe_hint(self) -> None:
        """Passing a pandas DataFrame must mention column extraction."""
        pd = pytest.importorskip("pandas")
        df = pd.DataFrame({"name": ["France"]})
        with pytest.raises(TypeError, match="col_name"):
            _detect_input_kind(df)

    def test_dict_accepted(self) -> None:
        """dict input must be accepted (not raise TypeError)."""
        kind, _ = _detect_input_kind({"a": "France"})
        assert kind == "dict"
