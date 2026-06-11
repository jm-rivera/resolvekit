"""Tests for BulkResult.to_review() and BulkResult.to_crosswalk().

Covers:
- to_review: documented column headers
- to_review: dedup by query_text
- to_review: RESOLVED rows absent from review file
- to_review: zero hard cases → header-only file (no error)
- to_crosswalk: merges auto (RESOLVED) and manual (review chosen)
- to_crosswalk: IGNORE token in review chosen → IGNORE entry
- to_crosswalk: no review → auto-only
- to_crosswalk: missing required columns raises ValueError
- End-to-end round-trip: bulk → to_review → fill chosen → to_crosswalk → bulk(crosswalk=)
- pandas-absent: monkeypatch sys.modules → no ImportError
"""

from __future__ import annotations

import csv
import pathlib
from typing import Any
from unittest.mock import MagicMock

import pytest

from resolvekit.core.api.bulk import _bulk_dispatch
from resolvekit.core.model.bulk_result import BulkResult
from resolvekit.core.model.crosswalk import Crosswalk
from resolvekit.core.model.result import (
    CandidateSummary,
    ReasonCode,
    ResolutionResult,
    ResolutionStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_resolved(
    query_text: str,
    entity_id: str = "country/FRA",
    iso3: str = "FRA",
) -> ResolutionResult:
    from resolvekit.core.model.entity import CodeRecord, EntityRecord

    entity = EntityRecord(
        entity_id=entity_id,
        entity_type="geo.country",
        canonical_name=query_text,
        canonical_name_norm=query_text.lower(),
        codes=[CodeRecord(system="iso3", value=iso3, value_norm=iso3.lower())],
    )
    return ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        entity_id=entity_id,
        entity=entity,
        query_text=query_text,
        reasons=[ReasonCode.EXACT_NAME_MATCH],
    )


def _make_ambiguous(
    query_text: str, candidates: list[CandidateSummary] | None = None
) -> ResolutionResult:
    if candidates is None:
        candidates = [
            CandidateSummary(
                entity_id="country/COD",
                canonical_name="Congo",
                confidence=0.75,
            ),
            CandidateSummary(
                entity_id="country/COG",
                canonical_name="Congo-Brazzaville",
                confidence=0.72,
            ),
        ]
    return ResolutionResult(
        status=ResolutionStatus.AMBIGUOUS,
        candidates=candidates,
        query_text=query_text,
        reasons=[ReasonCode.AMBIGUOUS_LOW_GAP],
    )


def _make_no_match(query_text: str) -> ResolutionResult:
    return ResolutionResult(
        status=ResolutionStatus.NO_MATCH,
        query_text=query_text,
        reasons=[ReasonCode.NO_CANDIDATES],
    )


def _make_bulk_result(
    source: list[ResolutionResult], values: list[Any] | None = None
) -> BulkResult:
    if values is None:
        values = [None] * len(source)
    return BulkResult(values=values, source=source, kind="list")


def _mock_resolver_with_entity(entities_by_id: dict[str, object]) -> MagicMock:
    from resolvekit.core.model.result import ResolutionResultList

    resolver = MagicMock()
    resolver._routing_mode = None
    resolver._runner.available_packs = frozenset({"geo"})
    resolver._runner.get_entity.side_effect = entities_by_id.get
    resolver._resolve_many_internal.side_effect = lambda texts, **kw: (
        ResolutionResultList(
            [
                ResolutionResult(
                    status=ResolutionStatus.NO_MATCH, reasons=[ReasonCode.NO_CANDIDATES]
                )
                for _ in texts
            ]
        )
    )
    return resolver


# ---------------------------------------------------------------------------
# to_review: documented columns
# ---------------------------------------------------------------------------


