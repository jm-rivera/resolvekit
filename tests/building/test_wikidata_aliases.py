"""Tests for the Wikidata English alias VALUES fetch and enrichment helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from resolvekit.builder.sources.wikidata.aliases import (
    _cache_path,
    _is_precise_en_alias,
    _qid_to_dcid,
    fetch_wikidata_en_aliases,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_QID_URI_BASE = "http://www.wikidata.org/entity/"


def _make_binding(qid: str, alt_label: str) -> dict[str, Any]:
    return {
        "item": {"type": "uri", "value": f"{_QID_URI_BASE}{qid}"},
        "altLabel": {"type": "literal", "value": alt_label, "xml:lang": "en"},
    }


def _codes_entry(qid: str, dcid: str) -> tuple[str, list[dict[str, Any]]]:
    """Return (dcid, [wikidataId code row]) for use in codes_by_entity."""
    return dcid, [{"code_system": "wikidataId", "code_value": qid, "source": "test"}]


# ---------------------------------------------------------------------------
# Empty-QID-list → {} (no-op, not a failure)
# ---------------------------------------------------------------------------


def test_empty_qid_list_returns_empty_dict() -> None:
    """No wikidataId codes in the chunk → {} without touching the network."""
    with patch(
        "resolvekit.builder.sources.wikidata.aliases.sparql_request",
        side_effect=AssertionError("network called with empty QID list"),
    ):
        result = fetch_wikidata_en_aliases(
            codes_by_entity={},
            cache_dir=None,
        )
    assert result == {}


def test_no_wikidataid_codes_returns_empty_dict() -> None:
    codes_by_entity: dict[str, list[dict[str, Any]]] = {
        "country/FRA": [{"code_system": "iso2", "code_value": "FR", "source": "dc"}],
    }
    with patch(
        "resolvekit.builder.sources.wikidata.aliases.sparql_request",
        side_effect=AssertionError("network called with no wikidataId codes"),
    ):
        result = fetch_wikidata_en_aliases(
            codes_by_entity=codes_by_entity,
            cache_dir=None,
        )
    assert result == {}


# ---------------------------------------------------------------------------
# VALUES-clause construction from QIDs
# ---------------------------------------------------------------------------


def test_values_clause_built_from_qids() -> None:
    """sparql_request receives a VALUES clause containing the chunk's QIDs."""
    codes_by_entity = dict([_codes_entry("Q30", "country/USA")])
    bindings = [_make_binding("Q30", "United States of America")]

    with patch(
        "resolvekit.builder.sources.wikidata.aliases.sparql_request",
        return_value=bindings,
    ) as mock_sparql:
        fetch_wikidata_en_aliases(
            codes_by_entity=codes_by_entity,
            cache_dir=None,
        )

    assert mock_sparql.call_count == 1
    query_arg = mock_sparql.call_args.kwargs["query"]
    assert "wd:Q30" in query_arg
    assert "skos:altLabel" in query_arg
    assert 'FILTER(LANG(?altLabel) = "en")' in query_arg
    # No transitive walk in the VALUES approach
    assert "P279" not in query_arg


def test_values_clause_uses_uppercase_qids() -> None:
    """QIDs stored lower-case in the map are upper-cased in the VALUES clause."""
    codes_by_entity = dict([_codes_entry("q142", "country/FRA")])
    bindings = [_make_binding("Q142", "French Republic")]

    with patch(
        "resolvekit.builder.sources.wikidata.aliases.sparql_request",
        return_value=bindings,
    ) as mock_sparql:
        fetch_wikidata_en_aliases(
            codes_by_entity=codes_by_entity,
            cache_dir=None,
        )

    query_arg = mock_sparql.call_args.kwargs["query"]
    assert "wd:Q142" in query_arg


# ---------------------------------------------------------------------------
# Batching
# ---------------------------------------------------------------------------


def test_batching_splits_large_qid_sets() -> None:
    """QIDs exceeding batch_size are split into multiple sparql_request calls."""
    codes_by_entity = dict(
        [
            _codes_entry("Q1", "country/AA"),
            _codes_entry("Q2", "country/BB"),
            _codes_entry("Q3", "country/CC"),
        ]
    )
    bindings_batch1 = [
        _make_binding("Q1", "Alpha"),
        _make_binding("Q2", "Beta"),
    ]
    bindings_batch2 = [_make_binding("Q3", "Gamma")]

    with (
        patch(
            "resolvekit.builder.sources.wikidata.aliases.sparql_request",
            side_effect=[bindings_batch1, bindings_batch2],
        ) as mock_sparql,
        patch("resolvekit.builder.sources.wikidata.aliases.time.sleep"),
    ):
        result = fetch_wikidata_en_aliases(
            codes_by_entity=codes_by_entity,
            cache_dir=None,
            batch_size=2,
            request_delay=0.1,
        )

    assert mock_sparql.call_count == 2
    assert "country/AA" in result
    assert "country/CC" in result


