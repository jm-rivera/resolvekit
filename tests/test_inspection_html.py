"""Tests for InspectionReport._repr_html_."""

from resolvekit.core.model.inspection import InspectionReport, InspectMatch


def _make_match(
    entity_id: str = "geo/test",
    matched_field: str | None = "name",
    matched_value: str | None = "Test",
    pack_id: str | None = "geo",
) -> InspectMatch:
    return InspectMatch(
        entity_id=entity_id,
        matched_field=matched_field,
        matched_value=matched_value,
        pack_id=pack_id,
    )


def test_inspection_report_repr_html_renders_query_and_normalized() -> None:
    report = InspectionReport(
        query="Paris",
        normalized="paris",
        exact_name_matches=[
            _make_match(entity_id="city/paris-fr", matched_value="Paris")
        ],
    )
    html = report._repr_html_()
    assert "Paris" in html
    assert "paris" in html


def test_inspection_report_repr_html_renders_three_tables() -> None:
    report = InspectionReport(
        query="Paris",
        normalized="paris",
        exact_code_matches=[_make_match(entity_id="code/PAR")],
        exact_name_matches=[_make_match(entity_id="name/paris-fr")],
        fuzzy_candidates=[_make_match(entity_id="fuzzy/paris-tx")],
    )
    html = report._repr_html_()
    assert "Exact code matches" in html
    assert "Exact name matches" in html
    assert "Fuzzy candidates" in html
    assert "code/PAR" in html
    assert "name/paris-fr" in html
    assert "fuzzy/paris-tx" in html


def test_inspection_report_repr_html_omits_empty_sections() -> None:
    report = InspectionReport(
        query="Paris",
        normalized="paris",
        exact_name_matches=[_make_match(entity_id="name/paris-fr")],
    )
    html = report._repr_html_()
    assert "Exact name matches" in html
    assert "Exact code matches" not in html
    assert "Fuzzy candidates" not in html


def test_inspection_report_repr_html_empty_input_renders_no_input() -> None:
    report = InspectionReport(query="", normalized="")
    html = report._repr_html_()
    assert "no input" in html


def test_inspection_report_repr_html_empty_matches_renders_no_matches() -> None:
    report = InspectionReport(query="x", normalized="x")
    html = report._repr_html_()
    assert "x" in html
    assert "no matches" in html


def test_inspection_report_repr_html_escapes_html_special_chars() -> None:
    payload = "<script>alert('x')</script>"
    report = InspectionReport(query=payload, normalized=payload)
    html_out = report._repr_html_()
    assert "<script>" not in html_out
    assert "&lt;script&gt;" in html_out


def test_inspection_report_repr_html_preserves_as_text_unchanged() -> None:
    report = InspectionReport(
        query="Paris",
        normalized="paris",
        exact_name_matches=[
            _make_match(entity_id="city/paris-fr", matched_value="Paris")
        ],
    )
    text = report.as_text()
    assert text == str(report)
    assert text.startswith("inspect: ")
    assert "query='Paris'" in text
    assert "name_matches=[city/paris-fr]" in text
