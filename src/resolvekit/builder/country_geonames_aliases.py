"""GeoNames alternateNames enricher for geo.country entities.

Injects country name aliases from the GeoNames alternateNames dump
(https://download.geonames.org/export/dump/alternateNames.zip,
Creative Commons Attribution 4.0 International License) into the
staging entity graph.

GeoNames alternate names cover four categories:
- Canonical preferred names per language (``isPreferredName=1``)
- Short-form names (``isShortName=1``)
- Historical names (``isHistoric=1``) — former state names, colonial names
- Colloquial names (``isColloquial=1``) — common-use aliases

This enricher focuses on languages already covered by the CLDR enricher
(en, de, es, fr) and fills the gap between the Data Commons baseline
and what the benchmark alias capability expects. Historical and colloquial
names are the primary target; canonical alternates that CLDR already
covers are naturally deduped via INSERT OR IGNORE.

The ``countryInfo.txt`` file maps GeoNames country IDs to ISO 3166-1
alpha-2 codes, which resolve against the entity store's ``iso2`` code
system. Only rows whose GeoNames ID appears in ``countryInfo.txt`` are
processed (approximately 252 country-level entries).
"""

from __future__ import annotations

import csv
import logging
import zipfile
from io import TextIOWrapper
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from resolvekit.builder.pipeline.contribution import GraphContribution
from resolvekit.builder.sqlite.context import connect_sqlite
from resolvekit.core.util.normalization import TextNormalizer

logger = logging.getLogger(__name__)

COUNTRY_ENTITY_TYPE = "geo.country"

# Languages to ingest — consistent with the CLDR and multilingual_names enrichers.
_TARGET_LANGUAGES: frozenset[str] = frozenset({"en", "de", "fr", "es"})

# GeoNames isolanguage codes to skip (non-name identifiers).
_SKIP_ISOLANGUAGES: frozenset[str] = frozenset(
    {"link", "post", "iata", "icao", "faac", "wkdt", "unlc", "abbr", "fr_1793"}
)

# Script annotations for non-Latin languages (matches multilingual_names convention).
_LANG_SCRIPT: dict[str, str] = {
    "ru": "Cyrl",
    "zh": "Hans",
    "ar": "Arab",
    "ja": "Jpan",
}


def _download(url: str, known_hash: str | None, cache_dir: Path | None) -> Path:
    """Download and cache a GeoNames file using pooch."""
    import pooch

    kwargs: dict[str, Any] = {"url": url, "known_hash": known_hash}
    if cache_dir is not None:
        kwargs["path"] = cache_dir

    path = pooch.retrieve(**kwargs)
    if isinstance(path, list):
        path = path[0]
    return Path(path)


def _load_geoname_to_iso2(cache_dir: Path | None) -> dict[str, str]:
    """Build geonameId → iso2 mapping from GeoNames countryInfo.txt."""
    from resolvekit.calibration.adapters.geonames import (
        _KNOWN_HASHES,
        COUNTRY_INFO_URL,
    )

    try:
        path = _download(
            COUNTRY_INFO_URL, _KNOWN_HASHES.get(COUNTRY_INFO_URL), cache_dir
        )
    except Exception as exc:
        logger.warning("GeoNames countryInfo.txt download failed: %s", exc)
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


def _build_iso2_to_entity(db_path: Path) -> dict[str, str]:
    """Read iso2 code → entity_id mapping from the staging database."""
    with connect_sqlite(db_path) as conn:
        rows = conn.execute(
            "SELECT c.entity_id, c.value FROM codes c"
            " INNER JOIN entities e ON e.entity_id = c.entity_id"
            " WHERE c.system = 'iso2' AND e.entity_type = ?",
            (COUNTRY_ENTITY_TYPE,),
        ).fetchall()
    return {str(row[1]).lower(): str(row[0]) for row in rows}


