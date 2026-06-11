"""Benchmark adapters.

Every competitor tool has its own adapter module in this package. Each
adapter implements the ResolverAdapter Protocol defined in ``protocol``
and returns a ``Response`` from ``resolve()``.
"""

from __future__ import annotations

from benchmarks.tools.country_converter import CountryConverterAdapter
from benchmarks.tools.countryguess import CountryguessAdapter
from benchmarks.tools.data_commons import DataCommonsAdapter
from benchmarks.tools.geonamescache import GeonamescacheAdapter
from benchmarks.tools.hdx import HdxAdapter
from benchmarks.tools.jsoncache import JsonCache
from benchmarks.tools.protocol import ResolverAdapter
from benchmarks.tools.pycountry import PycountryAdapter
from benchmarks.tools.rapidfuzz_dict import RapidfuzzDictAdapter
from benchmarks.tools.resolvekit import (
    ResolvekitAdapter,
    ResolvekitTypedAdapter,
)
from benchmarks.tools.ror import RorAdapter

__all__ = [
    "CountryConverterAdapter",
    "CountryguessAdapter",
    "DataCommonsAdapter",
    "GeonamescacheAdapter",
    "HdxAdapter",
    "JsonCache",
    "PycountryAdapter",
    "RapidfuzzDictAdapter",
    "ResolvekitAdapter",
    "ResolvekitTypedAdapter",
    "ResolverAdapter",
    "RorAdapter",
]
