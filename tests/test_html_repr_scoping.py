"""sklearn-scoped CSS in _repr_html_ (no global style leakage).

Covers ResolutionResult._repr_html_, BulkResult._repr_html_, and the
cross-verb snap hint in BulkResult when NO_MATCH rows are present.
"""

from __future__ import annotations

import dataclasses
import re

import pytest

from resolvekit.core.model.bulk_result import BulkResult, ResolutionSummary
from resolvekit.core.model.result import ResolutionResult, ResolutionStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolved_result(*, query_text: str = "United States") -> ResolutionResult:
    return ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        entity_id="country/USA",
        confidence=0.99,
        pack_id="geo",
        query_text=query_text,
    )


def _no_match_result(*, query_text: str = "Atlantis") -> ResolutionResult:
    return ResolutionResult(
        status=ResolutionStatus.NO_MATCH,
        query_text=query_text,
    )


def _ambiguous_result(*, query_text: str = "Georgia") -> ResolutionResult:
    return ResolutionResult(
        status=ResolutionStatus.AMBIGUOUS,
        query_text=query_text,
    )


def _make_bulk(
    sources: list[ResolutionResult],
    kind: str = "list",
) -> BulkResult:
    entity_ids = [r.entity_id for r in sources]
    return BulkResult(
        values=entity_ids,
        source=tuple(sources),
        kind=kind,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# ResolutionResult._repr_html_ — scoped CSS
# ---------------------------------------------------------------------------


def _extract_container_ids(html: str) -> list[str]:
    """Match any prefixed rk-* container id (rk-result-N, rk-bulk-N, etc.)."""
    return re.findall(r'id="(rk-[a-z]+-\d+)"', html)


def _extract_style_selectors(html: str) -> list[str]:
    """Extract all CSS selector lines from the <style> block."""
    style_match = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
    if not style_match:
        return []
    lines = []
    for line in style_match.group(1).strip().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("}") and "{" in stripped:
            lines.append(stripped)
    return lines


def test_repr_html_counter_based_container_id() -> None:
    """Two consecutive renders produce different rk-container-N IDs."""
    r1 = _resolved_result()
    r2 = _resolved_result()
    html1 = r1._repr_html_()
    html2 = r2._repr_html_()

    ids1 = _extract_container_ids(html1)
    ids2 = _extract_container_ids(html2)

    assert ids1, "First render has no rk-container-N id"
    assert ids2, "Second render has no rk-container-N id"
    assert ids1[0] != ids2[0], "Consecutive renders must get distinct container IDs"


def test_repr_html_no_global_class_leak() -> None:
    """All CSS selectors in ResolutionResult HTML are scoped under #rk-container-N >."""
    result = _resolved_result()
    html = result._repr_html_()
    ids = _extract_container_ids(html)
    assert ids, "No rk-container-N id found in rendered HTML"
    container_id = ids[0]

    selectors = _extract_style_selectors(html)
    assert selectors, "No CSS selectors found in <style> block"
    for selector in selectors:
        assert selector.startswith(f"#{container_id}"), (
            f"CSS selector not scoped under #{container_id}: {selector!r}"
        )


def test_repr_html_result_contains_status() -> None:
    """Rendered HTML contains the status value."""
    result = _resolved_result()
    html = result._repr_html_()
    assert "resolved" in html


def test_repr_html_result_contains_entity_id() -> None:
    """Rendered HTML contains the entity_id when present."""
    result = _resolved_result()
    html = result._repr_html_()
    assert "country/USA" in html


def test_repr_html_no_match_result_renders_cleanly() -> None:
    """NO_MATCH result renders without errors."""
    result = _no_match_result()
    html = result._repr_html_()
    assert "no_match" in html
    ids = _extract_container_ids(html)
    assert ids, "NO_MATCH render has no rk-container-N id"


# ---------------------------------------------------------------------------
# BulkResult._repr_html_ — scoped CSS
# ---------------------------------------------------------------------------


def test_bulk_repr_html_no_global_class_leak() -> None:
    """All CSS selectors in BulkResult HTML are scoped under #rk-container-N >."""
    bulk = _make_bulk([_resolved_result(), _no_match_result()])
    html = bulk._repr_html_()
    ids = _extract_container_ids(html)
    assert ids, "No rk-container-N id in BulkResult HTML"
    container_id = ids[0]

    selectors = _extract_style_selectors(html)
    assert selectors, "No CSS selectors found in BulkResult <style> block"
    for selector in selectors:
        assert selector.startswith(f"#{container_id}"), (
            f"CSS selector not scoped under #{container_id}: {selector!r}"
        )


def test_bulk_repr_html_counter_advances() -> None:
    """BulkResult renders also advance the global counter giving unique IDs."""
    bulk1 = _make_bulk([_resolved_result()])
    bulk2 = _make_bulk([_resolved_result()])
    html1 = bulk1._repr_html_()
    html2 = bulk2._repr_html_()

    ids1 = _extract_container_ids(html1)
    ids2 = _extract_container_ids(html2)
    assert ids1 and ids2
    assert ids1[0] != ids2[0], "Two BulkResult renders must get distinct container IDs"


# ---------------------------------------------------------------------------
# Cross-pollination IV: snap hint when NO_MATCH rows exist
# ---------------------------------------------------------------------------


def test_bulk_result_repr_html_includes_snap_hint_on_no_match() -> None:
    """When source contains a NO_MATCH row, rendered HTML mentions rk.snap(...)."""
    bulk = _make_bulk([_resolved_result(), _no_match_result(query_text="Atlantis")])
    html = bulk._repr_html_()
    assert "rk.snap(" in html, f"Expected snap hint in HTML but got:\n{html}"


def test_bulk_result_repr_html_no_hint_when_all_resolved() -> None:
    """When all rows are RESOLVED, no snap hint is rendered."""
    bulk = _make_bulk([_resolved_result(), _resolved_result(query_text="Germany")])
    html = bulk._repr_html_()
    assert "rk.snap(" not in html


def test_bulk_result_repr_html_includes_no_match_count() -> None:
    """The snap hint mentions the number of no_match rows."""
    no_match_count = 3
    sources = [
        _no_match_result(query_text=f"Unknown-{i}") for i in range(no_match_count)
    ]
    bulk = _make_bulk(sources)
    html = bulk._repr_html_()
    assert str(no_match_count) in html


def test_bulk_result_repr_html_query_text_in_hint() -> None:
    """The snap hint shows query_text examples from NO_MATCH rows."""
    bulk = _make_bulk([_no_match_result(query_text="Atlantis")])
    html = bulk._repr_html_()
    assert "Atlantis" in html


# ---------------------------------------------------------------------------
# BulkResult dataclass structure
# ---------------------------------------------------------------------------


def test_bulk_result_is_dataclass_not_pydantic() -> None:
    """BulkResult is a dataclass, not a pydantic BaseModel."""
    assert dataclasses.is_dataclass(BulkResult), "BulkResult must be a dataclass"
    # Confirm no pydantic ancestry
    from pydantic import BaseModel

    assert not issubclass(BulkResult, BaseModel), (
        "BulkResult must not inherit from pydantic.BaseModel"
    )


def test_bulk_result_iter_and_len() -> None:
    """BulkResult supports __iter__ and __len__."""
    sources = [_resolved_result(), _no_match_result()]
    bulk = _make_bulk(sources)
    assert len(bulk) == 2
    items = list(bulk)
    assert items[0].status == ResolutionStatus.RESOLVED
    assert items[1].status == ResolutionStatus.NO_MATCH


def test_bulk_result_getitem_by_index() -> None:
    """BulkResult[i] returns the i-th ResolutionResult."""
    sources = [_resolved_result(), _no_match_result()]
    bulk = _make_bulk(sources)
    assert bulk[0].status == ResolutionStatus.RESOLVED
    assert bulk[1].status == ResolutionStatus.NO_MATCH


def test_bulk_result_getitem_by_slice() -> None:
    """BulkResult[a:b] returns a tuple slice from source."""
    sources = [_resolved_result(), _no_match_result(), _ambiguous_result()]
    bulk = _make_bulk(sources)
    sliced = bulk[1:]
    assert len(sliced) == 2  # type: ignore[arg-type]


def test_bulk_result_summary_counts() -> None:
    """summary() totals add up: resolved + ambiguous + no_match + error == total."""
    sources = [
        _resolved_result(),
        _no_match_result(),
        _ambiguous_result(),
        ResolutionResult(status=ResolutionStatus.ERROR),
    ]
    bulk = _make_bulk(sources)
    s = bulk.summary()
    assert s.total == 4
    assert s.resolved == 1
    assert s.no_match == 1
    assert s.ambiguous == 1
    assert s.error == 1
    assert s.resolved + s.ambiguous + s.no_match + s.error == s.total


def test_bulk_result_summary_is_resolution_summary() -> None:
    """summary() returns a ResolutionSummary NamedTuple."""
    bulk = _make_bulk([_resolved_result()])
    s = bulk.summary()
    assert isinstance(s, ResolutionSummary)


def test_bulk_result_failures_excludes_resolved() -> None:
    """failures property contains only non-RESOLVED rows."""
    sources = [_resolved_result(), _no_match_result(), _ambiguous_result()]
    bulk = _make_bulk(sources)
    failures = bulk.failures
    assert all(r.status != ResolutionStatus.RESOLVED for r in failures.source)
    assert len(failures) == 2


def test_bulk_result_failures_empty_when_all_resolved() -> None:
    """failures is empty when all rows are RESOLVED."""
    sources = [_resolved_result(), _resolved_result(query_text="Germany")]
    bulk = _make_bulk(sources)
    assert len(bulk.failures) == 0


def test_bulk_result_to_list() -> None:
    """to_list() converts values to a Python list."""
    sources = [_resolved_result()]
    entity_ids = ["country/USA"]
    bulk = BulkResult(values=entity_ids, source=tuple(sources), kind="list")
    result_list = bulk.to_list()
    assert isinstance(result_list, list)
    assert result_list == entity_ids


def test_bulk_result_explain_returns_none_for_detached_rows() -> None:
    """BulkResult.explain() returns None for rows without a live resolver."""
    bulk = _make_bulk([_resolved_result()])
    scorecards = bulk.explain()
    assert scorecards == [None]


def test_bulk_result_unnest_returns_records_for_list_kind() -> None:
    """BulkResult.unnest() returns a list of dicts when kind='list'."""
    bulk = _make_bulk([_resolved_result()])
    records = bulk.unnest()
    assert isinstance(records, list)
    assert records[0]["entity_id"] == "country/USA"
    assert records[0]["status"] == "resolved"


def test_bulk_result_unnest_returns_pandas_dataframe_when_kind_pandas() -> None:
    """BulkResult.unnest() returns a pd.DataFrame when kind='pandas'."""
    pd = pytest.importorskip("pandas")
    bulk = _make_bulk([_resolved_result()], kind="pandas")
    df = bulk.unnest()
    assert isinstance(df, pd.DataFrame)
    assert "entity_id" in df.columns


def test_bulk_result_unnest_returns_polars_dataframe_when_kind_polars() -> None:
    """BulkResult.unnest() returns a pl.DataFrame when kind='polars'."""
    pl = pytest.importorskip("polars")
    bulk = _make_bulk([_resolved_result()], kind="polars")
    df = bulk.unnest()
    assert isinstance(df, pl.DataFrame)
    assert "entity_id" in df.columns


# ---------------------------------------------------------------------------
# Optional: pandas / polars integration (skipped when not installed)
# ---------------------------------------------------------------------------


def test_bulk_result_to_pandas_returns_pandas_series() -> None:
    """to_pandas() returns a pd.Series when pandas is installed."""
    pd = pytest.importorskip("pandas")
    sources = [_resolved_result()]
    bulk = BulkResult(values=["country/USA"], source=tuple(sources), kind="list")
    series = bulk.to_pandas()
    assert isinstance(series, pd.Series)
    assert list(series) == ["country/USA"]


def test_bulk_result_to_polars_returns_polars_series() -> None:
    """to_polars() returns a pl.Series when polars is installed."""
    pl = pytest.importorskip("polars")
    sources = [_resolved_result()]
    bulk = BulkResult(values=["country/USA"], source=tuple(sources), kind="list")
    series = bulk.to_polars()
    assert isinstance(series, pl.Series)
    assert series.to_list() == ["country/USA"]


def test_bulk_result_to_pandas_passthrough_when_kind_pandas() -> None:
    """to_pandas() returns the values directly when kind is 'pandas'."""
    pd = pytest.importorskip("pandas")
    values = pd.Series(["country/USA"])
    sources = [_resolved_result()]
    bulk = BulkResult(values=values, source=tuple(sources), kind="pandas")
    result = bulk.to_pandas()
    assert result is values


def test_bulk_result_to_list_raises_for_frame_values() -> None:
    """to_list() refuses to enumerate columns of an output='frame' DataFrame."""
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame([{"value": "USA", "status": "resolved"}])
    bulk = BulkResult(values=df, source=(_resolved_result(),), kind="pandas")
    with pytest.raises(TypeError, match="frame"):
        bulk.to_list()


def test_bulk_result_to_pandas_raises_for_frame_values() -> None:
    """to_pandas() refuses to misrepresent a DataFrame as a Series."""
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame([{"value": "USA", "status": "resolved"}])
    bulk = BulkResult(values=df, source=(_resolved_result(),), kind="pandas")
    with pytest.raises(TypeError, match="frame"):
        bulk.to_pandas()


def test_bulk_result_failures_preserves_dataframe_shape() -> None:
    """failures on output='frame' BulkResult slices rows of the DataFrame."""
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame(
        [
            {"value": "USA", "status": "resolved"},
            {"value": None, "status": "no_match"},
        ]
    )
    sources = [_resolved_result(), _no_match_result()]
    bulk = BulkResult(values=df, source=tuple(sources), kind="pandas")
    failures = bulk.failures
    assert isinstance(failures.values, pd.DataFrame)
    assert len(failures.values) == 1
    assert failures.values.iloc[0]["status"] == "no_match"
    assert failures.kind == "pandas"
