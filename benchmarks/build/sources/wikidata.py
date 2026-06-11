"""Wikidata builder — canonical + alias labels for country entities."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from benchmarks.core.kernel import Query
from resolvekit.calibration.adapters._wikidata_client import (
    GEO_ENTITY_TYPES,
    WIKIDATA_SPARQL_URL,  # noqa: F401 — re-exported; benchmarks/build/__init__.py reads wikidata.WIKIDATA_SPARQL_URL
    sparql_query,
)

if TYPE_CHECKING:
    from resolvekit.core.store import EntityStore

logger = logging.getLogger(__name__)

USER_AGENT = "ResolveKit/1.0 (benchmark; https://github.com/jm-rivera/resolvekit)"
REQUEST_DELAY = 1.0
DEFAULT_LANGUAGES: tuple[str, ...] = ("en", "es", "fr", "de")


def build(
    *,
    store: EntityStore,
    limit: int | None = None,
    seed: int = 42,
    languages: list[str] | None = None,
    cache_dir: Path | None = None,
    query_limit: int = 2000,
) -> list[Query]:
    del seed
    langs = tuple(languages) if languages is not None else DEFAULT_LANGUAGES

    rows: list[Query] = []
    seen: set[tuple[str, str, str]] = set()

    from resolvekit.calibration.adapters._latin_filter import is_latin_recoverable

    for entity_type in GEO_ENTITY_TYPES:
        for lang in langs:
            bindings = _fetch(
                entity_type=entity_type,
                lang=lang,
                cache_dir=cache_dir,
                query_limit=query_limit,
            )
            for binding in bindings:
                qid = binding.get("item", {}).get("value", "").rsplit("/", 1)[-1]
                if not qid.startswith("Q"):
                    continue
                entity_ids = store.lookup_code("wikidata", qid.lower())
                if not entity_ids:
                    continue
                dcid = entity_ids[0]
                # Only emit rows whose resolved entity is in the country/ namespace.
                # GEO_ENTITY_TYPES includes Q10864048 (admin1) and Q515 (city) which
                # Wikidata classifies as subtypes of sovereign states; these must be
                # excluded from the country benchmark. ISO 3166-1 dependent territories
                # stored as geo.admin1 in the entity store (American Samoa, Guam, etc.)
                # still resolve to country/ IDs so they are retained correctly.
                if not dcid.startswith("country/"):
                    continue

                label = binding.get("itemLabel", {}).get("value", "")
                alt_label = binding.get("altLabel", {}).get("value", "")
                candidates: tuple[tuple[str, bool], ...] = (
                    (label, False),
                    (alt_label, True),
                )
                for name, is_alias in candidates:
                    if not name:
                        continue
                    if not is_alias and name.startswith("Q"):
                        continue
                    if not is_latin_recoverable(name):
                        continue
                    if is_alias and len(name) <= 3 and name.isalpha():
                        continue  # ISO-2 / IOC / FIFA code aliases — code-lookups, not name queries
                    key = (lang, name.lower(), dcid)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append(
                        _make_row(
                            text=name,
                            dcid=dcid,
                            language=lang,
                            is_alias=is_alias,
                        )
                    )
                    if limit is not None and len(rows) >= limit:
                        return rows

    return rows


def _make_row(
    *,
    text: str,
    dcid: str,
    language: str,
    is_alias: bool,
) -> Query:
    category: str
    capabilities: tuple[str, ...]
    if is_alias:
        category = "alias"
        capabilities = ("multilingual", "alias") if language != "en" else ("alias",)
    else:
        category = "canonical"
        capabilities = ("multilingual",) if language != "en" else ()

    return Query(
        query_id="",
        text=text,
        expected_ids=(dcid,),
        language=language,
        entity_type="country",
        category=category,
        difficulty="medium",
        capabilities=capabilities,
        source="wikidata",
        notes=None,
    )


def _fetch(
    *,
    entity_type: str,
    lang: str,
    cache_dir: Path | None,
    query_limit: int,
) -> list[dict]:
    cache_path: Path | None = None
    if cache_dir is not None:
        cache_path = cache_dir / f"wikidata_wikidata_geo_{entity_type}_{lang}.json"
        if cache_path.exists():
            try:
                cached: list[dict] = json.loads(cache_path.read_text())
                return cached
            except Exception:
                logger.debug("Cache read failed for %s; refetching", cache_path)

    time.sleep(REQUEST_DELAY)
    bindings = sparql_query(
        entity_type=entity_type,
        lang=lang,
        limit=query_limit,
        user_agent=USER_AGENT,
    )

    if cache_path is not None and bindings:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(bindings))
        except Exception as exc:
            logger.debug("Cache write failed for %s: %s", cache_path, exc)

    return bindings
