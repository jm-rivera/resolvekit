"""Tests for ParsedEntity / ParseResult / DroppedSpan result types.

All fixtures are constructed directly — no engine, no ahocorasick_rs,
no Resolver needed.  Pandas-dependent tests are gated via
``pytest.importorskip("pandas")``.
"""

from __future__ import annotations

import pytest

from resolvekit.core.model.result import ResolutionResult, ResolutionStatus
from resolvekit.core.parse.result import DroppedSpan, ParsedEntity, ParseResult

# ---------------------------------------------------------------------------
# Helpers — build minimal ParsedEntity / ResolutionResult without a resolver
# ---------------------------------------------------------------------------


def _nil_resolution() -> ResolutionResult:
    """Return a detached NO_MATCH ResolutionResult (no explainer back-ref)."""
    return ResolutionResult(status=ResolutionStatus.NO_MATCH)


def _resolved_resolution() -> ResolutionResult:
    """Return a detached RESOLVED ResolutionResult."""
    return ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        entity_id="geo.KE",
        confidence=0.92,
        pack_id="geo",
    )


def _entity(
    surface: str,
    start: int,
    end: int,
    status: ResolutionStatus = ResolutionStatus.RESOLVED,
    entity_id: str | None = "geo.KE",
    entity_type: str | None = "geo.country",
    pack_id: str | None = "geo",
    confidence: float | None = 0.92,
    resolution: ResolutionResult | None = None,
    row_idx: int | None = None,
    output: str | None = None,
) -> ParsedEntity:
    if resolution is None:
        resolution = (
            _resolved_resolution()
            if status == ResolutionStatus.RESOLVED
            else _nil_resolution()
        )
    return ParsedEntity(
        surface=surface,
        start=start,
        end=end,
        entity_id=entity_id,
        entity_type=entity_type,
        pack_id=pack_id,
        status=status,
        confidence=confidence,
        resolution=resolution,
        row_idx=row_idx,
        output=output,
    )


# ---------------------------------------------------------------------------
# Ordering invariant — caller sorts, ParseResult trusts that order
# ---------------------------------------------------------------------------


class TestOrdering:
    """ParseResult preserves insertion order (caller is responsible for sorting)."""

    def test_presorted_roundtrips(self):
        """A pre-sorted list of entities round-trips unchanged."""
        e1 = _entity("Kenya", 0, 5)
        e2 = _entity("Uganda", 10, 16)
        result = ParseResult(entities=[e1, e2], dropped_spans=[])
        assert list(result) == [e1, e2]

    def test_iteration_preserves_insertion_order(self):
        """Iteration returns entities in the order they were stored."""
        e1 = _entity("B", 5, 6)
        e2 = _entity("A", 0, 1)
        # Deliberately out of offset order — caller did not sort
        result = ParseResult(entities=[e1, e2], dropped_spans=[])
        assert [e.surface for e in result] == ["B", "A"]


# ---------------------------------------------------------------------------
# to_dataframe() — columns, order, row_idx present/absent
# ---------------------------------------------------------------------------