def test_to_review_writes_documented_columns(tmp_path: pathlib.Path) -> None:
    """Header has value,status,cand_1_id,cand_1_name,cand_1_conf,...,chosen,note."""
    br = _make_bulk_result([_make_ambiguous("Congo")])
    review_path = tmp_path / "review.csv"
    br.to_review(review_path, top_n=3)

    with review_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames is not None
        expected = [
            "value",
            "status",
            "cand_1_id",
            "cand_1_name",
            "cand_1_conf",
            "cand_2_id",
            "cand_2_name",
            "cand_2_conf",
            "cand_3_id",
            "cand_3_name",
            "cand_3_conf",
            "chosen",
            "note",
        ]
        assert reader.fieldnames == expected

        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["value"] == "Congo"
        assert rows[0]["status"] == "ambiguous"
        assert rows[0]["cand_1_id"] == "country/COD"
        assert rows[0]["cand_1_name"] == "Congo"
        assert rows[0]["chosen"] == ""
        assert rows[0]["note"] == ""


def test_to_review_candidates_from_source(tmp_path: pathlib.Path) -> None:
    """Candidates pulled from source[i].candidates."""
    cands = [
        CandidateSummary(
            entity_id="country/COD", canonical_name="Congo", confidence=0.8
        ),
        CandidateSummary(
            entity_id="country/COG", canonical_name="Congo-Brazzaville", confidence=0.75
        ),
    ]
    br = _make_bulk_result([_make_ambiguous("Congo", candidates=cands)])
    review_path = tmp_path / "review.csv"
    br.to_review(review_path, top_n=2)

    with review_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    assert rows[0]["cand_1_id"] == "country/COD"
    assert rows[0]["cand_1_name"] == "Congo"
    assert rows[0]["cand_2_id"] == "country/COG"
    assert rows[0]["cand_2_name"] == "Congo-Brazzaville"
    # Confidence formatted as float string
    assert float(rows[0]["cand_1_conf"]) == pytest.approx(0.8, abs=1e-4)


# ---------------------------------------------------------------------------
# to_review: dedup
# ---------------------------------------------------------------------------


def test_to_review_dedups(tmp_path: pathlib.Path) -> None:
    """Repeated ambiguous query_text → single review row."""
    br = _make_bulk_result(
        [
            _make_ambiguous("Congo"),
            _make_ambiguous("Congo"),  # duplicate
            _make_ambiguous("France"),
        ]
    )
    review_path = tmp_path / "review.csv"
    br.to_review(review_path)

    with review_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    assert len(rows) == 2
    values = [r["value"] for r in rows]
    assert "Congo" in values
    assert "France" in values


# ---------------------------------------------------------------------------
# to_review: skips resolved
# ---------------------------------------------------------------------------


def test_to_review_skips_resolved(tmp_path: pathlib.Path) -> None:
    """RESOLVED rows are absent from the review file."""
    br = _make_bulk_result(
        [
            _make_resolved("France"),
            _make_ambiguous("Congo"),
        ]
    )
    review_path = tmp_path / "review.csv"
    br.to_review(review_path)

    with review_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    # Only Congo (ambiguous) should appear.
    assert len(rows) == 1
    assert rows[0]["value"] == "Congo"


# ---------------------------------------------------------------------------
# to_review: zero hard cases → header-only
# ---------------------------------------------------------------------------


def test_to_review_zero_hard_cases_header_only(tmp_path: pathlib.Path) -> None:
    """All RESOLVED → header-only file; no error raised."""
    br = _make_bulk_result([_make_resolved("France"), _make_resolved("Germany")])
    review_path = tmp_path / "review.csv"
    br.to_review(review_path)  # must not raise

    with review_path.open(newline="", encoding="utf-8") as fh:
        content = fh.read()

    lines = [ln for ln in content.splitlines() if ln]
    assert len(lines) == 1  # header only
    assert "value" in lines[0]
    assert "chosen" in lines[0]


# ---------------------------------------------------------------------------
# to_crosswalk: auto-only
# ---------------------------------------------------------------------------


def test_to_crosswalk_no_review() -> None:
    """to_crosswalk() with no file → auto map from RESOLVED rows only."""
    br = _make_bulk_result(
        [
            _make_resolved("France", "country/FRA"),
            _make_resolved("Germany", "country/DEU"),
            _make_no_match("Ruritania"),
        ]
    )
    cw = br.to_crosswalk()

    assert isinstance(cw, Crosswalk)
    assert len(cw) == 2
    assert "France" in cw
    assert "Germany" in cw
    assert "Ruritania" not in cw
    assert cw._get("France") == "country/FRA"
    assert cw._get("Germany") == "country/DEU"


