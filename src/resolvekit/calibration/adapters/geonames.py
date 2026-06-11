"""GeoNames alternateNames adapter."""

from __future__ import annotations

import csv
import logging
import zipfile
from io import TextIOWrapper
from pathlib import Path
from typing import TYPE_CHECKING, Any

from resolvekit.calibration.dataset import LabeledExample

if TYPE_CHECKING:
    from resolvekit.core.store import EntityStore

logger = logging.getLogger(__name__)

GEONAMES_URL = "https://download.geonames.org/export/dump/alternateNames.zip"
COUNTRY_INFO_URL = "https://download.geonames.org/export/dump/countryInfo.txt"

# Snapshot hashes for the GeoNames dumps above.
# These URLs are mutable (no version pin): refresh these constants whenever
# a fresh dump is intentionally pulled and the calibration data is rebuilt.
# Recompute with: shasum -a 256 <cached-file>
_GEONAMES_ALTNAMES_SHA256 = (
    "sha256:1279a9e8c1042947af8df674c2d3267775a51d92d798e8e84851dcda39bbe1c9"
)
_GEONAMES_COUNTRYINFO_SHA256 = (
    "sha256:93bafc525813f22e4711ff9ed6d626343094ce48c26388dc7c49189b3d7d5512"
)

# Non-name isolanguage codes to skip
_SKIP_ISOLANGUAGES = frozenset(["link", "post", "iata", "icao", "faac", "wkdt", "unlc"])


_KNOWN_HASHES: dict[str, str] = {
    GEONAMES_URL: _GEONAMES_ALTNAMES_SHA256,
    COUNTRY_INFO_URL: _GEONAMES_COUNTRYINFO_SHA256,
}


def _download(url: str, cache_dir: Path | None) -> Path:
    """Download and cache a GeoNames file using pooch."""
    import pooch

    kwargs: dict[str, Any] = {
        "url": url,
        "known_hash": _KNOWN_HASHES.get(url),
    }
    if cache_dir is not None:
        kwargs["path"] = cache_dir

    path = pooch.retrieve(**kwargs)
    if isinstance(path, list):
        path = path[0]
    return Path(path)


def _parse_row(
    row: list[str],
    store: EntityStore,
    geonameid_to_iso2: dict[str, str],
    languages: frozenset[str] | None,
) -> LabeledExample | None:
    """Parse a TSV row and return a LabeledExample or None."""

    # Expected columns: alternateNameId, geonameId, isolanguage,
    # alternateName, isPreferredName, isShortName, isColloquial,
    # isHistoric, from, to
    if len(row) < 4:
        return None

    isolanguage = row[2].strip()
    if isolanguage in _SKIP_ISOLANGUAGES:
        return None
    if languages is not None and isolanguage not in languages:
        return None

    geoname_id = row[1].strip()
    alternate_name = row[3].strip()
    if not alternate_name or not geoname_id:
        return None

    # Try direct geonames code lookup first (works when the store
    # has geonames codes, e.g. city/region datapacks).
    entity_ids = store.lookup_code("geonames", geoname_id)

    # Fall back to ISO2 bridge via countryInfo.txt mapping.
    if not entity_ids:
        iso2 = geonameid_to_iso2.get(geoname_id)
        if iso2:
            entity_ids = store.lookup_code("iso2", iso2)

    if not entity_ids:
        return None

    return LabeledExample(
        query_text=alternate_name,
        expected_entity_id=entity_ids[0],
        source_adapter="geonames",
        domain="geo",
    )


def _load_country_info(cache_dir: Path | None) -> dict[str, str]:
    """Download countryInfo.txt and build geonameId → iso2 mapping."""
    try:
        path = _download(COUNTRY_INFO_URL, cache_dir)
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


def geonames_generate_geo_pairs(
    *,
    store: EntityStore,
    languages: list[str] | None = None,
    cache_dir: str | Path | None = None,
    limit: int | None = None,
) -> list[LabeledExample]:
    """Generate (alternate name, DCID) pairs from GeoNames.

    Args:
        store: Entity store providing ``lookup_code('iso2', code)``.
        languages: Language codes to include. Defaults to
            :data:`~resolvekit.calibration.adapters._cldr_source.DEFAULT_LANGUAGES`.
        cache_dir: Pooch cache for GeoNames file downloads.
        limit: Maximum number of examples to return.
    """
    from resolvekit.calibration.adapters._cldr_source import DEFAULT_LANGUAGES

    selected_langs: frozenset[str] | None = (
        frozenset(languages) if languages is not None else frozenset(DEFAULT_LANGUAGES)
    )
    cache_path = Path(cache_dir) if cache_dir else None

    try:
        zip_path = _download(GEONAMES_URL, cache_path)
    except Exception as exc:
        logger.warning("GeoNames alternateNames download failed: %s", exc)
        return []

    # Build geonameId → ISO2 mapping from countryInfo.txt so we can
    # bridge to stores that have ISO2 codes but not geonames codes.
    geonameid_to_iso2 = _load_country_info(cache_path)

    examples: list[LabeledExample] = []

    try:
        with (
            zipfile.ZipFile(zip_path) as zf,
            zf.open("alternateNames.txt") as raw,
        ):
            text_stream = TextIOWrapper(raw, encoding="utf-8", errors="replace")
            reader = csv.reader(text_stream, delimiter="\t")
            for row in reader:
                ex = _parse_row(row, store, geonameid_to_iso2, selected_langs)
                if ex is not None:
                    examples.append(ex)
                    if limit is not None and len(examples) >= limit:
                        return examples
    except Exception as exc:
        logger.warning("GeoNames: error processing zip: %s", exc)

    return examples
