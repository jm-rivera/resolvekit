"""Characterization tests for benchmarks.build.geonames.build().

Network/pooch is mocked at benchmarks.build.sources.geonames._download via a url-keyed
side_effect; real zipfile/CSV parsing runs against fixture data to characterize
actual parse logic. Uses conftest.MockEntityStore with EntityRecord instances
for entity lookups.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path
from unittest.mock import patch

from benchmarks.build.sources.geonames import COUNTRY_INFO_URL, GEONAMES_URL, build
from resolvekit.core.model import EntityRecord
from tests.conftest import MockEntityStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_geonames_zip(tmp_path: Path, tsv_rows: list[list[str]]) -> Path:
    """Write alternateNames zip containing alternateNames.txt with ``tsv_rows``."""
    zip_path = tmp_path / "alternateNames.zip"
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter="\t", lineterminator="\n")
    writer.writerows(tsv_rows)
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("alternateNames.txt", buf.getvalue())
    return zip_path


def _build_country_info_file(tmp_path: Path, rows: list[tuple[str, str]]) -> Path:
    """Write a minimal countryInfo.txt where each row is (iso2, geoname_id).

    The real file has 19 tab-separated columns; col[0]=iso2, col[16]=geoname_id.
    """
    path = tmp_path / "countryInfo.txt"
    lines = ["# comment line\n"]
    for iso2, geoname_id in rows:
        # Build a 19-column row; only positions 0 and 16 matter.
        cols = [""] * 19
        cols[0] = iso2
        cols[16] = geoname_id
        lines.append("\t".join(cols) + "\n")
    path.write_text("".join(lines), encoding="utf-8")
    return path


def _make_download_side_effect(alt_zip: Path, country_info: Path):
    """Return a side_effect function keyed on the ``url`` keyword argument."""

    def _download(*, url: str, cache_dir: Path | None) -> Path:
        if url == GEONAMES_URL:
            return alt_zip
        if url == COUNTRY_INFO_URL:
            return country_info
        raise ValueError(f"Unexpected URL: {url}")

    return _download


def _make_gbr_store() -> MockEntityStore:
    """MockEntityStore: iso2 'gb' → country/GBR with canonical_name='United Kingdom'."""
    return MockEntityStore(
        entities={
            "country/GBR": EntityRecord(
                entity_id="country/GBR",
                entity_type="geo.country",
                canonical_name="United Kingdom",
                canonical_name_norm="united kingdom",
            ),
        },
        codes={("iso2", "gb"): ["country/GBR"]},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_build_canonical_alias_casenoise(tmp_path: Path) -> None:
    """Three rows for geonameId 2635167 (GBR): canonical, alias, case_noise.

    Pins _parse_row categories and capabilities (geonames.py:109-120).
    """
    # geonameId 2635167 → iso2 'gb'
    # alternateNames TSV: [altNameId, geonameId, isolanguage, alternateName, isPreferredName, ...]
    tsv_rows = [
        [
            "1",
            "2635167",
            "en",
            "United Kingdom",
            "1",
            "",
            "",
            "",
            "",
            "",
        ],  # canonical (isShort or matches)
        ["2", "2635167", "en", "Great Britain", "", "", "", "", "", ""],  # alias
        [
            "3",
            "2635167",
            "en",
            "UK BRITAIN",
            "",
            "",
            "",
            "",
            "",
            "",
        ],  # case_noise (all upper)
    ]
    zip_path = _build_geonames_zip(tmp_path, tsv_rows)
    country_info = _build_country_info_file(tmp_path, [("GB", "2635167")])
    store = _make_gbr_store()

    side_effect = _make_download_side_effect(zip_path, country_info)
    with patch("benchmarks.build.sources.geonames._download", side_effect=side_effect):
        rows = build(store=store, languages=["en"])

    by_query = {r.text: r for r in rows}
    assert set(by_query.keys()) == {"United Kingdom", "Great Britain", "UK BRITAIN"}

    canonical = by_query["United Kingdom"]
    assert canonical.category == "canonical"
    assert canonical.difficulty == "easy"
    assert canonical.capabilities == ()  # en, canonical

    alias = by_query["Great Britain"]
    assert alias.category == "alias"
    assert alias.difficulty == "medium"
    assert alias.capabilities == ("alias",)  # en, alias

    case_noise = by_query["UK BRITAIN"]
    assert case_noise.category == "case_noise"
    assert case_noise.difficulty == "medium"
    assert case_noise.capabilities == ("case_noise", "alias")


def test_build_skips_isolanguages(tmp_path: Path) -> None:
    """Rows with isolanguage in _SKIP_ISOLANGUAGES produce no rows."""
    tsv_rows = [
        [
            "1",
            "2635167",
            "link",
            "https://en.wikipedia.org/wiki/UK",
            "",
            "",
            "",
            "",
            "",
            "",
        ],
        ["2", "2635167", "iata", "LHR", "", "", "", "", "", ""],
    ]
    zip_path = _build_geonames_zip(tmp_path, tsv_rows)
    country_info = _build_country_info_file(tmp_path, [("GB", "2635167")])
    store = _make_gbr_store()

    side_effect = _make_download_side_effect(zip_path, country_info)
    with patch("benchmarks.build.sources.geonames._download", side_effect=side_effect):
        rows = build(store=store, languages=["en"])

    assert rows == []


def test_build_language_filter(tmp_path: Path) -> None:
    """Default languages=('en','es','fr','de'): 'zh' row excluded, 'en' row included.

    Pins the benchmark's 4-lang default (differs from calibration's 10-lang set).
    """
    tsv_rows = [
        ["1", "2635167", "en", "United Kingdom", "1", "", "", "", "", ""],
        ["2", "2635167", "zh", "英国", "", "", "", "", "", ""],
    ]
    zip_path = _build_geonames_zip(tmp_path, tsv_rows)
    country_info = _build_country_info_file(tmp_path, [("GB", "2635167")])
    store = _make_gbr_store()

    side_effect = _make_download_side_effect(zip_path, country_info)
    # Use default languages (not passing languages= → uses DEFAULT_LANGUAGES = ('en','es','fr','de'))
    with patch("benchmarks.build.sources.geonames._download", side_effect=side_effect):
        rows = build(store=store)

    queries = {r.text for r in rows}
    assert "United Kingdom" in queries
    assert "英国" not in queries


def test_build_returns_empty_when_countryinfo_missing(tmp_path: Path) -> None:
    """countryInfo fetch yielding empty mapping → build() returns [].

    Pins geonames.py:43-45: if geoname_to_iso2 is empty, skip with warning.
    """
    tsv_rows = [["1", "2635167", "en", "United Kingdom", "", "", "", "", "", ""]]
    zip_path = _build_geonames_zip(tmp_path, tsv_rows)
    # Write an empty (comment-only) countryInfo file → empty mapping
    country_info = tmp_path / "countryInfo.txt"
    country_info.write_text("# no data\n", encoding="utf-8")
    store = _make_gbr_store()

    side_effect = _make_download_side_effect(zip_path, country_info)
    with patch("benchmarks.build.sources.geonames._download", side_effect=side_effect):
        rows = build(store=store, languages=["en"])

    assert rows == []


def test_build_respects_limit(tmp_path: Path) -> None:
    """limit=1 with multiple rows returns exactly 1 row."""
    tsv_rows = [
        ["1", "2635167", "en", "United Kingdom", "", "", "", "", "", ""],
        ["2", "2635167", "en", "Great Britain", "", "", "", "", "", ""],
    ]
    zip_path = _build_geonames_zip(tmp_path, tsv_rows)
    country_info = _build_country_info_file(tmp_path, [("GB", "2635167")])
    store = _make_gbr_store()

    side_effect = _make_download_side_effect(zip_path, country_info)
    with patch("benchmarks.build.sources.geonames._download", side_effect=side_effect):
        rows = build(store=store, languages=["en"], limit=1)

    assert len(rows) == 1


def test_build_returns_empty_on_download_failure() -> None:
    """alternateNames _download raising → build() logs warning and returns []."""
    store = _make_gbr_store()

    with patch(
        "benchmarks.build.sources.geonames._download",
        side_effect=OSError("network down"),
    ):
        rows = build(store=store, languages=["en"])

    assert rows == []
