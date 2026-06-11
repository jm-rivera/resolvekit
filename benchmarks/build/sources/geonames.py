"""GeoNames builder — country aliases from the alternateNames dump."""

from __future__ import annotations

import csv
import logging
import zipfile
from io import TextIOWrapper
from pathlib import Path
from typing import TYPE_CHECKING

from benchmarks.build.sources._geo_common import _download
from benchmarks.core.kernel import Query
from resolvekit.calibration.adapters.geonames import (
    _SKIP_ISOLANGUAGES,
    COUNTRY_INFO_URL,
    GEONAMES_URL,
)

if TYPE_CHECKING:
    from resolvekit.core.store import EntityStore

logger = logging.getLogger(__name__)

DEFAULT_LANGUAGES: tuple[str, ...] = ("en", "es", "fr", "de")


def build(
    *,
    store: EntityStore,
    limit: int | None = None,
    seed: int = 42,
    languages: list[str] | None = None,
    cache_dir: Path | None = None,
) -> list[Query]:
    del seed
    langs = (
        frozenset(languages) if languages is not None else frozenset(DEFAULT_LANGUAGES)
    )

    try:
        zip_path = _download(url=GEONAMES_URL, cache_dir=cache_dir)
    except Exception as exc:
        logger.warning("GeoNames alternateNames download failed: %s", exc)
        return []

    geoname_to_iso2 = _load_country_info(cache_dir=cache_dir)
    if not geoname_to_iso2:
        logger.warning("GeoNames countryInfo unavailable; skipping")
        return []

    canonical_names = _canonical_names(store=store, iso2s=set(geoname_to_iso2.values()))

    rows: list[Query] = []
    try:
        with (
            zipfile.ZipFile(zip_path) as zf,
            zf.open("alternateNames.txt") as raw,
        ):
            text_stream = TextIOWrapper(raw, encoding="utf-8", errors="replace")
            reader = csv.reader(text_stream, delimiter="\t")
            for row in reader:
                built = _parse_row(
                    row=row,
                    store=store,
                    geoname_to_iso2=geoname_to_iso2,
                    canonical_names=canonical_names,
                    languages=langs,
                )
                if built is None:
                    continue
                rows.append(built)
                if limit is not None and len(rows) >= limit:
                    return rows
    except Exception as exc:
        logger.warning("GeoNames: error processing zip: %s", exc)

    return rows


def _parse_row(
    *,
    row: list[str],
    store: EntityStore,
    geoname_to_iso2: dict[str, str],
    canonical_names: dict[str, str],
    languages: frozenset[str],
) -> Query | None:
    if len(row) < 5:
        return None

    isolanguage = row[2].strip()
    if isolanguage in _SKIP_ISOLANGUAGES:
        return None
    if isolanguage not in languages:
        return None

    geoname_id = row[1].strip()
    alternate_name = row[3].strip()
    if not alternate_name or not geoname_id:
        return None

    iso2 = geoname_to_iso2.get(geoname_id)
    if not iso2:
        return None
    entity_ids = store.lookup_code("iso2", iso2)
    if not entity_ids:
        return None
    dcid = entity_ids[0]

    is_short = len(row) > 5 and row[5].strip() == "1"
    canonical = canonical_names.get(dcid, "")
    capabilities: tuple[str, ...]
    if alternate_name == canonical or (
        is_short and alternate_name.lower() == canonical.lower()
    ):
        category = "canonical"
        difficulty = "easy"
        capabilities = ("multilingual",) if isolanguage != "en" else ()
    elif alternate_name.isupper() and alternate_name.lower() != alternate_name:
        category = "case_noise"
        difficulty = "medium"
        capabilities = ("case_noise", "alias")
    else:
        category = "alias"
        difficulty = "medium"
        capabilities = ("multilingual", "alias") if isolanguage != "en" else ("alias",)

    return Query(
        query_id="",
        text=alternate_name,
        expected_ids=(dcid,),
        language=isolanguage,
        entity_type="country",
        category=category,
        difficulty=difficulty,
        capabilities=capabilities,
        source="geonames",
        notes=None,
    )


def _canonical_names(
    *,
    store: EntityStore,
    iso2s: set[str],
) -> dict[str, str]:
    names: dict[str, str] = {}
    for iso2 in iso2s:
        entity_ids = store.lookup_code("iso2", iso2)
        if not entity_ids:
            continue
        entity = store.get_entity(entity_ids[0])
        if entity is not None:
            names[entity_ids[0]] = entity.canonical_name
    return names


def _load_country_info(*, cache_dir: Path | None) -> dict[str, str]:
    try:
        path = _download(url=COUNTRY_INFO_URL, cache_dir=cache_dir)
    except Exception as exc:
        logger.warning("GeoNames countryInfo download failed: %s", exc)
        return {}

    mapping: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                cols = line.split("\t")
                if len(cols) > 16:
                    iso2 = cols[0].strip().lower()
                    geoname_id = cols[16].strip()
                    if iso2 and geoname_id:
                        mapping[geoname_id] = iso2
    except Exception as exc:
        logger.warning("GeoNames: error parsing countryInfo.txt: %s", exc)
    return mapping
