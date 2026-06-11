"""country_converter (coco) adapter - alias + regex table lookup.

Supports: entity_type={"country"}, language={"en"}.
"""

from __future__ import annotations

from typing import Any, ClassVar

from benchmarks.core.kernel import Query, Response
from benchmarks.core.toolspec import ToolSpec
from benchmarks.tools._util import _pkg_version


class CountryConverterAdapter:
    spec: ClassVar[ToolSpec] = ToolSpec(
        name="country_converter",
        distribution="country_converter",
        offline=True,
        entity_types=frozenset({"country"}),
    )

    _SENTINEL: ClassVar[str] = "__RK_NOT_FOUND__"

    def __init__(self) -> None:
        try:
            import country_converter
        except ImportError as exc:
            raise ImportError(
                "country_converter is required for CountryConverterAdapter. "
                "Install with: uv add country-converter"
            ) from exc
        self._module: Any = country_converter
        self._cc: Any = None

    def warmup(self) -> None:
        self._cc = self._module.CountryConverter()
        self._cc.convert(names="United States", to="ISO3", not_found=self._SENTINEL)

    def resolve(self, query: Query) -> Response:
        text = query.text.strip()
        if not text:
            return Response(status="no_match")
        if self._cc is None:
            self.warmup()
        assert self._cc is not None
        try:
            iso3 = self._cc.convert(names=text, to="ISO3", not_found=self._SENTINEL)
        except Exception as exc:
            return Response(status="error", error=repr(exc))
        if not iso3 or iso3 == self._SENTINEL:
            return Response(status="no_match")
        return Response(
            status="match",
            match_ids=(f"country/{iso3}",),
        )

    def version(self) -> str | None:
        return _pkg_version(self.spec.distribution)
