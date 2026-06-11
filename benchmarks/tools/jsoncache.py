"""Shared JSON response cache for online adapters.

Both ``data_commons`` and ``ror`` adapters use an identical cache layout:
SHA256 of ``"{query}|{language}"`` as the filename, JSON payload written
with ``indent=2, sort_keys=True``. This module centralises that logic so
the two adapters compose a ``JsonCache`` instead of duplicating ~40 lines.

**Cache compatibility guarantee:** the key scheme and on-disk format are
byte-identical to the prior per-adapter implementation, so existing cache
files under ``benchmarks/cache/data_commons/`` and ``benchmarks/cache/ror/``
continue to hit without regeneration.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmarks.tools._util import _cache_path


class JsonCache:
    """Read/write a directory of SHA256-keyed JSON cache files.

    The cache file for ``(query, language)`` is stored at::

        <cache_dir>/<sha256("{query}|{language}".encode()).hexdigest()>.json

    Content is written as ``json.dumps(payload, indent=2, sort_keys=True)``.
    """

    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = cache_dir

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    def _path(self, query: str, language: str) -> Path:
        return _cache_path(self._cache_dir, f"{query}|{language}")

    def read(self, query: str, language: str) -> dict[str, Any] | None:
        """Return the cached payload for ``(query, language)``, or ``None``."""
        path = self._path(query, language)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[return-value]
        except (OSError, json.JSONDecodeError):
            return None

    def write(self, query: str, language: str, payload: dict[str, Any]) -> None:
        """Persist ``payload`` to the cache for ``(query, language)``."""
        path = self._path(query, language)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
