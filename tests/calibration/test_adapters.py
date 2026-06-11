"""Tests for calibration adapters."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from resolvekit.calibration.adapters.cldr import cldr_generate_geo_pairs
from resolvekit.calibration.adapters.geonames import (
    _parse_row,
)
from resolvekit.calibration.adapters.multilingual_names import (
    EXTENDED_LANGUAGES,
    UN_OFFICIAL_LANGUAGES,
    generate_name_rows,
    multilingual_generate_geo_pairs,
)

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


# ---------------------------------------------------------------------------
# test_cldr_generate_geo_pairs
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cldr_adapter_generate_pairs_mock(tmp_path: Path) -> None:
    """Mock CLDR JSON files in a zip and verify output format + ISO mapping."""
    # Build a fake CLDR zip
    zip_path = tmp_path / "cldr-46.0.0.zip"
    territories_data = {
        "main": {
            "en": {
                "localeDisplayNames": {
                    "territories": {
                        "US": "United States",
                        "FR": "France",
                        "001": "World",  # numeric — should be skipped
                        "US-alt-short": "US",  # alt variant — should be skipped
                    }
                }
            }
        }
    }
    inner_path = (
        "cldr-json-46.0.0/cldr-json/cldr-localenames-full/main/en/territories.json"
    )
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(inner_path, json.dumps(territories_data))

    # Store: "us" → ["country/USA"], "fr" → ["country/FRA"]
    store = _make_mock_store(
        {
            ("iso2", "us"): ["country/USA"],
            ("iso2", "fr"): ["country/FRA"],
        }
    )

    # Patch module-level _download to return our fake zip
    with patch("resolvekit.calibration.adapters.cldr._download", return_value=zip_path):
        examples = cldr_generate_geo_pairs(store=store, languages=["en"])

    query_texts = {e.query_text for e in examples}
    entity_ids = {e.expected_entity_id for e in examples}

    assert "United States" in query_texts
    assert "France" in query_texts
    # Numeric codes and alt variants should be absent
    assert "World" not in query_texts
    assert "US" not in query_texts

    assert "country/USA" in entity_ids
    assert "country/FRA" in entity_ids

    for ex in examples:
        assert ex.source_adapter == "cldr"
        assert ex.domain == "geo"
        assert ex.raw_score is None
        assert ex.label is None


# ---------------------------------------------------------------------------
# test_geonames_parse_row (module-level function)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_geonames_adapter_parse_line() -> None:
    """Unit test for GeoNames TSV row parsing via module-level _parse_row."""
    store = _make_mock_store({("iso2", "gb"): ["country/GBR"]})
    geonameid_to_iso2 = {"2635167": "gb"}
    languages: frozenset[str] = frozenset(["en", "zh"])

    # Valid English name row — bridges via geonameId → iso2 → entity
    row = ["1234", "2635167", "en", "United Kingdom", "1", "", "", "", "", ""]
    result = _parse_row(row, store, geonameid_to_iso2, languages)
    assert result is not None
    assert result.query_text == "United Kingdom"
    assert result.expected_entity_id == "country/GBR"
    assert result.source_adapter == "geonames"
    assert result.domain == "geo"

    # Skip 'link' isolanguage
    row_link = [
        "5678",
        "2635167",
        "link",
        "https://en.wikipedia.org/wiki/UK",
        "",
        "",
        "",
        "",
        "",
        "",
    ]
    assert _parse_row(row_link, store, geonameid_to_iso2, languages) is None

    # Skip 'iata' isolanguage
    row_iata = ["9012", "2635167", "iata", "LHR", "", "", "", "", "", ""]
    assert _parse_row(row_iata, store, geonameid_to_iso2, languages) is None

    # Unknown geonameId not in mapping — returns None
    row_unknown = ["9999", "9999999", "en", "Atlantis", "", "", "", "", "", ""]
    assert _parse_row(row_unknown, store, geonameid_to_iso2, languages) is None

    # Chinese is in our explicit language set so it's accepted
    row_zh = ["4444", "2635167", "zh", "英国", "", "", "", "", "", ""]
    assert _parse_row(row_zh, store, geonameid_to_iso2, languages) is not None

    # Hindi is not in our language set — filtered out
    row_hi = ["6666", "2635167", "hi", "यूनाइटेड किंगडम", "", "", "", "", "", ""]
    assert _parse_row(row_hi, store, geonameid_to_iso2, languages) is None

    # languages=None means accept all
    row_ja = ["5555", "2635167", "ja", "イギリス", "", "", "", "", "", ""]
    assert _parse_row(row_ja, store, geonameid_to_iso2, None) is not None


# ---------------------------------------------------------------------------
# test_adapter_skips_unmapped_entities
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_adapter_skips_unmapped_entities(tmp_path: Path) -> None:
    """cldr_generate_geo_pairs skips entries where store.lookup_code returns []."""
    store = _make_mock_store({})

    zip_path = tmp_path / "cldr-46.0.0.zip"
    territories_data = {
        "main": {
            "en": {
                "localeDisplayNames": {
                    "territories": {
                        "XX": "Unknown Land",
                    }
                }
            }
        }
    }
    inner_path = (
        "cldr-json-46.0.0/cldr-json/cldr-localenames-full/main/en/territories.json"
    )
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(inner_path, json.dumps(territories_data))

    with patch("resolvekit.calibration.adapters.cldr._download", return_value=zip_path):
        examples = cldr_generate_geo_pairs(store=store, languages=["en"])

    assert examples == []


# ---------------------------------------------------------------------------
# test_multilingual_names
# ---------------------------------------------------------------------------


def _build_multilingual_zip(zip_path: Path) -> None:
    """Materialize a multi-language CLDR zip for testing."""
    territories_by_lang = {
        "de": {
            "DE": "Deutschland",
            "US": "Vereinigte Staaten",
            "US-alt-short": "USA",
            "GB": "Vereinigtes Königreich",
            "GB-alt-short": "UK",
            "GB-alt-variant": "UK (variant — should be skipped)",
            "001": "Welt",  # numeric — should be skipped
            "ZZ": "Unbekannte Region",  # unmappable — store returns []
        },
        "ar": {
            "DE": "ألمانيا",
            "US": "الولايات المتحدة",
        },
        "zh": {
            "DE": "德国",
            "US": "美国",
        },
    }
    with zipfile.ZipFile(zip_path, "w") as zf:
        for lang, territories in territories_by_lang.items():
            inner = (
                f"cldr-json-46.0.0/cldr-json/cldr-localenames-full/"
                f"main/{lang}/territories.json"
            )
            payload = {
                "main": {
                    lang: {"localeDisplayNames": {"territories": territories}},
                },
            }
            zf.writestr(inner, json.dumps(payload))


@pytest.mark.integration
def test_multilingual_names_generate_rows_with_alt_short(tmp_path: Path) -> None:
    """generate_name_rows emits ingestion-ready rows for de/ar/zh including short variants."""
    zip_path = tmp_path / "cldr-46.0.0.zip"
    _build_multilingual_zip(zip_path)

    store = _make_mock_store(
        {
            ("iso2", "de"): ["country/DEU"],
            ("iso2", "us"): ["country/USA"],
            ("iso2", "gb"): ["country/GBR"],
        }
    )

    with patch(
        "resolvekit.calibration.adapters.multilingual_names._download_cldr",
        return_value=zip_path,
    ):
        rows = generate_name_rows(store=store, languages=["de", "ar", "zh"])

    by_lang: dict[str, list[dict]] = {}
    for r in rows:
        by_lang.setdefault(r["lang"], []).append(r)

    de_values = {r["value"] for r in by_lang["de"]}
    assert "Deutschland" in de_values
    assert "Vereinigte Staaten" in de_values
    assert "USA" in de_values
    assert "UK" in de_values
    assert "Welt" not in de_values
    assert "Unbekannte Region" not in de_values
    assert all("variant — should be skipped" not in v for v in de_values)

    ar_values = {r["value"] for r in by_lang["ar"]}
    assert "ألمانيا" in ar_values
    assert "الولايات المتحدة" in ar_values

    zh_values = {r["value"] for r in by_lang["zh"]}
    assert "德国" in zh_values

    # Schema sanity: required SQLite columns are populated.
    for r in rows:
        assert r["name_kind"] == "alias"
        assert r["is_preferred"] == 0
        assert r["entity_id"].startswith("country/")
        assert r["lang"] in {"de", "ar", "zh"}
        assert r["value_norm"]  # never empty
        if r["lang"] == "ar":
            assert r["script"] == "Arab"
        elif r["lang"] == "zh":
            assert r["script"] == "Hans"
        else:
            assert r["script"] == ""


@pytest.mark.integration
def test_multilingual_names_short_variants_disabled(tmp_path: Path) -> None:
    """include_short_variants=False suppresses ``-alt-short`` entries."""
    zip_path = tmp_path / "cldr-46.0.0.zip"
    _build_multilingual_zip(zip_path)

    store = _make_mock_store(
        {
            ("iso2", "de"): ["country/DEU"],
            ("iso2", "us"): ["country/USA"],
            ("iso2", "gb"): ["country/GBR"],
        }
    )

    with patch(
        "resolvekit.calibration.adapters.multilingual_names._download_cldr",
        return_value=zip_path,
    ):
        rows = generate_name_rows(
            store=store,
            languages=["de"],
            include_short_variants=False,
        )

    values = {r["value"] for r in rows}
    assert "Vereinigte Staaten" in values
    assert "USA" not in values
    assert "UK" not in values


@pytest.mark.integration
def test_multilingual_names_iso3_fallback(tmp_path: Path) -> None:
    """Entities missing iso2 (Kosovo, South Sudan) are reachable via iso3 fallback."""
    zip_path = tmp_path / "cldr-46.0.0.zip"
    territories = {
        "main": {
            "de": {
                "localeDisplayNames": {
                    "territories": {
                        "XK": "Kosovo",
                        "SS": "Südsudan",
                    }
                }
            }
        }
    }
    inner = "cldr-json-46.0.0/cldr-json/cldr-localenames-full/main/de/territories.json"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(inner, json.dumps(territories))

    # Store has these only by iso3, not iso2 (matches our real data).
    store = _make_mock_store(
        {
            ("iso3", "xkx"): ["country/XKS"],
            ("iso3", "ssd"): ["country/SSD"],
        }
    )

    with patch(
        "resolvekit.calibration.adapters.multilingual_names._download_cldr",
        return_value=zip_path,
    ):
        rows = generate_name_rows(store=store, languages=["de"])

    by_entity = {r["entity_id"]: r for r in rows}
    assert by_entity["country/XKS"]["value"] == "Kosovo"
    assert by_entity["country/SSD"]["value"] == "Südsudan"


@pytest.mark.integration
def test_multilingual_names_adapter_emits_pairs(tmp_path: Path) -> None:
    """multilingual_generate_geo_pairs wraps generate_name_rows as LabeledExamples."""
    zip_path = tmp_path / "cldr-46.0.0.zip"
    _build_multilingual_zip(zip_path)

    store = _make_mock_store(
        {
            ("iso2", "de"): ["country/DEU"],
            ("iso2", "us"): ["country/USA"],
            ("iso2", "gb"): ["country/GBR"],
        }
    )

    with patch(
        "resolvekit.calibration.adapters.multilingual_names._download_cldr",
        return_value=zip_path,
    ):
        examples = multilingual_generate_geo_pairs(store=store, languages=["de"])

    assert examples
    # Every example must point at a country we mocked.
    expected_ids = {"country/DEU", "country/USA", "country/GBR"}
    assert {e.expected_entity_id for e in examples} <= expected_ids

    for ex in examples:
        assert ex.source_adapter == "multilingual_names"
        assert ex.domain == "geo"
        assert ex.raw_score is None
        assert ex.label is None


def test_multilingual_languages_constants_match_un_official() -> None:
    """UN-official set is the documented six languages."""
    assert UN_OFFICIAL_LANGUAGES == ("en", "es", "fr", "ru", "zh", "ar")
    # Extended set adds breadth without duplication.
    assert set(UN_OFFICIAL_LANGUAGES).issubset(set(EXTENDED_LANGUAGES))
    assert "de" in EXTENDED_LANGUAGES
