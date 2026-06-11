"""geonamescache adapter - offline country + city name lookup.

Supports: entity_type={"country", "city"}, language={"en"}.
"""

from __future__ import annotations

from typing import Any, ClassVar

from benchmarks.core.kernel import Query, Response
from benchmarks.core.toolspec import ToolSpec
from benchmarks.tools._util import _pkg_version


class GeonamescacheAdapter:
    spec: ClassVar[ToolSpec] = ToolSpec(
        name="geonamescache",
        distribution="geonamescache",
        offline=True,
        entity_types=frozenset({"country", "city"}),
    )

    def __init__(self) -> None:
        try:
            import geonamescache
        except ImportError as exc:
            raise ImportError(
                "geonamescache is required for GeonamescacheAdapter. "
                "Install with: uv add geonamescache"
            ) from exc
        self._module: Any = geonamescache
        self._gc: Any = None
        self._countries_by_name: dict[str, dict[str, Any]] = {}

    def warmup(self) -> None:
        self._gc = self._module.GeonamesCache()
        countries = self._gc.get_countries_by_names()
        self._countries_by_name = {
            name.casefold(): info for name, info in countries.items()
        }
        self._gc.get_cities()

    def resolve(self, query: Query) -> Response:
        text = query.text.strip()
        if not text:
            return Response(status="no_match")
        if self._gc is None:
            self.warmup()
        assert self._gc is not None
        return self._lookup(text=text, entity_type=query.entity_type)

    def _lookup(self, *, text: str, entity_type: str) -> Response:
        try:
            # Country dict lookup: only attempted for country-typed (or untyped) queries.
            if entity_type != "city":
                info = self._countries_by_name.get(text.casefold())
                if info is not None:
                    iso3 = info.get("iso3")
                    if iso3:
                        return Response(
                            status="match",
                            match_ids=(f"country/{iso3}",),
                            canonical_name=info.get("name"),
                        )
            # City search is skipped for country-typed queries to avoid the ~70 ms
            # full-scan penalty from searching ~165 MB of bundled city data on every
            # country miss.
            if entity_type == "country":
                return Response(status="no_match")
            cities = self._gc.search_cities(text, case_sensitive=False)
        except Exception as exc:
            return Response(status="error", error=repr(exc))
        if not cities:
            return Response(status="no_match")
        city = cities[0]
        geoname_id = city.get("geonameid")
        if not geoname_id:
            return Response(status="no_match")
        return Response(
            status="match",
            match_ids=(f"city/{geoname_id}",),
            canonical_name=city.get("name"),
        )

    def version(self) -> str | None:
        return _pkg_version(self.spec.distribution)