class TestToDataframe:
    """to_dataframe() column set and the row_idx omission/inclusion logic."""

    def test_requires_pandas(self, monkeypatch):
        """Raises a helpful ImportError when pandas is absent."""
        import sys

        # Stub out pandas so the import fails
        original = sys.modules.get("pandas")
        sys.modules["pandas"] = None  # type: ignore[assignment]
        try:
            result = ParseResult(entities=[], dropped_spans=[])
            with pytest.raises(ImportError, match="resolvekit\\[pandas\\]"):
                result.to_dataframe()
        finally:
            if original is None:
                sys.modules.pop("pandas", None)
            else:
                sys.modules["pandas"] = original

    def test_row_idx_absent_on_single_text_path(self):
        """row_idx column is absent when all entities have row_idx=None."""
        pytest.importorskip("pandas")
        e = _entity("Kenya", 0, 5, row_idx=None, output="KE")
        result = ParseResult(entities=[e], dropped_spans=[])
        df = result.to_dataframe()
        assert "row_idx" not in df.columns, "row_idx must be absent on single-text path"

    def test_row_idx_present_on_bulk_path(self):
        """row_idx column is present when any entity has a non-None row_idx."""
        pytest.importorskip("pandas")
        e = _entity("Kenya", 0, 5, row_idx=2, output="KE")
        result = ParseResult(entities=[e], dropped_spans=[])
        df = result.to_dataframe()
        assert "row_idx" in df.columns, (
            "row_idx must be present when any entity has non-None row_idx"
        )
        assert df["row_idx"].iloc[0] == 2

    def test_column_order_without_row_idx(self):
        """Columns are in the expected order when row_idx is omitted."""
        pytest.importorskip("pandas")
        e = _entity("Kenya", 0, 5, output="KE")
        result = ParseResult(entities=[e], dropped_spans=[])
        df = result.to_dataframe()
        expected = [
            "surface",
            "entity_id",
            "entity_type",
            "pack_id",
            "status",
            "confidence",
            "start",
            "end",
            "to",
        ]
        assert list(df.columns) == expected

    def test_column_order_with_row_idx(self):
        """row_idx is prepended when present."""
        pytest.importorskip("pandas")
        e = _entity("Kenya", 0, 5, row_idx=0, output="KE")
        result = ParseResult(entities=[e], dropped_spans=[])
        df = result.to_dataframe()
        expected = [
            "row_idx",
            "surface",
            "entity_id",
            "entity_type",
            "pack_id",
            "status",
            "confidence",
            "start",
            "end",
            "to",
        ]
        assert list(df.columns) == expected

    def test_to_column_holds_output(self):
        """The 'to' column holds ParsedEntity.output."""
        pytest.importorskip("pandas")
        e = _entity("Kenya", 0, 5, output="KE")
        result = ParseResult(entities=[e], dropped_spans=[])
        df = result.to_dataframe()
        assert df["to"].iloc[0] == "KE"

    def test_nil_entity_row(self):
        """NIL (NO_MATCH) entity yields a row with None entity_id and output."""
        pytest.importorskip("pandas")
        nil_e = _entity(
            "xyz",
            19,
            22,
            status=ResolutionStatus.NO_MATCH,
            entity_id=None,
            entity_type=None,
            pack_id="geo",
            confidence=0.1,
            output=None,
        )
        result = ParseResult(entities=[nil_e], dropped_spans=[])
        df = result.to_dataframe()
        assert df["entity_id"].iloc[0] is None
        assert df["to"].iloc[0] is None
        assert df["start"].iloc[0] == 19
        assert df["end"].iloc[0] == 22

    def test_empty_result_returns_empty_dataframe(self):
        """Empty entities list returns a DataFrame with the correct columns."""
        pytest.importorskip("pandas")
        result = ParseResult(entities=[], dropped_spans=[])
        df = result.to_dataframe()
        expected = [
            "surface",
            "entity_id",
            "entity_type",
            "pack_id",
            "status",
            "confidence",
            "start",
            "end",
            "to",
        ]
        assert list(df.columns) == expected
        assert len(df) == 0


# ---------------------------------------------------------------------------
# summary() — counts match a hand-built mix
# ---------------------------------------------------------------------------


class TestSummary:
    """summary() returns the correct per-status counts."""

    def test_counts_match_entities(self):
        resolved = _entity("Kenya", 0, 5, status=ResolutionStatus.RESOLVED)
        no_match = _entity(
            "xyz",
            10,
            13,
            status=ResolutionStatus.NO_MATCH,
            entity_id=None,
            entity_type=None,
            confidence=0.1,
        )
        no_match2 = _entity(
            "abc",
            20,
            23,
            status=ResolutionStatus.NO_MATCH,
            entity_id=None,
            entity_type=None,
            confidence=None,
        )
        result = ParseResult(entities=[resolved, no_match, no_match2], dropped_spans=[])
        s = result.summary()
        assert s.total == 3
        assert s.resolved == 1
        assert s.no_match == 2
        assert s.ambiguous == 0
        assert s.error == 0

    def test_empty_summary(self):
        result = ParseResult(entities=[], dropped_spans=[])
        s = result.summary()
        assert s.total == 0
        assert s.resolved == 0


