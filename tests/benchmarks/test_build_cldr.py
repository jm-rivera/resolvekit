"""Characterization tests for benchmarks.build.cldr.build().

Network/pooch is mocked at benchmarks.build.sources.cldr._download; real zipfile/JSON
parsing runs against fixture zips to characterize the actual parse logic.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from benchmarks.build.sources.cldr import CLDR_VERSION, build

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_store(mapping: dict[tuple[str, str], list[str]]) -> MagicMock:
    """Build a mock EntityStore where lookup_code uses ``mapping``."""
    store = MagicMock()

    def lookup_code(system: str, value: str) -> list[str]:
        return mapping.get((system, value), [])

    store.lookup_code.side_effect = lookup_code
    return store


def _build_cldr_zip(
    tmp_path: Path, territories_by_lang: dict[str, dict[str, str]]
) -> Path:
    """Write a minimal CLDR zip fixture at ``tmp_path/cldr.zip``.

    ``territories_by_lang`` maps lang code → {territory_code: name} dict.
    The inner zip path matches cldr.py:49-51 (version-sensitive).
    """
    zip_path = tmp_path / "cldr.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for lang, territories in territories_by_lang.items():
            inner_path = (
                f"cldr-json-{CLDR_VERSION}/cldr-json/cldr-localenames-full/"
                f"main/{lang}/territories.json"
            )
            data = {
                "main": {
                    lang: {
                        "localeDisplayNames": {
                            "territories": territories,
                        }
                    }
                }
            }
            zf.writestr(inner_path, json.dumps(data))
    return zip_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_build_maps_iso2_to_dcid(tmp_path: Path) -> None:
    """Territories US and FR are mapped to dcids via iso2 lookup."""
    zip_path = _build_cldr_zip(
        tmp_path, {"en": {"US": "United States", "FR": "France"}}
    )
    store = _make_mock_store(
        {
            ("iso2", "us"): ["country/USA"],
            ("iso2", "fr"): ["country/FRA"],
        }
    )

    with patch("benchmarks.build.sources.cldr._download", return_value=zip_path):
        rows = build(store=store, languages=["en"])

    queries = {r.text for r in rows}
    assert "United States" in queries
    assert "France" in queries

    for r in rows:
        assert r.source == "cldr"
        assert r.difficulty == "easy"
        assert r.entity_type == "country"

    usa_row = next(r for r in rows if r.text == "United States")
    assert usa_row.expected_ids == ("country/USA",)

    fra_row = next(r for r in rows if r.text == "France")
    assert fra_row.expected_ids == ("country/FRA",)


def test_build_skips_numeric_and_alt(tmp_path: Path) -> None:
    """Numeric codes (e.g. '001') and alt-variant codes (e.g. 'US-alt-short') produce no rows."""
    zip_path = _build_cldr_zip(tmp_path, {"en": {"001": "World", "US-alt-short": "US"}})
    store = _make_mock_store(
        {
            ("iso2", "001"): ["country/WORLD"],
            ("iso2", "us-alt-short"): ["country/USA"],
        }
    )

    with patch("benchmarks.build.sources.cldr._download", return_value=zip_path):
        rows = build(store=store, languages=["en"])

    assert rows == []


def test_build_skips_unmapped_iso2(tmp_path: Path) -> None:
    """store.lookup_code returns [] for a code → no row emitted."""
    zip_path = _build_cldr_zip(tmp_path, {"en": {"ZZ": "Neverland"}})
    store = _make_mock_store({})  # nothing mapped

    with patch("benchmarks.build.sources.cldr._download", return_value=zip_path):
        rows = build(store=store, languages=["en"])

    assert rows == []


def test_build_multilingual_capability(tmp_path: Path) -> None:
    """lang='de' → capabilities==('multilingual',); lang='en' → ()."""
    zip_path = _build_cldr_zip(
        tmp_path, {"de": {"DE": "Deutschland"}, "en": {"DE": "Germany"}}
    )
    store = _make_mock_store({("iso2", "de"): ["country/DEU"]})

    with patch("benchmarks.build.sources.cldr._download", return_value=zip_path):
        rows_de = build(store=store, languages=["de"])
        rows_en = build(store=store, languages=["en"])

    assert len(rows_de) == 1
    assert rows_de[0].capabilities == ("multilingual",)
    assert rows_de[0].language == "de"

    assert len(rows_en) == 1
    assert rows_en[0].capabilities == ()
    assert rows_en[0].language == "en"


def test_build_dedupes(tmp_path: Path) -> None:
    """Same (lang, name.lower(), dcid) twice → one row."""
    # Two territory codes that map to the same dcid and same name
    zip_path = _build_cldr_zip(
        tmp_path, {"en": {"US": "United States", "USA": "United States"}}
    )
    store = _make_mock_store(
        {
            ("iso2", "us"): ["country/USA"],
            ("iso2", "usa"): ["country/USA"],
        }
    )

    with patch("benchmarks.build.sources.cldr._download", return_value=zip_path):
        rows = build(store=store, languages=["en"])

    assert len(rows) == 1
    assert rows[0].text == "United States"


def test_build_respects_limit(tmp_path: Path) -> None:
    """limit=1 with multiple territory entries returns exactly 1 row."""
    zip_path = _build_cldr_zip(
        tmp_path, {"en": {"US": "United States", "FR": "France"}}
    )
    store = _make_mock_store(
        {
            ("iso2", "us"): ["country/USA"],
            ("iso2", "fr"): ["country/FRA"],
        }
    )

    with patch("benchmarks.build.sources.cldr._download", return_value=zip_path):
        rows = build(store=store, languages=["en"], limit=1)

    assert len(rows) == 1


def test_build_returns_empty_on_download_failure() -> None:
    """_download raising → build() logs a warning and returns []."""
    store = _make_mock_store({})

    with patch(
        "benchmarks.build.sources.cldr._download", side_effect=OSError("network down")
    ):
        rows = build(store=store, languages=["en"])

    assert rows == []
