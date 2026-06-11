"""Tests for Data Commons geo raw fetch assembly."""

from __future__ import annotations

import threading
import time
from typing import Any, cast
from unittest.mock import patch

import pytest

from resolvekit.builder.sources.datacommons.geo.dc_api import GeoDcApi
from resolvekit.builder.sources.datacommons.geo.fetch import fetch_raw_chunk

_WIKIDATA_ALIASES_PATH = (
    "resolvekit.builder.sources.datacommons.geo.fetch.fetch_wikidata_en_aliases"
)


@pytest.fixture(autouse=True)
def _no_wikidata_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block Wikidata network calls in all fetch tests (override per-test as needed)."""
    monkeypatch.setattr(
        _WIKIDATA_ALIASES_PATH,
        lambda **kwargs: {},  # type: ignore[misc]
    )


class _FakeGeoApi:
    def __init__(self) -> None:
        self._active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def _sleep(self) -> None:
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        time.sleep(0.03)
        with self._lock:
            self._active -= 1

    def get_entity_names(
        self,
        entity_ids: list[str],
        *,
        lang: str,
    ) -> dict[str, str]:
        _ = (entity_ids, lang)
        self._sleep()
        return {"country/a": "Country A"}

    def get_entity_types(self, entity_ids: list[str]) -> dict[str, str]:
        _ = entity_ids
        self._sleep()
        return {"country/a": "Country"}

    def get_lat_long(self, entity_ids: list[str]) -> dict[str, dict[str, str]]:
        _ = entity_ids
        self._sleep()
        return {"country/a": {"centroid_lat": "1.0", "centroid_lon": "2.0"}}

    def get_codes(self, entity_ids: list[str]) -> dict[str, list[dict[str, str]]]:
        _ = entity_ids
        self._sleep()
        return {
            "country/a": [
                {
                    "code_system": "iso2",
                    "code_value": "AA",
                    "source": "test",
                }
            ]
        }

    def get_aliases(
        self,
        entity_ids: list[str],
        *,
        languages: list[str],
        canonical_names=None,
    ) -> dict[str, list[dict[str, str]]]:
        _ = (entity_ids, languages, canonical_names)
        self._sleep()
        return {
            "country/a": [
                {
                    "alias_text": "A-land",
                    "language": "en",
                    "alias_type": "canonical",
                    "source": "test",
                }
            ]
        }

    def get_descriptions(self, entity_ids: list[str]) -> dict[str, dict[str, str]]:
        _ = entity_ids
        self._sleep()
        return {"country/a": {"description": "Test description"}}

    def get_parents(self, entity_ids: list[str]) -> dict[str, list[str]]:
        _ = entity_ids
        self._sleep()
        return {"country/a": ["geo/region-1"]}

    def get_source_class_family(self, raw_type: str) -> str:
        return raw_type

    def get_admin_levels(
        self,
        entity_ids: list[str],
        *,
        entity_types=None,
        parents_by_entity=None,
    ) -> dict[str, int]:
        _ = (entity_ids, entity_types, parents_by_entity)
        self._sleep()
        return {}


def test_fetch_raw_chunk_parallelizes_independent_api_calls() -> None:
    api = _FakeGeoApi()

    payload = fetch_raw_chunk(
        entity_ids=["country/a"],
        dc_api=cast(GeoDcApi, api),
        languages=["es"],
    )

    assert payload.entities["country/a"].canonical_name == "Country A"
    assert payload.relations["country/a"][0].target_id == "geo/region-1"
    assert payload.entities["country/a"].attrs_json["raw_entity_type"] == "Country"
    assert payload.entities["country/a"].attrs_json["source_class_family"] == "Country"
    assert payload.entities["country/a"].attrs_json["description"] == "Test description"
    assert api.max_active > 1


def test_fetch_raw_chunk_includes_inferred_admin_level_attrs() -> None:
    class _AdminGeoApi(_FakeGeoApi):
        def get_entity_names(
            self,
            entity_ids: list[str],
            *,
            lang: str,
        ) -> dict[str, str]:
            _ = (entity_ids, lang)
            return {"admin/a1": "Admin A1"}

        def get_entity_types(self, entity_ids: list[str]) -> dict[str, str]:
            if entity_ids == ["admin/a1"]:
                return {"admin/a1": "AdministrativeArea"}
            return {"country/a": "Country"}

        def get_lat_long(self, entity_ids: list[str]) -> dict[str, dict[str, str]]:
            _ = entity_ids
            return {}

        def get_codes(self, entity_ids: list[str]) -> dict[str, list[dict[str, str]]]:
            _ = entity_ids
            return {}

        def get_aliases(
            self,
            entity_ids: list[str],
            *,
            languages: list[str],
            canonical_names=None,
        ) -> dict[str, list[dict[str, str]]]:
            _ = (entity_ids, languages, canonical_names)
            return {}

        def get_descriptions(self, entity_ids: list[str]) -> dict[str, dict[str, str]]:
            _ = entity_ids
            return {}

        def get_parents(self, entity_ids: list[str]) -> dict[str, list[str]]:
            _ = entity_ids
            return {"admin/a1": ["country/a"]}

        def get_source_class_family(self, raw_type: str) -> str:
            return raw_type

        def get_admin_levels(
            self,
            entity_ids: list[str],
            *,
            entity_types=None,
            parents_by_entity=None,
        ) -> dict[str, int]:
            _ = (entity_ids, entity_types, parents_by_entity)
            return {"admin/a1": 1}

    payload = fetch_raw_chunk(
        entity_ids=["admin/a1"],
        dc_api=cast(GeoDcApi, _AdminGeoApi()),
        languages=[],
    )

    assert payload.entities["admin/a1"].attrs_json["admin_level"] == 1


def test_fetch_raw_chunk_wikidata_cache_dir_none_path() -> None:
    """wikidata_cache_dir=None still produces a valid chunk (no network)."""
    api = _FakeGeoApi()

    with patch(
        "resolvekit.builder.sources.datacommons.geo.fetch.fetch_wikidata_en_aliases",
        return_value={},
    ) as mock_wikidata:
        payload = fetch_raw_chunk(
            entity_ids=["country/a"],
            dc_api=cast(GeoDcApi, api),
            languages=["es"],
            wikidata_cache_dir=None,
        )

    mock_wikidata.assert_called_once()
    call_kwargs = mock_wikidata.call_args.kwargs
    assert call_kwargs["cache_dir"] is None
    assert payload.entities["country/a"].canonical_name == "Country A"


def test_fetch_raw_chunk_merges_wikidata_en_aliases() -> None:
    """An en alias row from Wikidata lands in the assembled chunk aliases."""
    api = _FakeGeoApi()
    wikidata_row: dict[str, Any] = {
        "alias_text": "Historic Land A",
        "language": "en",
        "alias_type": "alias",
        "source": "wikidata",
    }

    with patch(
        "resolvekit.builder.sources.datacommons.geo.fetch.fetch_wikidata_en_aliases",
        return_value={"country/a": [wikidata_row]},
    ):
        payload = fetch_raw_chunk(
            entity_ids=["country/a"],
            dc_api=cast(GeoDcApi, api),
            languages=["es"],
            wikidata_cache_dir=None,
        )

    alias_texts = {a.alias_text for a in payload.aliases.get("country/a", [])}
    assert "Historic Land A" in alias_texts
