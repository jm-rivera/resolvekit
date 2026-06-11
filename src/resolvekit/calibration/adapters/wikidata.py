"""Wikidata SPARQL adapter for geo and org entities."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from resolvekit.calibration.adapters._latin_filter import is_latin_recoverable
from resolvekit.calibration.adapters._wikidata_client import (
    GEO_ENTITY_TYPES,
    ORG_ENTITY_TYPES,
    sparql_query,
)

if TYPE_CHECKING:
    from resolvekit.calibration.dataset import LabeledExample
    from resolvekit.core.store import EntityStore

logger = logging.getLogger(__name__)

USER_AGENT = "ResolveKit/1.0 (calibration; https://github.com/jm-rivera/resolvekit)"
REQUEST_DELAY = 1.0  # seconds between requests

DEFAULT_LANGUAGES = ["en", "es", "fr", "de"]


def _load_cache(cache_path: Path) -> list[dict] | None:
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _save_cache(cache_path: Path, data: list[dict]) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(data), encoding="utf-8")
    except Exception as exc:
        logger.debug("Could not write cache %s: %s", cache_path, exc)


def _fetch(
    entity_type: str,
    lang: str,
    *,
    name: str,
    cache_dir: Path | None,
    query_limit: int,
) -> list[dict]:
    """Fetch with cache and rate limiting between every non-cached request."""
    if cache_dir is not None:
        cache_path = cache_dir / f"wikidata_{name}_{entity_type}_{lang}.json"
        cached = _load_cache(cache_path)
        if cached is not None:
            return cached

    time.sleep(REQUEST_DELAY)

    bindings = sparql_query(
        entity_type=entity_type,
        lang=lang,
        limit=query_limit,
        user_agent=USER_AGENT,
    )

    if cache_dir is not None:
        _save_cache(cache_path, bindings)  # type: ignore[possibly-undefined]

    return bindings


def _wikidata_generate_pairs(
    *,
    store: EntityStore,
    entity_types: tuple[str, ...],
    source_name: str,
    source_domain: str,
    languages: list[str] | None,
    cache_dir: Path | None,
    query_limit: int,
    limit: int | None,
) -> list[LabeledExample]:
    """Shared core: generate (label/alias, DCID) pairs via Wikidata SPARQL."""
    from resolvekit.calibration.dataset import LabeledExample

    selected_langs = languages or DEFAULT_LANGUAGES
    examples: list[LabeledExample] = []
    seen: set[tuple[str, str]] = set()

    for entity_type in entity_types:
        for lang in selected_langs:
            bindings = _fetch(
                entity_type,
                lang,
                name=source_name,
                cache_dir=cache_dir,
                query_limit=query_limit,
            )

            for binding in bindings:
                # "http://www.wikidata.org/entity/Q123" → "Q123"
                item_uri = binding.get("item", {}).get("value", "")
                qid = item_uri.rsplit("/", 1)[-1]
                if not qid.startswith("Q"):
                    continue

                # Map QID → DCID
                entity_ids = store.lookup_code("wikidata", qid.lower())
                if not entity_ids:
                    continue
                dcid = entity_ids[0]

                # Collect label and altLabel
                names: list[str] = []
                label = binding.get("itemLabel", {}).get("value", "")
                if label and not label.startswith("Q"):  # skip QID fallbacks
                    names.append(label)
                alt_label = binding.get("altLabel", {}).get("value", "")
                if alt_label:
                    names.append(alt_label)

                for name in names:
                    if not is_latin_recoverable(name):
                        continue
                    key = (name, dcid)
                    if key in seen:
                        continue
                    seen.add(key)
                    examples.append(
                        LabeledExample(
                            query_text=name,
                            expected_entity_id=dcid,
                            source_adapter=source_name,
                            domain=source_domain,
                        )
                    )
                    if limit is not None and len(examples) >= limit:
                        return examples

    return examples


def wikidata_generate_geo_pairs(
    *,
    store: EntityStore,
    languages: list[str] | None = None,
    cache_dir: str | Path | None = None,
    query_limit: int = 5000,
    limit: int | None = None,
) -> list[LabeledExample]:
    """Generate (label/alias, DCID) pairs for geo entities via Wikidata SPARQL.

    Args:
        store: Entity store providing ``lookup_code('wikidata', qid)``.
        languages: Language codes to query. Defaults to
            :data:`DEFAULT_LANGUAGES`.
        cache_dir: Directory for caching SPARQL responses.
        query_limit: Max results per SPARQL query.
        limit: Maximum number of examples to return.
    """
    return _wikidata_generate_pairs(
        store=store,
        entity_types=GEO_ENTITY_TYPES,
        source_name="wikidata_geo",
        source_domain="geo",
        languages=languages,
        cache_dir=Path(cache_dir) if cache_dir else None,
        query_limit=query_limit,
        limit=limit,
    )


def wikidata_generate_org_pairs(
    *,
    store: EntityStore,
    languages: list[str] | None = None,
    cache_dir: str | Path | None = None,
    query_limit: int = 5000,
    limit: int | None = None,
) -> list[LabeledExample]:
    """Generate (label/alias, DCID) pairs for org entities via Wikidata SPARQL.

    Args:
        store: Entity store providing ``lookup_code('wikidata', qid)``.
        languages: Language codes to query. Defaults to
            :data:`DEFAULT_LANGUAGES`.
        cache_dir: Directory for caching SPARQL responses.
        query_limit: Max results per SPARQL query.
        limit: Maximum number of examples to return.
    """
    return _wikidata_generate_pairs(
        store=store,
        entity_types=ORG_ENTITY_TYPES,
        source_name="wikidata_org",
        source_domain="org",
        languages=languages,
        cache_dir=Path(cache_dir) if cache_dir else None,
        query_limit=query_limit,
        limit=limit,
    )