def test_single_batch_no_sleep() -> None:
    """No inter-batch sleep when all QIDs fit in one batch."""
    codes_by_entity = dict([_codes_entry("Q30", "country/USA")])
    bindings = [_make_binding("Q30", "United States of America")]

    with (
        patch(
            "resolvekit.builder.sources.wikidata.aliases.sparql_request",
            return_value=bindings,
        ),
        patch("resolvekit.builder.sources.wikidata.aliases.time.sleep") as mock_sleep,
    ):
        fetch_wikidata_en_aliases(
            codes_by_entity=codes_by_entity,
            cache_dir=None,
        )

    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# QID→dcid join — wikidataId code rows, non-country dcids excluded
# ---------------------------------------------------------------------------


def test_qid_to_dcid_map_uses_wikidataid_rows() -> None:
    codes_by_entity: dict[str, list[dict[str, Any]]] = {
        "country/FRA": [
            {"code_system": "wikidataId", "code_value": "Q142", "source": "dc"},
            {"code_system": "iso2", "code_value": "FR", "source": "dc"},
        ],
        "geo/region/EU": [
            {"code_system": "wikidataId", "code_value": "Q458", "source": "dc"},
        ],
    }

    result = _qid_to_dcid(codes_by_entity)

    assert result["q142"] == "country/FRA"
    assert result["q458"] == "geo/region/EU"
    # iso2 is ignored
    assert "fr" not in result


def test_non_country_dcids_excluded_from_output() -> None:
    """Bindings whose QID maps to a non-country dcid are dropped."""
    codes_by_entity: dict[str, list[dict[str, Any]]] = {
        "geo/region/EU": [
            {"code_system": "wikidataId", "code_value": "Q458", "source": "dc"},
        ],
    }
    bindings = [_make_binding("Q458", "European Union")]

    with patch(
        "resolvekit.builder.sources.wikidata.aliases.sparql_request",
        return_value=bindings,
    ):
        result = fetch_wikidata_en_aliases(
            codes_by_entity=codes_by_entity,
            cache_dir=None,
        )

    assert result == {}


# ---------------------------------------------------------------------------
# Precision filter
# ---------------------------------------------------------------------------


def test_precision_filter_drops_short_alpha() -> None:
    assert not _is_precise_en_alias("UK", endonyms=set())
    assert not _is_precise_en_alias("US", endonyms=set())
    assert not _is_precise_en_alias("DE", endonyms=set())


def test_precision_filter_drops_dotted_forms() -> None:
    assert not _is_precise_en_alias("S. Korea", endonyms=set())
    assert not _is_precise_en_alias("St.", endonyms=set())
    assert not _is_precise_en_alias("D.R. Congo", endonyms=set())


def test_precision_filter_drops_endonym_casefold_match() -> None:
    endonyms = {"Suomi", "Finlande"}
    assert not _is_precise_en_alias("Suomi", endonyms=endonyms)
    assert not _is_precise_en_alias("suomi", endonyms=endonyms)


def test_precision_filter_keeps_valid_aliases() -> None:
    assert _is_precise_en_alias("Ceylon", endonyms=set())
    assert _is_precise_en_alias("Dutch Guiana", endonyms=set())
    assert _is_precise_en_alias("Irish Republic", endonyms=set())
    assert _is_precise_en_alias("Iran", endonyms=set())


def test_precision_filter_applied_per_entity() -> None:
    """Suomi is Finland's endonym — dropped for FIN, irrelevant for GBR."""
    bindings = [
        _make_binding("Q33", "Suomi"),
        _make_binding("Q145", "United Kingdom"),
    ]
    codes_by_entity = dict(
        [
            _codes_entry("Q33", "country/FIN"),
            _codes_entry("Q145", "country/GBR"),
        ]
    )
    foreign_names: dict[str, set[str]] = {
        "country/FIN": {"Suomi", "Finlande", "Finnland"},
        "country/GBR": {"Vereinigtes Königreich"},
    }

    with patch(
        "resolvekit.builder.sources.wikidata.aliases.sparql_request",
        return_value=bindings,
    ):
        result = fetch_wikidata_en_aliases(
            codes_by_entity=codes_by_entity,
            foreign_names_by_entity=foreign_names,
            cache_dir=None,
        )

    fin_texts = {r["alias_text"] for r in result.get("country/FIN", [])}
    assert "Suomi" not in fin_texts

    gbr_texts = {r["alias_text"] for r in result.get("country/GBR", [])}
    assert "United Kingdom" in gbr_texts


# ---------------------------------------------------------------------------
# Warn-and-continue: empty batch → warning logged, no raise, entity gets no aliases
# ---------------------------------------------------------------------------


def test_empty_batch_logs_warning_and_continues(caplog: pytest.LogCaptureFixture) -> None:
    """Empty single-batch response is logged as warning; treated as "no aliases".

    A single empty batch after internal retries is plausibly "no aliases"; multi-batch
    all-empty responses trigger RuntimeError (likely WDQS outage).
    """
    import logging

    codes_by_entity = dict([_codes_entry("Q30", "country/USA")])

    with (
        patch(
            "resolvekit.builder.sources.wikidata.aliases.sparql_request",
            return_value=[],
        ),
        caplog.at_level(logging.WARNING, logger="resolvekit.builder.sources.wikidata.aliases"),
    ):
        result = fetch_wikidata_en_aliases(
            codes_by_entity=codes_by_entity,
            cache_dir=None,
        )

    # No aliases for the entity — not an error
    assert result == {}
    assert any("no bindings" in r.message for r in caplog.records)


