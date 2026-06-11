"""Shared CLDR zip download and territory-read helpers.

This module owns the CLDR version constants and the two functions used by
both ``cldr.py`` and ``multilingual_names.py`` to fetch and read territory
names from the CLDR JSON archive.
"""

from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CLDR_VERSION = "46.0.0"
CLDR_URL = (
    f"https://github.com/unicode-org/cldr-json/archive/refs/tags/{CLDR_VERSION}.zip"
)
# Pinned hash for the immutable GitHub tag archive above.
# Recompute with: shasum -a 256 <cached-file>
_CLDR_ZIP_SHA256 = (
    "sha256:dc9310a03e460f15ade6c5979e66d952f1ba2b7cda175692b0ccc37fa7c71a23"
)

# Languages used to seed CLDR calibration training pairs:
# six UN official languages plus German, Portuguese, Italian and Japanese.
DEFAULT_LANGUAGES = ["en", "es", "fr", "de", "ru", "zh", "ar", "pt", "it", "ja"]


def download_cldr_zip(cache_dir: Path | None) -> Path | None:
    """Download and cache the CLDR zip via pooch; return None on failure.

    On import or retrieve failure, logs a warning and returns None so callers
    can fall back to Babel.
    """
    try:
        import pooch
    except ImportError:
        return None
    try:
        kwargs: dict[str, Any] = {"url": CLDR_URL, "known_hash": _CLDR_ZIP_SHA256}
        if cache_dir is not None:
            kwargs["path"] = cache_dir
        path = pooch.retrieve(**kwargs)
        if isinstance(path, list):
            path = path[0]
        return Path(path)
    except Exception as exc:
        logger.warning("CLDR download failed, falling back to Babel: %s", exc)
        return None


def read_cldr_territories(zip_path: Path, lang: str) -> dict[str, str] | None:
    """Read {code: name} from territories.json for *lang*; None if missing/unreadable."""
    territory_path = (
        f"cldr-json-{CLDR_VERSION}/cldr-json/cldr-localenames-full/"
        f"main/{lang}/territories.json"
    )
    try:
        with zipfile.ZipFile(zip_path) as zf:
            data = json.loads(zf.read(territory_path))
    except KeyError:
        logger.debug("CLDR zip: no territories.json for lang=%s", lang)
        return None
    except Exception as exc:
        logger.warning("CLDR zip: error reading %s: %s", territory_path, exc)
        return None
    territories = (
        data.get("main", {})
        .get(lang, {})
        .get("localeDisplayNames", {})
        .get("territories", {})
    )
    return dict(territories) if territories else None
