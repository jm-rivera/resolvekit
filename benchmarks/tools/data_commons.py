"""Google Data Commons /resolve adapter - online, cached.

Reads cached responses from ``benchmarks/cache/data_commons/`` when
available; otherwise calls the live endpoint at
``datacommons.one.org`` (the public, free ONE-hosted instance).
No API key required.

The official ``datacommons-client`` library calls ``requests.post``
without a timeout, which occasionally hangs for 150+ seconds per call
against the ONE-hosted instance. We install a socket-level default
timeout in ``warmup()`` so those hangs surface as errors instead of
stalling the benchmark. Individual calls are still ~500ms when the
endpoint is warm.

Supports: entity_type={"country", "admin1", "admin2", "city"},
language={"en"}.
"""

from __future__ import annotations

import contextlib
import socket
from pathlib import Path
from typing import Any, ClassVar

from benchmarks.core.kernel import Query, Response
from benchmarks.core.toolspec import ToolSpec
from benchmarks.tools._util import _pkg_version
from benchmarks.tools.jsoncache import JsonCache

_DEFAULT_CACHE = Path("benchmarks/cache/data_commons")
_DC_INSTANCE = "datacommons.one.org"
_DEFAULT_TIMEOUT_S = 10.0


class DataCommonsAdapter:
    spec: ClassVar[ToolSpec] = ToolSpec(
        name="data_commons_resolve",
        distribution="datacommons-client",
        offline=False,
        entity_types=frozenset({"country", "admin1", "admin2", "city"}),
    )

    def __init__(
        self,
        *,
        cache_dir: Path | None = None,
        refresh: bool = False,
        dc_instance: str = _DC_INSTANCE,
        timeout: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self._cache = JsonCache(
            Path(cache_dir) if cache_dir is not None else _DEFAULT_CACHE
        )
        self._refresh = refresh
        self._dc_instance = dc_instance
        self._timeout = timeout
        self._client: Any = None
        try:
            from datacommons_client import DataCommonsClient
        except ImportError as exc:
            raise ImportError(
                "datacommons-client is required for DataCommonsAdapter. "
                "Install with: uv add datacommons-client"
            ) from exc
        self._client_class: Any = DataCommonsClient

    def warmup(self) -> None:
        self._cache.cache_dir.mkdir(parents=True, exist_ok=True)
        # Upstream client's requests.post has no timeout and occasionally
        # hangs indefinitely; cap at the socket layer so it surfaces as an
        # error instead of wedging the benchmark.
        socket.setdefaulttimeout(self._timeout)
        if self._client is None:
            self._client = self._client_class(dc_instance=self._dc_instance)

    def _call_live(self, query: str) -> dict[str, Any]:
        assert self._client is not None, "call warmup() first"
        response = self._client.resolve.fetch_dcids_by_name(names=[query])
        return response.to_dict()

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
        entities = payload.get("entities") or []
        candidates: list[str] = []
        for entity in entities:
            for cand in entity.get("candidates") or []:
                dcid = cand.get("dcid")
                if dcid:
                    candidates.append(str(dcid))
        if not candidates:
            return Response(status="no_match")
        if len(candidates) == 1:
            return Response(
                status="match",
                match_ids=(candidates[0],),
            )
        return Response(
            status="ambiguous",
            match_ids=tuple(candidates),
        )

    def version(self) -> str | None:
        return _pkg_version(self.spec.distribution)
