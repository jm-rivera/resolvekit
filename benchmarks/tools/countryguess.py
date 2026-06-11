"""countryguess adapter - stdlib-only fuzzy country lookup.

Supports: entity_type={"country"}, language={"en"}.
"""

from __future__ import annotations

from typing import Any, ClassVar

from benchmarks.core.kernel import Query, Response
from benchmarks.core.toolspec import ToolSpec
from benchmarks.tools._util import _pkg_version


def _field(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


class CountryguessAdapter:
    spec: ClassVar[ToolSpec] = ToolSpec(
        name="countryguess",
        distribution="countryguess",
        offline=True,
        entity_types=frozenset({"country"}),
    )

    def __init__(self) -> None:
        try:
            import countryguess
        except ImportError as exc:
            raise ImportError(
                "countryguess is required for CountryguessAdapter. "
                "Install with: uv add countryguess"
            ) from exc
        self._module: Any = countryguess

    def warmup(self) -> None:
        self._module.guess_country("United States")

    def resolve(self, query: Query) -> Response:
        text = query.text.strip()
        if not text:
            return Response(status="no_match")
        try:
            result = self._module.guess_country(text)
        except Exception as exc:
            return Response(status="error", error=repr(exc))
        if not result:
            return Response(status="no_match")
        iso3 = _field(result, "iso3")
        if not iso3:
            return Response(status="no_match")
        return Response(
            status="match",
            match_ids=(f"country/{iso3}",),
            canonical_name=_field(result, "name_short"),
        )

    def version(self) -> str | None:
        return _pkg_version(self.spec.distribution)
