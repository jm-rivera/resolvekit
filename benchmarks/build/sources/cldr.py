"""CLDR builder — emits canonical country names per language."""

from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from benchmarks.build.sources._geo_common import _download
from benchmarks.core.kernel import Query
from resolvekit.calibration.adapters.cldr import CLDR_URL, CLDR_VERSION

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
    langs = tuple(languages) if languages is not None else DEFAULT_LANGUAGES

    try:
        zip_path = _download(url=CLDR_URL, cache_dir=cache_dir)
    except Exception as exc:
        logger.warning("CLDR download failed: %s", exc)
        return []

    rows: list[Query] = []
    seen: set[tuple[str, str, str]] = set()

    try:
        with zipfile.ZipFile(zip_path) as zf:
            for lang in langs:
                territory_path = (
                    f"cldr-json-{CLDR_VERSION}/cldr-json/cldr-localenames-full/"
                    f"main/{lang}/territories.json"
                )
                try:
                    data = json.loads(zf.read(territory_path))
                except KeyError:
                    logger.debug("CLDR: no territories.json for lang=%s", lang)
                    continue
                except Exception as exc:
                    logger.warning("CLDR: error reading %s: %s", territory_path, exc)
                    continue

                territories = (
                    data.get("main", {})
                    .get(lang, {})
                    .get("localeDisplayNames", {})
                    .get("territories", {})
                )

                for code, name in territories.items():
                    if code.isdigit() or "-alt-" in code:
                        continue

                    entity_ids = store.lookup_code("iso2", code.lower())
                    if not entity_ids:
                        continue
                    dcid = entity_ids[0]

                    key = (lang, name.lower(), dcid)
                    if key in seen:
                        continue
                    seen.add(key)

                    capabilities = ("multilingual",) if lang != "en" else ()
                    rows.append(
                        Query(
                            query_id="",
                            text=name,
                            expected_ids=(dcid,),
                            language=lang,
                            entity_type="country",
                            category="canonical",
                            difficulty="easy",
                            capabilities=capabilities,
                            source="cldr",
                            notes=None,
                        )
                    )
                    if limit is not None and len(rows) >= limit:
                        return rows
    except Exception as exc:
        logger.warning("CLDR: error processing zip: %s", exc)

    return rows
