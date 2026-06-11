"""pycountry adapter - exact ISO code + name lookup.

Supports: entity_type={"country"}, language={"en"}.
"""

from __future__ import annotations

from typing import Any, ClassVar

from benchmarks.core.kernel import Query, Response
from benchmarks.core.toolspec import ToolSpec
from benchmarks.tools._util import _pkg_version


class PycountryAdapter:
    spec: ClassVar[ToolSpec] = ToolSpec(
        name="pycountry",
        distribution="pycountry",
        offline=True,
        entity_types=frozenset({"country"}),
    )

    _ACCESSORS: ClassVar[tuple[str, ...]] = (
        "alpha_2",
        "alpha_3",
        "numeric",
        "name",
        "official_name",
    )

    def __init__(self) -> None:
        try:
            import pycountry
        except ImportError as exc:
            raise ImportError(
                "pycountry is required for PycountryAdapter. "
                "Install with: uv add pycountry"
            ) from exc
        self._pycountry: Any = pycountry

    def warmup(self) -> None:
        list(self._pycountry.countries)

    def resolve(self, query: Query) -> Response:
        text = query.text.strip()
        if not text:
            return Response(status="no_match")
        try:
            for accessor in self._ACCESSORS:
                country = self._pycountry.countries.get(**{accessor: text})
                if country is not None:
                    return Response(
                        status="match",
                        match_ids=(f"country/{country.alpha_3}",),
                        canonical_name=country.name,
                    )
        except Exception as exc:
            return Response(status="error", error=repr(exc))
        return Response(status="no_match")

    def version(self) -> str | None:
        return _pkg_version(self.spec.distribution)
