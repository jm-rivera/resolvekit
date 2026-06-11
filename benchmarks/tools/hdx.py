"""hdx-python-country adapter - multilingual country lookup.

Supports: entity_type={"country"}, language={"en", "es", "fr", "de"}.
"""

from __future__ import annotations

from typing import Any, ClassVar

from benchmarks.core.kernel import Query, Response
from benchmarks.core.toolspec import ToolSpec
from benchmarks.tools._util import _pkg_version


class HdxAdapter:
    spec: ClassVar[ToolSpec] = ToolSpec(
        name="hdx_python_country",
        distribution="hdx-python-country",
        offline=True,
        entity_types=frozenset({"country"}),
    )

    def __init__(self) -> None:
        try:
            from hdx.location.country import Country
        except ImportError as exc:
            raise ImportError(
                "hdx-python-country is required for HdxAdapter. "
                "Install with: uv add hdx-python-country"
            ) from exc
        self._country: Any = Country

    def warmup(self) -> None:
        self._country.get_iso3_country_code_fuzzy("United States", use_live=False)

    def resolve(self, query: Query) -> Response:
        text = query.text.strip()
        if not text:
            return Response(status="no_match")
        try:
            exact = self._country.get_iso3_country_code(text)
            if exact:
                return Response(
                    status="match",
                    match_ids=(f"country/{exact}",),
                )
            # Upstream API: get_iso3_country_code_fuzzy returns (iso3, exact_bool).
            fuzzy = self._country.get_iso3_country_code_fuzzy(text, use_live=False)
        except Exception as exc:
            return Response(status="error", error=repr(exc))
        iso3: str | None = None
        if isinstance(fuzzy, tuple) and fuzzy:
            iso3 = fuzzy[0]
        elif isinstance(fuzzy, str):
            iso3 = fuzzy
        if not iso3:
            return Response(status="no_match")
        return Response(
            status="match",
            match_ids=(f"country/{iso3}",),
        )

    def version(self) -> str | None:
        return _pkg_version(self.spec.distribution)
