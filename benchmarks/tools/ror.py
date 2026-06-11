"""ROR /affiliation adapter - online, cached.

Reads cached responses from ``benchmarks/cache/ror/`` when available;
otherwise calls the live ROR v2 affiliation endpoint.

Supports: entity_type={"org"}, language={"en"}.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from benchmarks.core.kernel import Query, Response
from benchmarks.core.toolspec import ToolSpec
from benchmarks.tools.jsoncache import JsonCache

_DEFAULT_CACHE = Path("benchmarks/cache/ror")
_ROR_BASE_URL = "https://api.ror.org/v2/organizations"
_MATCH_THRESHOLD = 0.9


class RorAdapter:
    spec: ClassVar[ToolSpec] = ToolSpec(
        name="ror_affiliation",
        distribution="",
        offline=False,
        entity_types=frozenset({"org"}),
    )

    def __init__(
        self,
        *,
        cache_dir: Path | None = None,
        refresh: bool = False,
        timeout: float = 10.0,
    ) -> None:
        self._cache = JsonCache(
            Path(cache_dir) if cache_dir is not None else _DEFAULT_CACHE
        )
        self._refresh = refresh
        self._timeout = timeout

    def warmup(self) -> None:
        self._cache.cache_dir.mkdir(parents=True, exist_ok=True)

    def _call_live(self, query: str) -> dict[str, Any]:
        url = f"{_ROR_BASE_URL}?{urlencode({'affiliation': query})}"
        req = Request(url, headers={"User-Agent": "resolvekit-benchmark/0"})
        with urlopen(req, timeout=self._timeout) as resp:
            body = resp.read().decode("utf-8")
        return json.loads(body)

    def _best_item(
        self, payload: dict[str, Any]
    ) -> tuple[dict[str, Any], float] | None:
        items = payload.get("items") or []
        best: tuple[dict[str, Any], float] | None = None
        for item in items:
            score = float(item.get("score") or 0.0)
            org = item.get("organization") or {}
            if best is None or score > best[1]:
                best = (org, score)
        return best

    def _display_name(self, org: dict[str, Any]) -> str | None:
        for name_entry in org.get("names") or []:
            types = name_entry.get("types") or []
            if "ror_display" in types:
                value = name_entry.get("value")
                if value:
                    return str(value)
        for name_entry in org.get("names") or []:
            value = name_entry.get("value")
            if value:
                return str(value)
        return None

    def resolve(self, query: Query) -> Response:
        text = query.text.strip()
        if not text:
            return Response(status="no_match")
        payload: dict[str, Any] | None = None
        if not self._refresh:
            payload = self._cache.read(text, query.language)
        if payload is None:
            try:
                payload = self._call_live(text)
            except Exception as exc:
                return Response(status="error", error=repr(exc))
            with contextlib.suppress(OSError):
                self._cache.write(text, query.language, payload)
        best = self._best_item(payload)
        if best is None:
            return Response(status="no_match")
        org, score = best
        if score < _MATCH_THRESHOLD:
            return Response(
                status="no_match",
                confidence=score,
            )
        ror_url = str(org.get("id") or "")
        ror_id = ror_url.rsplit("/", 1)[-1] if ror_url else ""
        if not ror_id:
            return Response(status="no_match")
        return Response(
            status="match",
            match_ids=(f"ror/{ror_id}",),
            canonical_name=self._display_name(org),
            confidence=score,
        )

    def version(self) -> str | None:
        return None