# ---------------------------------------------------------------------------
# to_crosswalk: merges auto and manual
# ---------------------------------------------------------------------------


def test_to_crosswalk_merges_auto_and_manual(tmp_path: pathlib.Path) -> None:
    """Auto RESOLVED entries + filled review chosen → merged; manual overrides auto."""
    br = _make_bulk_result(
        [
            _make_resolved("France", "country/FRA"),
            _make_ambiguous("Congo"),
        ]
    )

    review_path = tmp_path / "review.csv"
    br.to_review(review_path)

    # Fill in the chosen column for Congo.
    rows: list[dict[str, str]] = []
    with review_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        for row in reader:
            if row["value"] == "Congo":
                row["chosen"] = "country/COD"
            rows.append(row)

    with review_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    cw = br.to_crosswalk(review=review_path)

    assert "France" in cw
    assert "Congo" in cw
    assert cw._get("France") == "country/FRA"
    assert cw._get("Congo") == "country/COD"


def test_to_crosswalk_manual_overrides_auto(tmp_path: pathlib.Path) -> None:
    """If a value appears in both auto (RESOLVED) and review, manual wins."""
    # France is RESOLVED → auto map has France→country/FRA.
    # Review file overrides France→country/DEU (human decision).
    br = _make_bulk_result([_make_resolved("France", "country/FRA")])

    review_csv = tmp_path / "review.csv"
    review_csv.write_text(
        "value,chosen\nFrance,country/DEU\n",
        encoding="utf-8",
    )

    cw = br.to_crosswalk(review=review_csv)
    assert cw._get("France") == "country/DEU"


# ---------------------------------------------------------------------------
# to_crosswalk: IGNORE token
# ---------------------------------------------------------------------------


def test_to_crosswalk_ignore_token(tmp_path: pathlib.Path) -> None:
    """Review chosen='IGNORE' → IGNORE entry in the resulting Crosswalk."""
    br = _make_bulk_result([_make_ambiguous("Ruritania")])

    review_path = tmp_path / "review.csv"
    br.to_review(review_path)

    # Fill chosen with IGNORE for Ruritania.
    rows: list[dict[str, str]] = []
    with review_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        for row in reader:
            row["chosen"] = "IGNORE"
            rows.append(row)

    with review_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    cw = br.to_crosswalk(review=review_path, strict=False)
    assert "Ruritania" in cw
    # IGNORE maps to internal None.
    assert cw._get("Ruritania") is None


# ---------------------------------------------------------------------------
# to_crosswalk: missing columns raises
# ---------------------------------------------------------------------------


def test_to_crosswalk_missing_columns_raises(tmp_path: pathlib.Path) -> None:
    """review CSV missing value or chosen raises ValueError."""
    br = _make_bulk_result([_make_resolved("France", "country/FRA")])

    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("name,decision\nFrance,country/FRA\n", encoding="utf-8")

    with pytest.raises(ValueError, match="'value','chosen'"):
        br.to_crosswalk(review=bad_csv)


# ---------------------------------------------------------------------------
# End-to-end round-trip
# ---------------------------------------------------------------------------


