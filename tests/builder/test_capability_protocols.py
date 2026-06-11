"""Tests for A4 capability-protocol honesty: spec flags, adapter predicates, helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from resolvekit.builder.sources.datacommons.adapter import (
    DataCommonsSourceAdapter,
    DomainAdapterConfig,
)
from resolvekit.builder.sources.datacommons.geo.adapter import (
    DataCommonsGeoSourceAdapter,
)
from resolvekit.builder.sources.datacommons.specs import DataCommonsDomainSpec
from resolvekit.builder.sources.protocol import (
    IncrementalFilteredDiscoveryAdapter,
    adapter_supports_filtered_discovery,
    adapter_supports_inspection,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_spec(**overrides: bool) -> DataCommonsDomainSpec:
    """Build a minimal DataCommonsDomainSpec for testing capability flags."""
    defaults: dict = {
        "domain": "test",
        "profile": MagicMock(),
        "discover_entities": MagicMock(),
        "discover_entities_filtered": MagicMock(),
        "collect_discovered_entity_facts": MagicMock(),
    }
    defaults.update(overrides)
    return DataCommonsDomainSpec(**defaults)


def _make_adapter(spec: DataCommonsDomainSpec) -> DataCommonsSourceAdapter:
    """Wrap a spec in a minimal DataCommonsSourceAdapter (no real DC calls)."""
    config = DomainAdapterConfig(
        domain_spec=spec,
        dc_api_factory=MagicMock(return_value=MagicMock()),
        fetch_raw_chunk_fn=MagicMock(),
        filter_entities_fn=MagicMock(),
    )
    return DataCommonsSourceAdapter(config)


# ---------------------------------------------------------------------------
# Default spec — both capabilities enabled
# ---------------------------------------------------------------------------


def test_default_spec_supports_filtered_discovery() -> None:
    """DataCommonsDomainSpec defaults supports_filtered_discovery to True."""
    spec = _make_spec()
    assert spec.supports_filtered_discovery is True


def test_default_spec_supports_inspection() -> None:
    """DataCommonsDomainSpec defaults supports_inspection to True."""
    spec = _make_spec()
    assert spec.supports_inspection is True


def test_adapter_supports_filtered_discovery_default_true() -> None:
    """adapter_supports_filtered_discovery returns True for a default-spec adapter."""
    adapter = _make_adapter(_make_spec())
    assert adapter_supports_filtered_discovery(adapter) is True


def test_adapter_supports_inspection_default_true() -> None:
    """adapter_supports_inspection returns True for a default-spec adapter."""
    adapter = _make_adapter(_make_spec())
    assert adapter_supports_inspection(adapter) is True


# ---------------------------------------------------------------------------
# Spec with supports_filtered_discovery=False
# ---------------------------------------------------------------------------


def test_spec_with_filtered_discovery_disabled() -> None:
    """supports_filtered_discovery=False propagates to adapter predicate."""
    adapter = _make_adapter(_make_spec(supports_filtered_discovery=False))
    assert adapter.supports_filtered_discovery() is False
    assert adapter_supports_filtered_discovery(adapter) is False


def test_discover_entities_filtered_raises_when_disabled() -> None:
    """discover_entities_filtered raises NotImplementedError when flag is False."""
    adapter = _make_adapter(_make_spec(supports_filtered_discovery=False))
    with pytest.raises(NotImplementedError):
        adapter.discover_entities_filtered("test", ["SomeType"], False)


# ---------------------------------------------------------------------------
# Spec with supports_inspection=False
# ---------------------------------------------------------------------------


def test_spec_with_inspection_disabled() -> None:
    """supports_inspection=False propagates to adapter predicate."""
    adapter = _make_adapter(_make_spec(supports_inspection=False))
    assert adapter.supports_inspection() is False
    assert adapter_supports_inspection(adapter) is False


def test_inspect_domain_raises_when_disabled() -> None:
    """inspect_domain raises NotImplementedError when flag is False."""
    adapter = _make_adapter(_make_spec(supports_inspection=False))
    with pytest.raises(NotImplementedError):
        adapter.inspect_domain(
            "test",
            include_entity_types=["SomeType"],
            include_relation_targets=False,
        )


# ---------------------------------------------------------------------------
# Structural fallback for non-DC adapters (v0.x)
# ---------------------------------------------------------------------------


def test_structural_fallback_filtered_discovery_present() -> None:
    """hasattr fallback returns True when discover_entities_filtered exists."""

    class LegacyAdapter:
        def discover_entities_filtered(self, *_a, **_kw): ...

    assert adapter_supports_filtered_discovery(LegacyAdapter()) is True


def test_structural_fallback_filtered_discovery_absent() -> None:
    """hasattr fallback returns False when discover_entities_filtered is absent."""

    class MinimalAdapter:
        pass

    assert adapter_supports_filtered_discovery(MinimalAdapter()) is False


def test_structural_fallback_inspection_present() -> None:
    """hasattr fallback returns True when inspect_domain exists."""

    class LegacyAdapter:
        def inspect_domain(self, *_a, **_kw): ...

    assert adapter_supports_inspection(LegacyAdapter()) is True


def test_structural_fallback_inspection_absent() -> None:
    """hasattr fallback returns False when inspect_domain is absent."""

    class MinimalAdapter:
        pass

    assert adapter_supports_inspection(MinimalAdapter()) is False


# ---------------------------------------------------------------------------
# IncrementalFilteredDiscoveryAdapter — geo adapter satisfies it (line-210 path)
# ---------------------------------------------------------------------------


def test_geo_adapter_satisfies_incremental_filtered_discovery() -> None:
    """DataCommonsGeoSourceAdapter must satisfy IncrementalFilteredDiscoveryAdapter."""
    geo = DataCommonsGeoSourceAdapter()
    assert isinstance(geo, IncrementalFilteredDiscoveryAdapter)
