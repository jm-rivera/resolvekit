"""CLDR country names adapter."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from resolvekit.calibration.adapters._cldr_source import (
    CLDR_URL,
    CLDR_VERSION,
    DEFAULT_LANGUAGES,
    download_cldr_zip,
    read_cldr_territories,
)

if TYPE_CHECKING:
    from resolvekit.calibration.dataset import LabeledExample
    from resolvekit.core.store import EntityStore

logger = logging.getLogger(__name__)

# Alias for monkeypatch seams in tests: keep this name pointing at the
# shared implementation so test patches of `adapters.cldr._download` intercept.
_download = download_cldr_zip


def cldr_generate_geo_pairs(
    *,
    store: EntityStore,
    languages: list[str] | None = None,
    cache_dir: str | Path | None = None,
    limit: int | None = None,
) -> list[LabeledExample]:
    """Generate (territory name, DCID) pairs from CLDR data.

    Args:
        store: Entity store providing ``lookup_code('iso2', code)``.
        languages: Language codes to include. Defaults to
            :data:`DEFAULT_LANGUAGES`.
        cache_dir: Pooch cache for the CLDR zip download.
        limit: Maximum number of examples to return.
    """
    from resolvekit.calibration.dataset import LabeledExample

    selected_langs = languages or DEFAULT_LANGUAGES
    cache_path = Path(cache_dir) if cache_dir else None

    zip_path = _download(cache_path)
    if zip_path is None:
        return []

    examples: list[LabeledExample] = []
    seen: set[tuple[str, str]] = set()

    try:
        for lang in selected_langs:
            territories = read_cldr_territories(zip_path, lang)
            if territories is None:
                continue

            for code, name in territories.items():
                # Skip numeric-only codes (UN M.49 regions like "001", "150")
                if code.isdigit():
                    continue
                # Skip variant markers (e.g. "US-alt-short")
                if "-alt-" in code:
                    continue

                key = (code, name)
                if key in seen:
                    continue
                seen.add(key)

                # Map ISO alpha-2 code to DCID
                entity_ids = store.lookup_code("iso2", code.lower())
                if not entity_ids:
                    continue

                dcid = entity_ids[0]
                examples.append(
                    LabeledExample(
                        query_text=name,
                        expected_entity_id=dcid,
                        source_adapter="cldr",
                        domain="geo",
                    )
                )

                if limit is not None and len(examples) >= limit:
                    return examples

    except Exception as exc:
        logger.warning("CLDR: error processing zip: %s", exc)

    return examples


__all__ = [
    "CLDR_URL",
    "CLDR_VERSION",
    "DEFAULT_LANGUAGES",
    "cldr_generate_geo_pairs",
]
