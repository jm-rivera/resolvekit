"""Unit tests for the OECD DAC refresh script (scripts/data_maintenance/refresh_oecd_dac.py)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "oecd"


def _load_fixture(filename: str) -> bytes:
    path = _FIXTURES / filename
    if not path.exists():
        pytest.skip(
            f"Fixture {filename} not yet captured — run --capture-fixtures first"
        )
    return path.read_bytes()


# ---------------------------------------------------------------------------
# Parse-shape tests (depend on captured fixtures)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_recipients_shape() -> None:
    from scripts.data_maintenance.refresh_oecd_dac import parse_codelist

    raw = _load_fixture("codelist_13.json")
    rows = parse_codelist(raw, codelist_id="13")

    assert len(rows) >= 100, f"Expected >=100 active recipients, got {len(rows)}"
    for row in rows:
        assert "code" in row
        assert "name_en" in row
        assert "name_fr" in row
        assert "iso3" in row
        assert "type" in row

    codes = [r["code"] for r in rows]
    assert codes == sorted(codes), "Rows should be sorted by code"


@pytest.mark.unit
def test_parse_providers_shape() -> None:
    from scripts.data_maintenance.refresh_oecd_dac import parse_codelist

    raw = _load_fixture("codelist_5.json")
    rows = parse_codelist(raw, codelist_id="5")

    assert len(rows) >= 100, f"Expected >=100 active providers, got {len(rows)}"
    for row in rows:
        assert "code" in row
        assert "name_en" in row
        assert "name_fr" in row
        assert "iso3" in row
        assert "type" in row

    iso3_populated = [r for r in rows if r["iso3"] is not None]
    assert len(iso3_populated) >= 50, "Expected >=50 providers to have iso3"

    codes = [r["code"] for r in rows]
    assert codes == sorted(codes)


@pytest.mark.unit
def test_parse_channels_shape() -> None:
    from scripts.data_maintenance.refresh_oecd_dac import parse_codelist

    raw = _load_fixture("codelist_3.json")
    rows = parse_codelist(raw, codelist_id="3")

    assert len(rows) >= 300, f"Expected >=300 active channels, got {len(rows)}"
    for row in rows:
        assert "code" in row
        assert "category" in row
        assert "name_en" in row
        assert "name_fr" in row

    codes = [r["code"] for r in rows]
    assert codes == sorted(codes)


@pytest.mark.unit
def test_parse_agencies_shape() -> None:
    from scripts.data_maintenance.refresh_oecd_dac import parse_codelist

    raw = _load_fixture("codelist_16.json")
    rows = parse_codelist(raw, codelist_id="16")

    assert len(rows) >= 500, f"Expected >=500 active agencies, got {len(rows)}"
    for row in rows:
        assert "code" in row
        assert "donor_code" in row
        assert "name_en" in row
        assert "name_fr" in row
        assert "acronym" in row


# ---------------------------------------------------------------------------
# Main function tests (monkey-patched, no fixtures needed)
# ---------------------------------------------------------------------------


def _envelope(name: str, item: dict[str, Any]) -> bytes:
    """Wrap a single codelist-item dict in the OECD JSON envelope shape."""
    return json.dumps(
        {
            "codelists": {
                "date-last-modified": "2026-01-01",
                "codelist": [
                    {"name": name, "codelist-items": {"codelist-item": [item]}}
                ],
            }
        }
    ).encode()


_FIXTURE_BY_ID = {
    "13": _envelope(
        "Recipients",
        {
            "status": "active",
            "code": "5",
            "name": {"narrative": ["Türkiye", {"xml:lang": "fr", "#text": "Türkiye"}]},
            "type": "Country",
            "iso-alpha-3-code": "TUR",
        },
    ),
    "5": _envelope(
        "Providers",
        {
            "status": "Active",
            "code": "1",
            "name": {"narrative": ["Austria", {"xml:lang": "fr", "#text": "Autriche"}]},
            "type": "DAC member",
            "iso-alpha-3-code": "AUT",
        },
    ),
    "3": _envelope(
        "Channels",
        {
            "status": "Active",
            "code": "10000",
            "name": {
                "narrative": [
                    "Public Sector Institutions",
                    {"xml:lang": "fr", "#text": "Institutions du secteur public"},
                ]
            },
            "category": "10000",
        },
    ),
    "16": _envelope(
        "Agencies",
        {
            "status": "Active",
            "code": "1",
            "name": {
                "narrative": [
                    "Federal Ministry of Finance",
                    {"xml:lang": "fr", "#text": "Ministère fédéral des finances"},
                ]
            },
            "acronym": {"narrative": ["BMF", {"xml:lang": "fr", "#text": "BMF"}]},
            "donor-code": "1",
        },
    ),
}


def _mock_fetch(codelist_id: str, *, standard: str = "0") -> bytes:
    return _FIXTURE_BY_ID[codelist_id]


@pytest.mark.unit
def test_parse_codelist_raises_on_unknown_id() -> None:
    from scripts.data_maintenance.refresh_oecd_dac import parse_codelist

    with pytest.raises(ValueError, match="unknown codelist_id"):
        parse_codelist(b"{}", codelist_id="recipients")


@pytest.mark.unit
def test_main_prints_diff_when_yaml_differs(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    import scripts.data_maintenance.refresh_oecd_dac as mod

    stub_yaml = tmp_path / "oecd_dac.yaml"
    stub_yaml.write_text(
        "version: 1\ngenerated_from:\n  oecd_query_date: null\n"
        "  source_url: https://development-finance-codelists.oecd.org/CodesList.aspx\n"
        "  aspx_codelist_ids:\n    recipients: '13'\n    providers: '5'\n    channels: '3'\n"
        "    agencies: '16'\nrecipients: []\nproviders: []\nchannels: []\nagencies: []\n"
    )

    orig_yaml = mod._OECD_DAC_YAML
    mod._OECD_DAC_YAML = stub_yaml
    try:
        with (
            patch.object(mod, "fetch_codelist_json", side_effect=_mock_fetch),
            patch.object(sys, "argv", ["refresh_oecd_dac.py"]),
        ):
            mod.main()
    finally:
        mod._OECD_DAC_YAML = orig_yaml

    captured = capsys.readouterr()
    assert "--- oecd_dac.yaml (current)" in captured.out
    assert "+++ oecd_dac.yaml (proposed)" in captured.out


@pytest.mark.unit
def test_main_no_changes_when_yaml_matches(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    import scripts.data_maintenance.refresh_oecd_dac as mod

    stub_yaml = tmp_path / "oecd_dac.yaml"
    stub_yaml.write_text("")  # empty so first run shows a diff

    orig_yaml = mod._OECD_DAC_YAML
    mod._OECD_DAC_YAML = stub_yaml

    try:
        # Run main once to get what the script would generate
        with (
            patch.object(mod, "fetch_codelist_json", side_effect=_mock_fetch),
            patch.object(sys, "argv", ["refresh_oecd_dac.py"]),
        ):
            mod.main()

        captured_first = capsys.readouterr()
        # Extract proposed content from the diff — lines starting with '+' (not '+++')
        proposed_lines = [
            line[1:]
            for line in captured_first.out.splitlines(keepends=True)
            if line.startswith("+") and not line.startswith("+++")
        ]
        proposed_text = "".join(proposed_lines)
        stub_yaml.write_text(proposed_text)

        # Now run again — should detect no changes
        with (
            patch.object(mod, "fetch_codelist_json", side_effect=_mock_fetch),
            patch.object(sys, "argv", ["refresh_oecd_dac.py"]),
        ):
            mod.main()
    finally:
        mod._OECD_DAC_YAML = orig_yaml

    captured_second = capsys.readouterr()
    assert captured_second.out == "", "Expected no diff output"
    assert "No changes detected." in captured_second.err
