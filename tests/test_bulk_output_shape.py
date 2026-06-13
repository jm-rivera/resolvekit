"""Pin output='frame' column names, order, dtypes, and index.

These assertions guard the _build_frame_native / _frame_columns_from_output
implementation so that behaviour-equivalence is machine-checked.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from resolvekit.core.api.bulk import _bulk_dispatch
from resolvekit.core.model.result import ReasonCode, ResolutionResult, ResolutionStatus

# ---------------------------------------------------------------------------
# Helpers — mirror the mock from test_bulk_dispatch
# ---------------------------------------------------------------------------

_EXPECTED_COLUMNS = [
    "value",
    "status",
    "entity_id",
    "confidence",
    "pack_id",
    "query_text",
]


def _make_result(
    status: ResolutionStatus = ResolutionStatus.RESOLVED,
    entity_id: str | None = "country/USA",
) -> ResolutionResult:
    return ResolutionResult(
        status=status,
        entity_id=entity_id,
        reasons=(ReasonCode.EXACT_NAME_MATCH,),
    )


def _make_entity(entity_id: str = "country/USA", iso3: str = "USA") -> object:
    from resolvekit.core.model.entity import CodeRecord, EntityRecord

    return EntityRecord(
        entity_id=entity_id,
        entity_type="geo.country",
        canonical_name="United States",
        canonical_name_norm="united states",
        codes=[
            CodeRecord(system="iso3", value=iso3, value_norm=iso3.lower()),
        ],
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
            [
                results_by_text.get(t, _make_result(ResolutionStatus.NO_MATCH, None))
                for t in texts
            ]
        )

    resolver._resolve_many_internal.side_effect = _resolve_many_internal
    return resolver


def _dispatch_frame(values, *, resolver, to="iso3"):
    return _bulk_dispatch(
        resolver=resolver,
        values=values,
        to=to,
        output="frame",
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )


# ---------------------------------------------------------------------------
# pandas frame: column names, order, dtypes, index
# ---------------------------------------------------------------------------


def test_frame_pandas_column_names_and_order():
    pd = pytest.importorskip("pandas")
    entity = _make_entity()
    result_obj = _make_result().model_copy(update={"entity": entity})
    resolver = _mock_resolver({"United States": result_obj})

    out = _dispatch_frame(
        pd.Series(["United States"], name="country"), resolver=resolver
    )

    assert list(out.values.columns) == _EXPECTED_COLUMNS


def test_frame_pandas_values():
    pd = pytest.importorskip("pandas")
    entity = _make_entity()
    result_obj = _make_result().model_copy(update={"entity": entity})
    resolver = _mock_resolver({"United States": result_obj})

    out = _dispatch_frame(
        pd.Series(["United States"], name="country"), resolver=resolver
    )
    df = out.values

    assert df.loc[0, "value"] == "USA"
    assert df.loc[0, "status"] == "resolved"
    assert df.loc[0, "entity_id"] == "country/USA"


def test_frame_pandas_index_preserved():
    """orig_index is forwarded, so the DataFrame carries the original Series index."""
    pd = pytest.importorskip("pandas")
    entity = _make_entity()
    result_obj = _make_result().model_copy(update={"entity": entity})
    resolver = _mock_resolver({"United States": result_obj})

    orig = pd.Series(["United States"], index=[42], name="country")
    out = _dispatch_frame(orig, resolver=resolver)

    assert list(out.values.index) == [42]


def test_frame_pandas_no_match_row():
    pd = pytest.importorskip("pandas")
    resolver = _mock_resolver({})  # everything is NO_MATCH

    out = _dispatch_frame(pd.Series(["Atlantis"]), resolver=resolver)
    df = out.values

    assert list(df.columns) == _EXPECTED_COLUMNS
    assert df.loc[0, "status"] == "no_match"
    assert df.loc[0, "value"] is None


def test_frame_pandas_mixed_rows():
    """Resolved and unresolved rows in the same frame — all columns present."""
    pd = pytest.importorskip("pandas")
    entity = _make_entity()
    result_obj = _make_result().model_copy(update={"entity": entity})
    resolver = _mock_resolver({"United States": result_obj})

    out = _dispatch_frame(pd.Series(["United States", "Atlantis"]), resolver=resolver)
    df = out.values

    assert list(df.columns) == _EXPECTED_COLUMNS
    assert len(df) == 2
    assert df.loc[0, "value"] == "USA"
    assert df.loc[1, "value"] is None


# ---------------------------------------------------------------------------
# polars frame: column names, order, values
# ---------------------------------------------------------------------------


def test_frame_polars_column_names_and_order():
    pl = pytest.importorskip("polars")
    entity = _make_entity()
    result_obj = _make_result().model_copy(update={"entity": entity})
    resolver = _mock_resolver({"United States": result_obj})

    out = _dispatch_frame(pl.Series(["United States"]), resolver=resolver)

    assert out.values.columns == _EXPECTED_COLUMNS


def test_frame_polars_values():
    pl = pytest.importorskip("polars")
    entity = _make_entity()
    result_obj = _make_result().model_copy(update={"entity": entity})
    resolver = _mock_resolver({"United States": result_obj})

    out = _dispatch_frame(pl.Series(["United States"]), resolver=resolver)
    df = out.values

    assert df["value"][0] == "USA"
    assert df["status"][0] == "resolved"
    assert df["entity_id"][0] == "country/USA"


# ---------------------------------------------------------------------------
# list-kind: list-of-dicts preserved
# ---------------------------------------------------------------------------


def test_frame_list_kind_returns_list_of_dicts():
    entity = _make_entity()
    result_obj = _make_result().model_copy(update={"entity": entity})
    resolver = _mock_resolver({"United States": result_obj})

    out = _dispatch_frame(["United States"], resolver=resolver)

    records = out.values
    assert isinstance(records, list)
    assert records[0]["entity_id"] == "country/USA"
    assert records[0]["status"] == "resolved"
    assert records[0]["value"] == "USA"
    assert list(records[0].keys()) == _EXPECTED_COLUMNS


# ---------------------------------------------------------------------------
# single-pass counter — warn fires when all resolved rows are None
# ---------------------------------------------------------------------------


def test_spec_warn_fires_when_all_resolved_values_are_none():
    """The single-pass counter warns exactly when every resolved row returned None."""
    import warnings

    pd = pytest.importorskip("pandas")
    from resolvekit.core.api.output_spec import UNSET as _UNSET
    from resolvekit.core.api.output_spec import compile_output_spec
    from resolvekit.core.model.entity import EntityRecord

    # Build an entity with no iso3 attribute so apply_output returns None.
    bare_entity = EntityRecord(
        entity_id="country/TST",
        entity_type="geo.country",
        canonical_name="Testland",
        canonical_name_norm="testland",
        codes=[],  # no iso3
    )
    result_obj = ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        entity_id="country/TST",
        reasons=(ReasonCode.EXACT_NAME_MATCH,),
    ).model_copy(update={"entity": bare_entity})

    resolver = _mock_resolver({"Testland": result_obj})
    resolver._runner.available_packs = frozenset({"geo"})

    # Compile a spec that asks for "iso3"; the entity has no iso3 → value=None.
    spec = compile_output_spec(
        "iso3",
        on_missing="null",
        known_systems=frozenset({"iso3"}),
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _bulk_dispatch(
            resolver=resolver,
            values=pd.Series(["Testland"]),
            to=_UNSET,  # activates spec_active path
            output="series",
            domain=None,
            context=None,
            from_system=None,
            not_found="null",
            on_error="raise",
            on_ambiguous="null",
            output_spec=spec,
        )

    user_warns = [w for w in caught if issubclass(w.category, UserWarning)]
    assert len(user_warns) == 1
    assert "wholly empty" in str(user_warns[0].message)
