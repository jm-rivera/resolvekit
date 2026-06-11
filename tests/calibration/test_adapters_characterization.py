"""Characterization tests for calibration adapters.

Pin current observable behavior at the stable ``urllib.request.urlopen`` seam.
All tests run offline and deterministically.

Mock targets:
  - Wikidata urlopen: ``resolvekit.calibration.adapters._wikidata_client.urllib.request.urlopen``
  - Wikidata sleep:   ``resolvekit.calibration.adapters.wikidata.time.sleep``
  - GeoNames full flow: ``patch("resolvekit.calibration.adapters.geonames._download", ...)``
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from resolvekit.calibration.adapters._wikidata_client import ORG_ENTITY_TYPES
from resolvekit.calibration.adapters.geonames import geonames_generate_geo_pairs
from resolvekit.calibration.adapters.wikidata import (
    wikidata_generate_geo_pairs,
    wikidata_generate_org_pairs,
)
from resolvekit.core.model.entity import EntityRecord
from tests.conftest import MockEntityStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WIKIDATA_URLOPEN = (
    "resolvekit.calibration.adapters._wikidata_client.urllib.request.urlopen"
)
_WIKIDATA_SLEEP = "resolvekit.calibration.adapters.wikidata.time.sleep"


def _make_mock_store(mapping: dict[tuple[str, str], list[str]]) -> MagicMock:
    """Build a mock EntityStore where lookup_code uses ``mapping``."""
    store = MagicMock()

    def lookup_code(system: str, value: str) -> list[str]:
        return mapping.get((system, value), [])

    store.lookup_code.side_effect = lookup_code
    return store


def _sparql_response_cm(bindings: list[dict]) -> MagicMock:
    """Return a context-manager mock whose .read() yields SPARQL JSON bytes."""
    body = json.dumps({"results": {"bindings": bindings}}).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=resp)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


def _build_geonames_zip(tmp_path: Path, tsv_rows: list[list[str]]) -> Path:
    """Write a zip containing alternateNames.txt from ``tsv_rows``."""
    zip_path = tmp_path / "alternateNames.zip"
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter="\t", lineterminator="\n")
    for row in tsv_rows:
        writer.writerow(row)
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("alternateNames.txt", buf.getvalue())
    return zip_path


def _build_country_info(tmp_path: Path, rows: list[tuple[str, str]]) -> Path:
    """Write a minimal countryInfo.txt mapping iso2 → geonameId."""
    # cols[0]=iso2, cols[16]=geonameId; pad the rest with tabs.
    path = tmp_path / "countryInfo.txt"
    lines = ["# comment\n"]
    for iso2, geoname_id in rows:
        cols = [iso2] + [""] * 15 + [geoname_id]
        lines.append("\t".join(cols) + "\n")
    path.write_text("".join(lines))
    return path


def _make_geonames_store(
    entities: dict[str, str],
    codes: dict[tuple[str, str], list[str]],
) -> MockEntityStore:
    """Build a MockEntityStore for GeoNames full-flow tests."""
    records: dict[str, EntityRecord] = {}
    for eid, cname in entities.items():
        records[eid] = EntityRecord(
            entity_id=eid,
            entity_type="geo.country",
            canonical_name=cname,
            canonical_name_norm=cname.lower(),
            names=[],
        )
    return MockEntityStore(entities=records, codes=codes)


# ---------------------------------------------------------------------------
# test_wikidata_org_adapter_generate_pairs
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_wikidata_org_adapter_generate_pairs() -> None:
    """wikidata_generate_org_pairs: name, domain, entity types, and output LabeledExamples."""
    # Pin identity fields (ORG_ENTITY_TYPES is the same set the class used)
    assert (
        ORG_ENTITY_TYPES
    )  # non-empty; specific values pinned by _wikidata_client unit tests

    bindings = [
        {
            "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q7164"},
            "itemLabel": {"type": "literal", "value": "United Nations"},
        },
    ]
    store = _make_mock_store({("wikidata", "q7164"): ["org/UN"]})

    with (
        patch(_WIKIDATA_SLEEP),
        patch(_WIKIDATA_URLOPEN, return_value=_sparql_response_cm(bindings)),
    ):
        examples = wikidata_generate_org_pairs(store=store, languages=["en"])

    assert len(examples) >= 1
    ex = next(e for e in examples if e.query_text == "United Nations")
    assert ex.expected_entity_id == "org/UN"
    assert ex.source_adapter == "wikidata_org"
    assert ex.domain == "org"


# ---------------------------------------------------------------------------
# test_wikidata_geo_fetch_caches
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_wikidata_geo_fetch_caches(tmp_path: Path) -> None:
    """wikidata_generate_geo_pairs: first call writes cache; second hits cache."""
    bindings = [
        {
            "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q30"},
            "itemLabel": {"type": "literal", "value": "United States of America"},
        },
    ]
    store = _make_mock_store({("wikidata", "q30"): ["country/USA"]})

    # First call — network allowed.
    with (
        patch(_WIKIDATA_SLEEP),
        patch(_WIKIDATA_URLOPEN, return_value=_sparql_response_cm(bindings)),
    ):
        examples_first = wikidata_generate_geo_pairs(
            store=store, languages=["en"], cache_dir=tmp_path
        )

    # Cache files should exist (one per entity_type per lang).
    cache_files = list(tmp_path.glob("wikidata_wikidata_geo_*.json"))
    assert len(cache_files) > 0

    # Second call — network raises; must still return results from cache.
    with (
        patch(_WIKIDATA_SLEEP),
        patch(_WIKIDATA_URLOPEN, side_effect=OSError("network disabled")),
    ):
        examples_second = wikidata_generate_geo_pairs(
            store=store, languages=["en"], cache_dir=tmp_path
        )

    texts_first = {e.query_text for e in examples_first}
    texts_second = {e.query_text for e in examples_second}
    assert "United States of America" in texts_first
    assert texts_first == texts_second  # cache round-trip is lossless


# ---------------------------------------------------------------------------
# test_wikidata_label_qid_fallback_skipped
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_wikidata_label_qid_fallback_skipped() -> None:
    """Canonical label starting 'Q' is dropped; altLabel starting 'Q' is kept."""
    bindings = [
        {
            # itemLabel is a QID fallback — should be dropped
            "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q999"},
            "itemLabel": {"type": "literal", "value": "Q999"},
            "altLabel": {"type": "literal", "value": "Q999-alias"},
        },
    ]
    store = _make_mock_store({("wikidata", "q999"): ["country/X99"]})

    with (
        patch(_WIKIDATA_SLEEP),
        patch(_WIKIDATA_URLOPEN, return_value=_sparql_response_cm(bindings)),
    ):
        examples = wikidata_generate_geo_pairs(store=store, languages=["en"])

    query_texts = {e.query_text for e in examples}
    # itemLabel "Q999" must be absent (drops QID-fallback labels)
    assert "Q999" not in query_texts
    # altLabel "Q999-alias" must be present (only canonical is filtered)
    assert "Q999-alias" in query_texts


# ---------------------------------------------------------------------------
# test_geonames_adapter_full_flow
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_geonames_adapter_full_flow(tmp_path: Path) -> None:
    """geonames_generate_geo_pairs: full zip path, isolanguage skip, iso2 bridge."""
    # TSV rows: alternateNameId, geonameId, isolanguage, alternateName, ...
    tsv_rows = [
        ["1", "2635167", "en", "United Kingdom", "1", "", "", "", "", ""],
        ["2", "2635167", "en", "Britain", "", "", "", "", "", ""],
        [
            "3",
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
        ["4", "2635167", "iata", "LHR", "", "", "", "", "", ""],
    ]
    zip_path = _build_geonames_zip(tmp_path, tsv_rows)
    country_info_path = _build_country_info(tmp_path, [("gb", "2635167")])

    store = _make_geonames_store(
        entities={"country/GBR": "United Kingdom"},
        codes={("iso2", "gb"): ["country/GBR"]},
    )

    def _fake_download(url: str, cache_dir: Path | None) -> Path:
        from resolvekit.calibration.adapters.geonames import (
            COUNTRY_INFO_URL,
            GEONAMES_URL,
        )

        if url == GEONAMES_URL:
            return zip_path
        if url == COUNTRY_INFO_URL:
            return country_info_path
        raise ValueError(f"unexpected url: {url}")

    with patch(
        "resolvekit.calibration.adapters.geonames._download", side_effect=_fake_download
    ):
        examples = geonames_generate_geo_pairs(store=store, languages=["en"])

    query_texts = {e.query_text for e in examples}
    # English names should be present
    assert "United Kingdom" in query_texts
    assert "Britain" in query_texts
    # isolanguage rows must be excluded
    assert "https://en.wikipedia.org/wiki/UK" not in query_texts
    assert "LHR" not in query_texts

    for ex in examples:
        assert ex.source_adapter == "geonames"
        assert ex.domain == "geo"
        assert ex.expected_entity_id == "country/GBR"


# ---------------------------------------------------------------------------
# test_geonames_direct_geonames_code_lookup
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_geonames_direct_geonames_code_lookup(tmp_path: Path) -> None:
    """geonames_generate_geo_pairs resolves via direct geonames code when store has it.

    The calibration adapter tries store.lookup_code("geonames", geoname_id)
    before falling back to the iso2 bridge.  The benchmark builder lacks this
    direct-lookup path — pinning this divergence so the refactor preserves it.
    """
    # One TSV row: geoname_id "9999999" maps directly in the store (no iso2 needed).
    tsv_rows = [
        ["1", "9999999", "en", "Testlandia", "1", "", "", "", "", ""],
    ]
    zip_path = _build_geonames_zip(tmp_path, tsv_rows)
    # countryInfo has no entry for 9999999 → iso2 bridge would fail if tried
    country_info_path = _build_country_info(tmp_path, [])

    # Store maps geonames code directly (not via iso2)
    store = _make_geonames_store(
        entities={"country/TST": "Testlandia"},
        codes={("geonames", "9999999"): ["country/TST"]},
    )

    def _fake_download(url: str, cache_dir: Path | None) -> Path:
        from resolvekit.calibration.adapters.geonames import (
            COUNTRY_INFO_URL,
            GEONAMES_URL,
        )

        if url == GEONAMES_URL:
            return zip_path
        if url == COUNTRY_INFO_URL:
            return country_info_path
        raise ValueError(f"unexpected url: {url}")

    with patch(
        "resolvekit.calibration.adapters.geonames._download", side_effect=_fake_download
    ):
        examples = geonames_generate_geo_pairs(store=store, languages=["en"])

    assert len(examples) == 1
    ex = examples[0]
    assert ex.query_text == "Testlandia"
    assert ex.expected_entity_id == "country/TST"
    assert ex.source_adapter == "geonames"
    assert ex.domain == "geo"