def test_empty_batch_with_cache_dir_logs_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """cache_dir given but no cache file + empty WDQS return → warning, no raise."""
    import logging

    codes_by_entity = dict([_codes_entry("Q142", "country/FRA")])

    with (
        patch(
            "resolvekit.builder.sources.wikidata.aliases.sparql_request",
            return_value=[],
        ),
        caplog.at_level(logging.WARNING, logger="resolvekit.builder.sources.wikidata.aliases"),
    ):
        result = fetch_wikidata_en_aliases(
            codes_by_entity=codes_by_entity,
            cache_dir=tmp_path,
        )

    assert result == {}
    assert any("no bindings" in r.message for r in caplog.records)


def test_all_batches_empty_raises() -> None:
    """All batches returning empty for a multi-batch fetch → RuntimeError.

    A single empty batch is plausibly "no aliases"; every batch in a multi-batch
    chunk returning empty is more consistent with a WDQS outage than with every
    entity being alias-less, so we fail loud.
    """
    # 3 QIDs with batch_size=1 → 3 batches, all returning []
    codes_by_entity = dict(
        [
            _codes_entry("Q1", "country/AA"),
            _codes_entry("Q2", "country/BB"),
            _codes_entry("Q3", "country/CC"),
        ]
    )

    with (
        patch(
            "resolvekit.builder.sources.wikidata.aliases.sparql_request",
            return_value=[],
        ),
        pytest.raises(RuntimeError, match=r"all .* batches returned no bindings"),
    ):
        fetch_wikidata_en_aliases(
            codes_by_entity=codes_by_entity,
            cache_dir=None,
            batch_size=1,
        )


# ---------------------------------------------------------------------------
# Cache: write on first call, read on second without hitting network
# ---------------------------------------------------------------------------


def test_cache_write_then_read(tmp_path: Path) -> None:
    bindings = [_make_binding("Q29", "Kingdom of Spain")]
    codes_by_entity = dict([_codes_entry("Q29", "country/ESP")])
    call_count = 0

    def fake_sparql(**kwargs: Any) -> list[dict[str, Any]]:
        nonlocal call_count
        call_count += 1
        return bindings

    with patch(
        "resolvekit.builder.sources.wikidata.aliases.sparql_request",
        side_effect=fake_sparql,
    ):
        result1 = fetch_wikidata_en_aliases(
            codes_by_entity=codes_by_entity,
            cache_dir=tmp_path,
        )

    assert call_count == 1
    assert "country/ESP" in result1

    # Second call: sparql_request must NOT fire again
    with patch(
        "resolvekit.builder.sources.wikidata.aliases.sparql_request",
        side_effect=AssertionError("network called on second run"),
    ):
        result2 = fetch_wikidata_en_aliases(
            codes_by_entity=codes_by_entity,
            cache_dir=tmp_path,
        )

    esp_texts = {r["alias_text"] for r in result2.get("country/ESP", [])}
    assert "Kingdom of Spain" in esp_texts


def test_cache_file_keyed_on_qid_set(tmp_path: Path) -> None:
    """Different QID sets produce different cache files."""
    path_a = _cache_path(tmp_path, ["q29"])
    path_b = _cache_path(tmp_path, ["q30"])
    assert path_a != path_b


def test_cache_read_on_existing_file(tmp_path: Path) -> None:
    """Existing cache file is read without hitting the network."""
    cached_bindings = [_make_binding("Q142", "French Republic")]
    codes_by_entity = dict([_codes_entry("Q142", "country/FRA")])

    # Pre-write the cache file at the expected path
    cache_file = _cache_path(tmp_path, ["q142"])
    cache_file.write_text(
        json.dumps(cached_bindings, ensure_ascii=True), encoding="utf-8"
    )

    with patch(
        "resolvekit.builder.sources.wikidata.aliases.sparql_request",
        side_effect=AssertionError("network called despite cache"),
    ):
        result = fetch_wikidata_en_aliases(
            codes_by_entity=codes_by_entity,
            cache_dir=tmp_path,
        )

    fra_texts = {r["alias_text"] for r in result.get("country/FRA", [])}
    assert "French Republic" in fra_texts


# ---------------------------------------------------------------------------
# source='wikidata' on all rows
# ---------------------------------------------------------------------------


def test_alias_rows_carry_wikidata_source() -> None:
    bindings = [_make_binding("Q29", "Kingdom of Spain")]
    codes_by_entity = dict([_codes_entry("Q29", "country/ESP")])

    with patch(
        "resolvekit.builder.sources.wikidata.aliases.sparql_request",
        return_value=bindings,
    ):
        result = fetch_wikidata_en_aliases(
            codes_by_entity=codes_by_entity,
            cache_dir=None,
        )

    for row in result.get("country/ESP", []):
        assert row["source"] == "wikidata"
        assert row["language"] == "en"
        assert row["alias_type"] == "alias"
