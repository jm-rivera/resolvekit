"""Tests for the DC geo discovery fix that includes second-level UN M.49 subregions.

The fix extends discover_geo_region_entities so that when raw_type == GeoRegion,
it follows up with get_places_by_parents on the discovered first-level regions to
pick up second-level subregions (e.g. "Western Europe" parented under "Europe").
"""

from unittest.mock import MagicMock

import pytest

from resolvekit.builder.sources.datacommons.geo.mappings import (
    DISCOVERY_MAX_WORKERS,
    DISCOVERY_PARENT_BATCH_SIZE,
    PLACE_TYPE_GEO_REGION,
)


def _make_with_retries():  # type: ignore[no-untyped-def]
    """Return a with_retries shim that just calls the function with its kwargs."""

    def with_retries(fn, **kwargs):  # type: ignore[no-untyped-def]
        return fn(**kwargs)

    return with_retries


@pytest.mark.unit
def test_discover_geo_region_entities_includes_subregions() -> None:
    """Second-level GeoRegion subregions are included when raw_type is GeoRegion."""
    from resolvekit.builder.sources.datacommons.geo._geo_regions import (
        discover_geo_region_entities,
    )

    dc_api = MagicMock()
    # First call: parent-level regions (e.g. Europe, Asia)
    first_level = ["region/Europe", "region/Asia"]
    dc_api.get_places.return_value = first_level
    # Second call via get_places_by_parents: second-level subregions
    dc_api.get_places_by_parents.return_value = {
        "region/Europe": ["region/WesternEurope", "region/NorthernEurope"],
        "region/Asia": ["region/EasternAsia"],
    }

    result = discover_geo_region_entities(
        dc_api=dc_api,
        with_retries=_make_with_retries(),
        raw_type=PLACE_TYPE_GEO_REGION,
    )

    # First-level regions present
    assert "region/Europe" in result
    assert "region/Asia" in result
    # Second-level subregions also present
    assert "region/WesternEurope" in result
    assert "region/NorthernEurope" in result
    assert "region/EasternAsia" in result

    # Verify get_places_by_parents was called exactly once
    dc_api.get_places_by_parents.assert_called_once()
    call_kwargs = dc_api.get_places_by_parents.call_args.kwargs
    assert call_kwargs["place_type"] == PLACE_TYPE_GEO_REGION
    assert set(call_kwargs["parent_places"]) == set(first_level)
    assert call_kwargs["chunk_size"] == DISCOVERY_PARENT_BATCH_SIZE
    assert call_kwargs["max_workers"] == DISCOVERY_MAX_WORKERS


@pytest.mark.unit
def test_discover_geo_region_entities_skips_subregion_call_when_empty() -> None:
    """When first-level discovery returns empty, subregion call is not made."""
    from resolvekit.builder.sources.datacommons.geo._geo_regions import (
        discover_geo_region_entities,
    )

    dc_api = MagicMock()
    dc_api.get_places.return_value = []
    dc_api.get_entities_by_type.return_value = []

    discover_geo_region_entities(
        dc_api=dc_api,
        with_retries=_make_with_retries(),
        raw_type=PLACE_TYPE_GEO_REGION,
    )

    dc_api.get_places_by_parents.assert_not_called()


@pytest.mark.unit
def test_discover_geo_region_entities_non_geo_region_skips_subregion_call() -> None:
    """For non-GeoRegion types, get_places_by_parents is never called."""
    from resolvekit.builder.sources.datacommons.geo._geo_regions import (
        discover_geo_region_entities,
    )

    dc_api = MagicMock()
    dc_api.get_places.return_value = ["region/SomeOtherRegion"]

    discover_geo_region_entities(
        dc_api=dc_api,
        with_retries=_make_with_retries(),
        raw_type="SomeOtherPlaceType",
    )

    dc_api.get_places_by_parents.assert_not_called()
