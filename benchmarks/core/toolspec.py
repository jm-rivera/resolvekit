"""Tool specification and registry.

``ToolSpec`` is the single source of truth for a tool's identity — name,
distribution package, and entity-type coverage. Each adapter class carries
``spec: ClassVar[ToolSpec]``. ``tool_registry()`` returns an explicit list of
all known adapter classes; add new adapters to that list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from benchmarks.tools.protocol import ResolverAdapter


@dataclass(frozen=True)
class ToolSpec:
    """Identity + coverage declaration for one benchmark adapter."""

    name: str
    distribution: str
    offline: bool
    entity_types: frozenset[str]
    # When True, calibration metrics (ECE, Brier score) are computed for this
    # tool. Only meaningful for tools that emit a confidence score; set False
    # for tools that return a fixed or absent confidence.
    supports_calibration: bool = False


def tool_registry() -> dict[str, type[ResolverAdapter]]:
    """Return a mapping of tool name → adapter class, keyed by ``cls.spec.name``."""
    from benchmarks.tools.country_converter import CountryConverterAdapter
    from benchmarks.tools.countryguess import CountryguessAdapter
    from benchmarks.tools.data_commons import DataCommonsAdapter
    from benchmarks.tools.geonamescache import GeonamescacheAdapter
    from benchmarks.tools.hdx import HdxAdapter
    from benchmarks.tools.pycountry import PycountryAdapter
    from benchmarks.tools.rapidfuzz_dict import RapidfuzzDictAdapter
    from benchmarks.tools.resolvekit import ResolvekitAdapter, ResolvekitTypedAdapter

    # ror_affiliation is excluded from the active comparative set: its output uses
    # the ror/ ID namespace which is not present in any committed dataset's expected_ids,
    # so it structurally cannot score correct answers. The module (benchmarks/tools/ror.py)
    # is kept in place; re-add the import below when a ror/-prefixed dataset ships.
    classes: list[type[ResolverAdapter]] = [
        ResolvekitAdapter,
        ResolvekitTypedAdapter,
        PycountryAdapter,
        CountryConverterAdapter,
        CountryguessAdapter,
        HdxAdapter,
        GeonamescacheAdapter,
        RapidfuzzDictAdapter,
        DataCommonsAdapter,
    ]
    return {cls.spec.name: cls for cls in classes}