def _current_names(db_path: Path) -> dict[tuple[str, str], set[str]]:
    """Return existing (entity_id, lang) → set[normalised name] from the staging DB."""
    from collections import defaultdict

    names: dict[tuple[str, str], set[str]] = defaultdict(set)
    with connect_sqlite(db_path) as conn:
        for row in conn.execute(
            "SELECT entity_id, lang, value_norm FROM names"
            " WHERE entity_id IN (SELECT entity_id FROM entities WHERE entity_type = ?)",
            (COUNTRY_ENTITY_TYPE,),
        ):
            names[(str(row[0]), str(row[1]))].add(str(row[2]))
        for row in conn.execute(
            "SELECT entity_id, canonical_name_norm FROM entities WHERE entity_type = ?",
            (COUNTRY_ENTITY_TYPE,),
        ):
            names[(str(row[0]), "en")].add(str(row[1]))
    return names


def build_geonames_country_aliases_contribution(
    db_path: Path,
    *,
    cache_dir: Path | None = None,
) -> GraphContribution:
    """Compute GeoNames alternate-name alias rows for geo.country entities.

    Downloads (or reuses the pooch cache for) GeoNames alternateNames.zip
    and countryInfo.txt, filters to country-level entries in the target
    languages, and returns a ``GraphContribution`` with the new name rows.

    The caller (pipeline) writes them via ``apply_contribution`` with
    INSERT OR IGNORE, so the operation is idempotent and safe to re-run.

    Args:
        db_path: Path to the staging SQLite database.
        cache_dir: Directory for pooch caches; defaults to the pooch user
            cache when ``None``.
    """
    from resolvekit.calibration.adapters.geonames import (
        _KNOWN_HASHES,
        GEONAMES_URL,
    )

    geoname_to_iso2 = _load_geoname_to_iso2(cache_dir)
    if not geoname_to_iso2:
        logger.warning(
            "GeoNames country aliases: countryInfo unavailable; skipping enricher"
        )
        return GraphContribution()

    iso2_to_entity = _build_iso2_to_entity(db_path)
    if not iso2_to_entity:
        logger.debug("GeoNames country aliases: no country entities in staging DB")
        return GraphContribution()

    country_geoname_ids: set[str] = set(geoname_to_iso2.keys())
    current = _current_names(db_path)
    normalizer = TextNormalizer()

    try:
        zip_path = _download(GEONAMES_URL, _KNOWN_HASHES.get(GEONAMES_URL), cache_dir)
    except Exception as exc:
        logger.warning(
            "GeoNames country aliases: alternateNames.zip download failed: %s", exc
        )
        return GraphContribution()

    name_dicts: list[dict] = []
    seen: set[tuple[str, str, str]] = set()  # (entity_id, value_norm, lang)

    try:
        with (
            zipfile.ZipFile(zip_path) as zf,
            zf.open("alternateNames.txt") as raw,
        ):
            text_stream = TextIOWrapper(raw, encoding="utf-8", errors="replace")
            reader = csv.reader(text_stream, delimiter="\t")
            for row in reader:
                if len(row) < 4:
                    continue

                isolanguage = row[2].strip()
                if not isolanguage:
                    continue
                if isolanguage in _SKIP_ISOLANGUAGES:
                    continue
                if isolanguage not in _TARGET_LANGUAGES:
                    continue

                geoname_id = row[1].strip()
                if geoname_id not in country_geoname_ids:
                    continue

                alt_name = row[3].strip()
                if not alt_name or len(alt_name) < 2:
                    continue

                iso2 = geoname_to_iso2.get(geoname_id)
                if not iso2:
                    continue
                entity_id = iso2_to_entity.get(iso2)
                if not entity_id:
                    continue

                value_norm = normalizer.normalize(alt_name)
                if not value_norm:
                    continue

                key = (entity_id, value_norm, isolanguage)
                if key in seen:
                    continue

                # Skip if already in the staging DB
                existing = current.get((entity_id, isolanguage), set())
                if value_norm in existing:
                    continue

                seen.add(key)
                script = _LANG_SCRIPT.get(isolanguage, "")
                name_dicts.append(
                    {
                        "entity_id": entity_id,
                        "name_kind": "alias",
                        "value": alt_name,
                        "value_norm": value_norm,
                        "lang": isolanguage,
                        "script": script,
                        "is_preferred": 0,
                    }
                )
    except Exception as exc:
        logger.warning("GeoNames country aliases: error processing zip: %s", exc)

    logger.info("GeoNames country aliases: prepared %d new name rows", len(name_dicts))
    return GraphContribution(names=name_dicts)
