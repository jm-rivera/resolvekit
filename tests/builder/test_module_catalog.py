"""Tests for module_catalog distribution strategy dispatch."""

from resolvekit.builder.module_catalog import (
    REMOTE_MODULE_IDS,
    DistributionStrategy,
    module_entry,
)


def test_geo_cities_is_remote() -> None:
    """geo.cities is in the manually-curated remote set."""
    assert module_entry("geo.cities").distribution is DistributionStrategy.REMOTE


def test_geo_countries_is_bundled() -> None:
    """geo.countries is not in the remote set — should be bundled."""
    assert module_entry("geo.countries").distribution is DistributionStrategy.BUNDLED


def test_remote_module_ids_is_public_frozenset() -> None:
    """REMOTE_MODULE_IDS is exported as a frozenset (not underscore-private)."""
    assert isinstance(REMOTE_MODULE_IDS, frozenset)
    assert "geo.cities" in REMOTE_MODULE_IDS


def test_old_constants_absent() -> None:
    """REMOTE_SIZE_CUTOFF_BYTES and _REMOTE_MODULE_IDS must not exist on the module."""
    import resolvekit.builder.module_catalog as m

    assert not hasattr(m, "REMOTE_SIZE_CUTOFF_BYTES")
    assert not hasattr(m, "_REMOTE_MODULE_IDS")