def test_review_roundtrip_e2e(tmp_path: pathlib.Path) -> None:
    """build → to_review → fill chosen → to_crosswalk → bulk(crosswalk=) resolves.

    The value ("Congo") ends up in the crosswalk and resolves on the second
    bulk() call without touching the normal resolution path.
    """
    from resolvekit.core.model.entity import CodeRecord, EntityRecord
    from resolvekit.core.model.result import ResolutionResultList

    cod_entity = EntityRecord(
        entity_id="country/COD",
        entity_type="geo.country",
        canonical_name="Congo",
        canonical_name_norm="congo",
        codes=[CodeRecord(system="iso3", value="COD", value_norm="cod")],
    )

    # First resolver returns ambiguous for Congo.
    resolver1 = MagicMock()
    resolver1._routing_mode = None
    resolver1._runner.available_packs = frozenset({"geo"})
    resolver1._runner.get_entity.side_effect = lambda eid: (
        cod_entity if eid == "country/COD" else None
    )
    resolver1._resolve_many_internal.side_effect = lambda texts, **kw: (
        ResolutionResultList([_make_ambiguous(t) for t in texts])
    )

    br = _bulk_dispatch(
        resolver=resolver1,
        values=["Congo"],
        to=None,
        output="series",
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )
    assert isinstance(br, BulkResult)

    # Write review.
    review_path = tmp_path / "review.csv"
    br.to_review(review_path)

    # Fill in chosen.
    rows: list[dict[str, str]] = []
    with review_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        for row in reader:
            if row["value"] == "Congo":
                row["chosen"] = "country/COD"
            rows.append(row)
    with review_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    cw = br.to_crosswalk(review=review_path, strict=False)
    assert cw._get("Congo") == "country/COD"

    # Second bulk() call with the crosswalk resolves Congo.
    resolver2 = MagicMock()
    resolver2._routing_mode = None
    resolver2._runner.available_packs = frozenset({"geo"})
    resolver2._runner.get_entity.side_effect = lambda eid: (
        cod_entity if eid == "country/COD" else None
    )
    resolver2._resolve_many_internal.side_effect = lambda texts, **kw: (
        ResolutionResultList(
            [
                ResolutionResult(
                    status=ResolutionStatus.NO_MATCH, reasons=[ReasonCode.NO_CANDIDATES]
                )
                for _ in texts
            ]
        )
    )

    result = _bulk_dispatch(
        resolver=resolver2,
        values=["Congo"],
        to="iso3",
        output="series",
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
        crosswalk=cw,
    )
    assert result == ["COD"]


# ---------------------------------------------------------------------------
# pandas-absent path
# ---------------------------------------------------------------------------


def test_pandas_absent_review_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Entire round-trip works with pandas and polars absent (no ImportError)."""
    import sys

    monkeypatch.setitem(sys.modules, "pandas", None)  # type: ignore[arg-type]
    monkeypatch.setitem(sys.modules, "polars", None)  # type: ignore[arg-type]

    from resolvekit.core.model.entity import CodeRecord, EntityRecord
    from resolvekit.core.model.result import ResolutionResultList

    fra_entity = EntityRecord(
        entity_id="country/FRA",
        entity_type="geo.country",
        canonical_name="France",
        canonical_name_norm="france",
        codes=[CodeRecord(system="iso3", value="FRA", value_norm="fra")],
    )
    fra_result = ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        entity_id="country/FRA",
        entity=fra_entity,
        query_text="France",
        reasons=[ReasonCode.EXACT_NAME_MATCH],
    )

    resolver = MagicMock()
    resolver._routing_mode = None
    resolver._runner.available_packs = frozenset({"geo"})
    resolver._runner.get_entity.side_effect = lambda eid: (
        fra_entity if eid == "country/FRA" else None
    )
    resolver._resolve_many_internal.side_effect = lambda texts, **kw: (
        ResolutionResultList(
            [
                fra_result
                if t == "France"
                else ResolutionResult(
                    status=ResolutionStatus.NO_MATCH, reasons=[ReasonCode.NO_CANDIDATES]
                )
                for t in texts
            ]
        )
    )

    # Run bulk with a list input (not pandas/polars).
    br = _bulk_dispatch(
        resolver=resolver,
        values=["France"],
        to=None,
        output="series",
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )
    assert isinstance(br, BulkResult)

    review_path = tmp_path / "review.csv"
    br.to_review(review_path)  # no pandas needed

    cw = br.to_crosswalk(review=None)  # no pandas needed
    assert "France" in cw

    # Second bulk with crosswalk.
    result = _bulk_dispatch(
        resolver=resolver,
        values=["France"],
        to="iso3",
        output="series",
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
        crosswalk=cw,
    )
    assert result == ["FRA"]
