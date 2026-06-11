"""Multilingual country name adapter for entity-store ingestion.

The :func:`cldr_generate_geo_pairs` function generates calibration training
pairs ``(query_text, expected_entity_id)`` from CLDR territory names. Those
pairs are used to fit the calibrator — they do **not** populate the SQLite
``names`` table, so they have no effect on resolution recall against
multilingual queries.

Resolution recall against multilingual queries depends on the ``names`` table
containing localised name rows for each entity. Today the only path that adds
those rows is the Data Commons source adapter, which fetches ``alternateName``
per language. Coverage is uneven — Data Commons returns 0 German country names
and only ~140 each for French/Spanish across 238 country entities.

This module bridges that gap. It exposes:

* :func:`generate_name_rows` — produces a list of dicts shaped for direct
  insertion into the SQLite ``names`` table
  ``(entity_id, name_kind, value, value_norm, lang, script, is_preferred)``.
  The build pipeline (owned by the ``pipeline-and-calibration`` agent) consumes
  these rows after the Data Commons fetch and before FTS rebuild, similar to how
  ``builder/formal_names.py`` injects formal English designations.

* :func:`multilingual_generate_geo_pairs` — a calibration free function
  emitting :class:`LabeledExample` pairs for every name row, so the calibrator
  can learn from the same multilingual coverage that resolution will use.

Source: CLDR via the cached zip download from the existing
:func:`cldr_generate_geo_pairs` (no extra HTTP traffic). When the cached zip
isn't available we fall back to ``babel.Locale`` which ships its own copy of
CLDR territory names.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from resolvekit.calibration.adapters._cldr_source import (
    download_cldr_zip,
    read_cldr_territories,
)

if TYPE_CHECKING:
    from resolvekit.calibration.dataset import LabeledExample
    from resolvekit.core.store import EntityStore

logger = logging.getLogger(__name__)

# Six UN official languages plus Portuguese/Italian/Japanese for breadth.
# CLDR ships authoritative names for all of these.
UN_OFFICIAL_LANGUAGES: tuple[str, ...] = ("en", "es", "fr", "ru", "zh", "ar")
EXTENDED_LANGUAGES: tuple[str, ...] = (*UN_OFFICIAL_LANGUAGES, "pt", "it", "ja", "de")

# CLDR variants we ingest. ``short`` gives compact aliases (e.g. "USA",
# "UK", "EE.UU."). ``variant`` and region-specific markers (``biot``,
# ``chagos``) are skipped because they are politically sensitive
# alternative renderings rather than commonly used aliases.
_ACCEPTED_ALT_KINDS: frozenset[str] = frozenset({"short"})

# Map ISO15924 / common script names to the SQLite ``script`` column
# value. We populate this for non-Latin scripts to help future scoring
# decisions; Latin-script languages get an empty string (matches the
# existing convention for English/Spanish/French rows).
_LANG_SCRIPT: dict[str, str] = {
    "ru": "Cyrl",
    "zh": "Hans",
    "ar": "Arab",
    "ja": "Jpan",
    # Languages omitted here default to "" (Latin-script).
}

# Bridge CLDR ISO 3166-1 alpha-2 codes to ISO 3166-1 alpha-3 codes for
# entities the upstream Data Commons import did not tag with ``iso2``.
# Each mapping resolves to the alpha-3 code our entity store carries
# under the ``iso3`` system. Only a small handful of CLDR territories
# fall into this bucket (~8 in the geo.countries pack).
_ISO2_TO_ISO3_FALLBACK: dict[str, str] = {
    "ss": "ssd",  # South Sudan
    "xk": "xkx",  # Kosovo (M.49 user-assigned)
    "ax": "ala",  # Åland Islands
    "bq": "bes",  # Bonaire, Sint Eustatius and Saba
}


def _normalize_text(value: str) -> str:
    """Apply the same normalization as the rest of the build pipeline."""
    from resolvekit.core.util.normalization import TextNormalizer

    return TextNormalizer().normalize(value)


def _read_babel_territories(lang: str) -> dict[str, str] | None:
    """Fallback: read territory names from Babel's bundled CLDR data."""
    try:
        from babel import Locale, UnknownLocaleError
    except ImportError:
        logger.warning(
            "Babel not installed; multilingual names cannot be sourced for %s",
            lang,
        )
        return None
    try:
        loc = Locale.parse(lang)
    except (UnknownLocaleError, ValueError):
        logger.warning("Babel: unknown locale %r", lang)
        return None
    return dict(loc.territories)


def _territories_for_language(
    lang: str,
    zip_path: Path | None,
) -> dict[str, str]:
    """Return raw {code: name} mapping for a language, with alt variants.

    Prefers the cached CLDR zip (which carries ``-alt-short`` variants),
    falling back to ``babel.Locale.territories`` (no alt variants).
    """
    if zip_path is not None:
        from_zip = read_cldr_territories(zip_path, lang)
        if from_zip:
            return from_zip
    return _read_babel_territories(lang) or {}


