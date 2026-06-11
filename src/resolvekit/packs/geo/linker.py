"""Geo-specific linker for overlay composition."""

from resolvekit.core.linking import BaseLinker


class GeoLinker(BaseLinker):
    """Linker for geo domain entities.

    Understands dcid, iso3, iso2, geonameid code systems.
    """

    KNOWN_CODE_SYSTEMS = frozenset({"dcid", "iso3", "iso2", "geonameid"})