# ---------------------------------------------------------------------------
# _repr_html_ — non-empty str, escaped surfaces, span visible, empty safe
# ---------------------------------------------------------------------------


class TestReprHtml:
    """_repr_html_ renders non-raising HTML with expected content."""

    def test_contains_surface_and_span(self):
        e = _entity("<Kenya>", 19, 24)
        result = ParseResult(entities=[e], dropped_spans=[])
        html = result._repr_html_()
        assert isinstance(html, str)
        assert len(html) > 0
        # Surface is HTML-escaped
        assert "&lt;Kenya&gt;" in html
        # Span notation visible
        assert "19:24" in html

    def test_empty_entities_does_not_raise(self):
        result = ParseResult(entities=[], dropped_spans=[])
        html = result._repr_html_()
        assert isinstance(html, str)
        assert len(html) > 0

    def test_dropped_hint_appears_when_drops_present(self):
        e = _entity("Kenya", 0, 5)
        drop = DroppedSpan(
            surface="KE", start=6, end=8, pack_id="geo", reason="short_input"
        )
        result = ParseResult(entities=[e], dropped_spans=[drop])
        html = result._repr_html_()
        assert "include_nil=True" in html

    def test_no_dropped_hint_when_empty(self):
        e = _entity("Kenya", 0, 5)
        result = ParseResult(entities=[e], dropped_spans=[])
        html = result._repr_html_()
        assert "include_nil=True" not in html


# ---------------------------------------------------------------------------
# dropped_spans — accessible as-is, DroppedSpan fields accessible
# ---------------------------------------------------------------------------


class TestDroppedSpans:
    """DroppedSpan fields are accessible and round-trip through ParseResult."""

    def test_dropped_span_fields(self):
        drop = DroppedSpan(
            surface="KE",
            start=3,
            end=5,
            pack_id="geo",
            reason="word_boundary",
        )
        assert drop.surface == "KE"
        assert drop.start == 3
        assert drop.end == 5
        assert drop.pack_id == "geo"
        assert drop.reason == "word_boundary"

    def test_dropped_spans_surfaced_in_result(self):
        drop = DroppedSpan("X", 0, 1, "org", "sentinel")
        result = ParseResult(entities=[], dropped_spans=[drop])
        assert result.dropped_spans == [drop]
        assert result.dropped_spans[0].reason == "sentinel"


# ---------------------------------------------------------------------------
# Iteration / len / __getitem__ — parity with a plain list
# ---------------------------------------------------------------------------


class TestCollectionProtocol:
    """ParseResult exposes list-like access over entities."""

    def setup_method(self):
        self.e1 = _entity("Kenya", 0, 5)
        self.e2 = _entity("Uganda", 10, 16)
        self.result = ParseResult(entities=[self.e1, self.e2], dropped_spans=[])

    def test_len(self):
        assert len(self.result) == 2

    def test_len_empty(self):
        assert len(ParseResult(entities=[], dropped_spans=[])) == 0

    def test_iter(self):
        assert list(self.result) == [self.e1, self.e2]

    def test_getitem_int(self):
        assert self.result[0] is self.e1
        assert self.result[1] is self.e2
        assert self.result[-1] is self.e2

    def test_getitem_slice(self):
        assert self.result[0:1] == [self.e1]
        assert self.result[:] == [self.e1, self.e2]

    def test_import_from_barrel(self):
        """Types importable from resolvekit.core.parse."""
        from resolvekit.core.parse import DroppedSpan, ParsedEntity, ParseResult

        assert ParsedEntity is not None
        assert ParseResult is not None
        assert DroppedSpan is not None