# Alias for monkeypatch seams in tests: keep this name pointing at the
# shared implementation so test patches of `adapters.multilingual_names._download_cldr` intercept.
_download_cldr = download_cldr_zip


def generate_name_rows(
    *,
    store: EntityStore,
    languages: list[str] | None = None,
    cache_dir: str | Path | None = None,
    include_short_variants: bool = True,
) -> list[dict[str, Any]]:
    """Generate ``names``-table rows for each (country, language) pair.

    Each row carries the schema fields expected by the build pipeline's
    SQLite writer: ``entity_id``, ``name_kind``, ``value``,
    ``value_norm``, ``lang``, ``script``, ``is_preferred``. Rows are
    ready for ``INSERT OR IGNORE INTO names(...)``.

    ``name_kind`` is set to ``"alias"`` and ``is_preferred`` to ``0``
    so injected rows do not displace the canonical English name that
    the Data Commons fetch already populates.

    Returns one row per (entity, language, surface form) combination,
    deduplicated on ``(entity_id, value_norm, lang, script)``.

    Args:
        store: Entity store providing ``lookup_code('iso2', code)``.
        languages: 2-letter language codes to ingest. Defaults to
            :data:`EXTENDED_LANGUAGES` (6 UN official + pt/it/ja/de).
        cache_dir: Pooch cache for the CLDR zip download. Default is
            the Pooch user cache.
        include_short_variants: When ``True`` (default), CLDR
            ``-alt-short`` entries (e.g. "USA", "UK", "EE.UU.") are
            emitted alongside the canonical localised name.
    """
    selected_langs = list(languages) if languages else list(EXTENDED_LANGUAGES)
    cache_path = Path(cache_dir) if cache_dir else None

    zip_path = _download_cldr(cache_path)

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()

    for lang in selected_langs:
        territories = _territories_for_language(lang, zip_path)
        if not territories:
            continue

        script = _LANG_SCRIPT.get(lang, "")

        for code, name in territories.items():
            if not name or not isinstance(name, str):
                continue
            if code.isdigit():
                continue

            base_code = code
            is_alt_short = False
            if "-alt-" in code:
                base_code, _, alt = code.partition("-alt-")
                if not include_short_variants:
                    continue
                if alt not in _ACCEPTED_ALT_KINDS:
                    continue
                is_alt_short = alt == "short"

            entity_ids = store.lookup_code("iso2", base_code.lower())
            if not entity_ids:
                fallback_iso3 = _ISO2_TO_ISO3_FALLBACK.get(base_code.lower())
                if fallback_iso3:
                    entity_ids = store.lookup_code("iso3", fallback_iso3)
            if not entity_ids:
                continue
            entity_id = entity_ids[0]

            value_norm = _normalize_text(name)
            if not value_norm:
                continue

            key = (entity_id, value_norm, lang, script)
            if key in seen:
                continue
            seen.add(key)

            rows.append(
                {
                    "entity_id": entity_id,
                    "name_kind": "alias",
                    "value": name,
                    "value_norm": value_norm,
                    "lang": lang,
                    "script": script,
                    "is_preferred": 0,
                    "_alt_short": is_alt_short,
                }
            )

    return rows


def multilingual_generate_geo_pairs(
    *,
    store: EntityStore,
    languages: list[str] | None = None,
    cache_dir: str | Path | None = None,
    include_short_variants: bool = True,
    limit: int | None = None,
) -> list[LabeledExample]:
    """Generate (multilingual name, DCID) pairs from CLDR data.

    Wraps :func:`generate_name_rows` so the calibrator trains on the same
    multilingual coverage that resolution will see at query time.

    Args:
        store: Entity store providing ``lookup_code('iso2', code)``.
        languages: 2-letter language codes. Defaults to
            :data:`EXTENDED_LANGUAGES`.
        cache_dir: Pooch cache for the CLDR zip download.
        include_short_variants: When ``True`` (default), emit
            ``-alt-short`` entries (e.g. "USA", "UK").
        limit: Maximum number of examples to return.
    """
    from resolvekit.calibration.dataset import LabeledExample

    rows = generate_name_rows(
        store=store,
        languages=languages,
        cache_dir=cache_dir,
        include_short_variants=include_short_variants,
    )

    examples: list[LabeledExample] = []
    for row in rows:
        examples.append(
            LabeledExample(
                query_text=row["value"],
                expected_entity_id=row["entity_id"],
                source_adapter="multilingual_names",
                domain="geo",
            )
        )
        if limit is not None and len(examples) >= limit:
            break
    return examples
