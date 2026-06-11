"""Characterization tests for benchmarks.build.wikidata.build().

Pin current observable behavior. Network is mocked at
resolvekit.calibration.adapters._wikidata_client.urllib.request.urlopen.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from benchmarks.build.sources.wikidata import build

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


def _sparql_response(bindings: list[dict]) -> MagicMock:
    """Return a mock urlopen context-manager that yields a SPARQL JSON body."""
    body = json.dumps({"results": {"bindings": bindings}}).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _q30_binding() -> dict:
    return {
        "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q30"},
        "itemLabel": {"type": "literal", "value": "United States of America"},
        "altLabel": {"type": "literal", "value": "America"},
    }


def _q142_binding() -> dict:
    return {
        "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q142"},
        "itemLabel": {"type": "literal", "value": "France"},
    }


# Store that maps Q30 and Q142 to dcids
_BASE_STORE = {
    ("wikidata", "q30"): ["country/USA"],
    ("wikidata", "q142"): ["country/FRA"],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_build_emits_canonical_and_alias_rows() -> None:
    """build() returns rows for Q30 label, Q30 altLabel, Q142 label."""
    bindings = [_q30_binding(), _q142_binding()]
    store = _make_mock_store(_BASE_STORE)
    resp = _sparql_response(bindings)

    with (
        patch(
            "resolvekit.calibration.adapters._wikidata_client.urllib.request.urlopen",
            return_value=resp,
        ),
        patch("benchmarks.build.sources.wikidata.time.sleep"),
    ):
        rows = build(store=store, languages=["en"])

    queries = {r.text for r in rows}
    assert "United States of America" in queries
    assert "America" in queries
    assert "France" in queries

    for r in rows:
        assert r.source == "wikidata"
        assert r.entity_type == "country"
        assert r.query_id == ""
        assert len(r.expected_ids) == 1

    usa_row = next(r for r in rows if r.text == "United States of America")
    assert usa_row.expected_ids == ("country/USA",)

    fra_row = next(r for r in rows if r.text == "France")
    assert fra_row.expected_ids == ("country/FRA",)


def test_build_capabilities_for_en() -> None:
    """For languages=['en']: canonical → capabilities==(); alias → ('alias',)."""
    bindings = [_q30_binding()]
    store = _make_mock_store(_BASE_STORE)
    resp = _sparql_response(bindings)

    with (
        patch(
            "resolvekit.calibration.adapters._wikidata_client.urllib.request.urlopen",
            return_value=resp,
        ),
        patch("benchmarks.build.sources.wikidata.time.sleep"),
    ):
        rows = build(store=store, languages=["en"])

    canonical = next(r for r in rows if r.text == "United States of America")
    alias = next(r for r in rows if r.text == "America")

    assert canonical.category == "canonical"
    assert canonical.capabilities == ()

    assert alias.category == "alias"
    assert alias.capabilities == ("alias",)


def test_build_capabilities_for_non_en() -> None:
    """For languages=['es']: canonical → ('multilingual',); alias → ('multilingual','alias')."""
    binding = {
        "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q30"},
        "itemLabel": {"type": "literal", "value": "Estados Unidos"},
        "altLabel": {"type": "literal", "value": "EE.UU."},
    }
    store = _make_mock_store(_BASE_STORE)
    resp = _sparql_response([binding])

    with (
        patch(
            "resolvekit.calibration.adapters._wikidata_client.urllib.request.urlopen",
            return_value=resp,
        ),
        patch("benchmarks.build.sources.wikidata.time.sleep"),
    ):
        rows = build(store=store, languages=["es"])

    canonical = next(r for r in rows if r.text == "Estados Unidos")
    alias = next(r for r in rows if r.text == "EE.UU.")

    assert canonical.category == "canonical"
    assert canonical.capabilities == ("multilingual",)

    assert alias.category == "alias"
    assert alias.capabilities == ("multilingual", "alias")


def test_build_skips_unmapped_qid() -> None:
    """Binding whose QID store.lookup_code returns [] produces no row."""
    binding = {
        "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q999"},
        "itemLabel": {"type": "literal", "value": "Unknown Territory"},
    }
    store = _make_mock_store({})  # nothing mapped
    resp = _sparql_response([binding])

    with (
        patch(
            "resolvekit.calibration.adapters._wikidata_client.urllib.request.urlopen",
            return_value=resp,
        ),
        patch("benchmarks.build.sources.wikidata.time.sleep"),
    ):
        rows = build(store=store, languages=["en"])

    assert rows == []


def test_build_skips_qid_fallback_label() -> None:
    """Canonical label starting with 'Q' is dropped; alias starting with 'Q' is kept.

    Pins the asymmetry at wikidata.py:79: only canonical (is_alias=False) is
    filtered; altLabels that look like QIDs are kept.
    """
    binding = {
        "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q12345"},
        "itemLabel": {"type": "literal", "value": "Q12345"},  # will be dropped
        "altLabel": {"type": "literal", "value": "Q12345-alias"},  # kept
    }
    store = _make_mock_store({("wikidata", "q12345"): ["country/FAKE"]})
    resp = _sparql_response([binding])

    with (
        patch(
            "resolvekit.calibration.adapters._wikidata_client.urllib.request.urlopen",
            return_value=resp,
        ),
        patch("benchmarks.build.sources.wikidata.time.sleep"),
    ):
        rows = build(store=store, languages=["en"])

    queries = {r.text for r in rows}
    assert "Q12345" not in queries  # canonical QID-label dropped
    assert "Q12345-alias" in queries  # alias kept


def test_build_drops_short_code_aliases() -> None:
    """A <=3-char pure-alpha altLabel (ISO-2 / IOC / FIFA code) is not emitted.

    Codes like "USA" are code-lookups, not name queries, so they are filtered
    from the generated alias rows; the canonical name and longer aliases stay.
    """
    binding = {
        "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q30"},
        "itemLabel": {"type": "literal", "value": "United States of America"},
        "altLabel": {"type": "literal", "value": "USA"},  # 3-char code — dropped
    }
    store = _make_mock_store(_BASE_STORE)
    resp = _sparql_response([binding])

    with (
        patch(
            "resolvekit.calibration.adapters._wikidata_client.urllib.request.urlopen",
            return_value=resp,
        ),
        patch("benchmarks.build.sources.wikidata.time.sleep"),
    ):
        rows = build(store=store, languages=["en"])

    queries = {r.text for r in rows}
    assert "United States of America" in queries  # canonical kept
    assert "USA" not in queries  # short code-alias dropped


def test_build_dedupes_on_lang_name_dcid() -> None:
    """Same (lang, name.lower(), dcid) across two entity-types yields one row.

    build() loops over 4 GEO_ENTITY_TYPES x N langs. The same mock response
    is returned for each iteration, so without dedup the same name would appear
    4 times. The seen set collapses this to one.
    """
    binding = _q30_binding()
    store = _make_mock_store(_BASE_STORE)
    resp = _sparql_response([binding])

    with (
        patch(
            "resolvekit.calibration.adapters._wikidata_client.urllib.request.urlopen",
            return_value=resp,
        ),
        patch("benchmarks.build.sources.wikidata.time.sleep"),
    ):
        rows = build(store=store, languages=["en"])

    usa_rows = [r for r in rows if r.text == "United States of America"]
    assert len(usa_rows) == 1  # dedup collapsed 4 iterations to 1

    usa_alias_rows = [r for r in rows if r.text == "America"]
    assert len(usa_alias_rows) == 1


def test_build_respects_limit() -> None:
    """limit=1 with multiple candidate names returns exactly 1 row."""
    bindings = [_q30_binding(), _q142_binding()]
    store = _make_mock_store(_BASE_STORE)
    resp = _sparql_response(bindings)

    with (
        patch(
            "resolvekit.calibration.adapters._wikidata_client.urllib.request.urlopen",
            return_value=resp,
        ),
        patch("benchmarks.build.sources.wikidata.time.sleep"),
    ):
        rows = build(store=store, languages=["en"], limit=1)

    assert len(rows) == 1


def test_build_caches_fetch(tmp_path: Path) -> None:
    """With cache_dir: first build writes cache file; second build reads from it.

    The second call has urlopen patched to raise — proving it never hits the
    network and still returns rows via the cache round-trip (_fetch, wikidata.py:140-160).
    """
    bindings = [_q30_binding()]
    store = _make_mock_store(_BASE_STORE)
    resp = _sparql_response(bindings)

    # First call — should write cache
    with (
        patch(
            "resolvekit.calibration.adapters._wikidata_client.urllib.request.urlopen",
            return_value=resp,
        ),
        patch("benchmarks.build.sources.wikidata.time.sleep"),
    ):
        rows_first = build(store=store, languages=["en"], cache_dir=tmp_path)

    assert len(rows_first) > 0

    # Exactly one entity type x one lang — one cache file per (entity_type, lang) pair.
    # build() uses all 4 GEO_ENTITY_TYPES; verify at least one cache file exists.
    cache_files = list(tmp_path.glob("wikidata_wikidata_geo_*.json"))
    assert len(cache_files) > 0

    # Second call — urlopen raises; must still return rows from cache
    with (
        patch(
            "resolvekit.calibration.adapters._wikidata_client.urllib.request.urlopen",
            side_effect=OSError("no network"),
        ),
        patch("benchmarks.build.sources.wikidata.time.sleep"),
    ):
        rows_second = build(store=store, languages=["en"], cache_dir=tmp_path)

    assert len(rows_second) > 0
    assert {r.text for r in rows_second} == {r.text for r in rows_first}


def test_build_returns_empty_on_query_failure() -> None:
    """urlopen raises for all calls, no cache_dir → build returns [].

    Pins _sparql_query except → [] path (wikidata.py:173-177).
    """
    store = _make_mock_store(_BASE_STORE)

    with (
        patch(
            "resolvekit.calibration.adapters._wikidata_client.urllib.request.urlopen",
            side_effect=OSError("no network"),
        ),
        patch("benchmarks.build.sources.wikidata.time.sleep"),
    ):
        rows = build(store=store, languages=["en"])

    assert rows == []
