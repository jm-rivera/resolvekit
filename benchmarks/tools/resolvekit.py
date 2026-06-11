"""resolvekit adapter — the system under test.

Supports: entity_type={"country", "admin1", "admin2", "admin3", "admin4", "admin5",
"city", "country_region", "continent", "continental_union", "world_region", "org"},
language={"en"}.

Two registered modes:
  resolvekit       — pass_hints=False: no context, resolver figures it out from scratch.
  resolvekit_typed — pass_hints=True:  passes entity_type + language from the dataset row.
                     Scores reflect a caller with structured input available. The type
                     hint is hierarchy-aware (a "city" hint admits places stored at any
                     admin level). Supplying hints improves accuracy and substantially
                     lowers wrong-match rate versus the no-hint mode: on geo_countries_en
                     (ISO-only, n=4431) typed scores 0.679 vs plain 0.655, with
                     wrong-match falling to 0.024 from 0.054. On the multilingual set
                     resolvekit now leads (plain 0.622, typed 0.619) ahead of the
                     specialist multilingual tools (hdx_python_country 0.583,
                     countryguess 0.532) — the per-pack normalization contract closed
                     the prior gap on es/fr/de.

Footprint notes (see benchmarks/README.md for full detail):
  - Cold-start:  ~1.6 s (composed-SQLite cache; first-ever build ~15 s, then cached).
  - Construction/exact-lookup RSS: ~49 MB (SymSpell indexes are lazy-built).
  - Benchmark profiled peak RSS: ~125 MB (full geo suite, typed queries).
  - No-hint fuzzy query over deep admin/city tiers: ~1.3 GB RSS — inherent cost
    of SymSpell over ~720 k names; most callers never hit this path (opt-in tiers).
  - Wheel: ~9 MB (code + country pack); deep geo data (~812 MB) is on-demand.

Notes on entity_type extensions:
  country_region  — treated as admin1 internally (US states, provinces, etc.)
  continent       — geo.continent pack
  continental_union — geo.continental_union pack
  world_region    — geo.region pack
  admin5          — geo.admin5 pack
  org             — org pack (not yet loaded by default; resolves via geo fallback)
"""

from __future__ import annotations

from typing import Any, ClassVar

from benchmarks.core.kernel import Query, Response
from benchmarks.core.toolspec import ToolSpec
from benchmarks.tools._util import _pkg_version

# Maps benchmark dataset entity_type values to the geo pack's internal entity_type
# prefix used in EntityRecord.entity_type (e.g. "country" → "geo.country").
# country_region maps to admin1 because it represents sub-national regions
# (US states, Indian states, Mexican states, etc.) — same level in the geo hierarchy.
_ENTITY_TYPE_MAP: dict[str, str] = {
    "country": "geo.country",
    "admin1": "geo.admin1",
    "admin2": "geo.admin2",
    "admin3": "geo.admin3",
    "admin4": "geo.admin4",
    "admin5": "geo.admin5",
    "city": "geo.city",
    "country_region": "geo.admin1",
    "continent": "geo.continent",
    "continental_union": "geo.continental_union",
    "world_region": "geo.region",
}

# The full set of entity types the resolvekit adapter will attempt, including
# continents, regions, and admin5 variants.
_GEO_ENTITY_TYPES: frozenset[str] = frozenset(
    {
        "country",
        "admin1",
        "admin2",
        "admin3",
        "admin4",
        "admin5",
        "city",
        "country_region",
        "continent",
        "continental_union",
        "world_region",
        "org",
    }
)


class ResolvekitAdapter:
    spec: ClassVar[ToolSpec] = ToolSpec(
        name="resolvekit",
        distribution="resolvekit",
        offline=True,
        entity_types=_GEO_ENTITY_TYPES,
        supports_calibration=True,
    )

    def __init__(
        self,
        *,
        modules: list[str] | None = None,
        pass_hints: bool = False,
    ) -> None:
        self._modules = modules
        self._pass_hints = pass_hints
        self._resolver: Any | None = None
        self._status_enum: Any | None = None

    def warmup(self) -> None:
        from resolvekit import Resolver
        from resolvekit.types import ResolutionStatus

        self._status_enum = ResolutionStatus
        self._resolver = (
            Resolver.from_modules(module_ids=self._modules)
            if self._modules is not None
            else Resolver.auto()
        )
        self._resolver.resolve("United States")

    def resolve(self, query: Query) -> Response:
        if self._resolver is None or self._status_enum is None:
            self.warmup()
        assert self._resolver is not None
        assert self._status_enum is not None

        context = None
        if self._pass_hints:
            from resolvekit.core.model import ResolutionContext

            internal_type = _ENTITY_TYPE_MAP.get(query.entity_type)
            context = ResolutionContext(
                languages=[query.language],
                # Only pass entity_types when we have a known mapping; passing an
                # unmapped type would cause the TypeConstraint to reject all candidates.
                entity_types=frozenset({internal_type}) if internal_type else None,
            )

        try:
            result = self._resolver.resolve(query.text, context=context)
        except Exception as exc:
            return Response(status="error", error=repr(exc))
        status = result.status
        if status == self._status_enum.RESOLVED and result.entity_id:
            best = getattr(result, "best_candidate", None)
            canonical = getattr(best, "canonical_name", None) if best else None
            return Response(
                status="match",
                match_ids=(result.entity_id,),
                canonical_name=canonical,
                confidence=result.confidence,
            )
        if status == self._status_enum.AMBIGUOUS:
            ids = tuple(c.entity_id for c in result.candidates if c.entity_id)
            return Response(
                status="ambiguous",
                match_ids=ids,
            )
        return Response(status="no_match")

    def version(self) -> str | None:
        return _pkg_version(self.spec.distribution)


class ResolvekitTypedAdapter(ResolvekitAdapter):
    """resolvekit adapter with entity_type + language hints from the dataset row."""

    spec: ClassVar[ToolSpec] = ToolSpec(
        name="resolvekit_typed",
        distribution="resolvekit",
        offline=True,
        entity_types=_GEO_ENTITY_TYPES,
        supports_calibration=True,
    )

    def __init__(self, *, modules: list[str] | None = None) -> None:
        super().__init__(modules=modules, pass_hints=True)
