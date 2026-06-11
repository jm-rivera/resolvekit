"""Tests for Resolver.info typed property.

Verifies that ``Resolver.info`` returns a ``ResolverInfo`` typed object
(not a dict), that subscript access raises ``TypeError``, and that the
property's HTML rendering works.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from resolvekit.core.api.info import ResolverInfo
from resolvekit.core.api.resolver import Resolver

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_resolver(cache_size: int = 0) -> Resolver:
    """Return a minimal Resolver backed by a mock runner."""
    runner = MagicMock()
    runner.available_packs = frozenset({"geo"})
    return Resolver(runner=runner, cache_size=cache_size)


# ---------------------------------------------------------------------------
# Core contract: info is a property, not a method
# ---------------------------------------------------------------------------


def test_resolver_info_is_property() -> None:
    """``resolver.info`` is a property returning ``ResolverInfo``."""
    r = _make_resolver()
    info = r.info
    assert isinstance(info, ResolverInfo)


def test_resolver_info_not_callable() -> None:
    """``resolver.info()`` must raise ``TypeError`` — it is not a method."""
    r = _make_resolver()
    with pytest.raises(TypeError):
        r.info()  # type: ignore[operator]  # ty: ignore[call-non-callable]


def test_resolver_info_subscript_raises() -> None:
    """``resolver.info["data_version"]`` must raise ``TypeError``."""
    r = _make_resolver()
    info = r.info
    with pytest.raises(TypeError):
        _ = info["data_version"]  # type: ignore[index]  # ty: ignore[not-subscriptable]


# ---------------------------------------------------------------------------
# Field access
# ---------------------------------------------------------------------------


def test_resolver_info_has_expected_fields() -> None:
    """``ResolverInfo`` exposes the documented attribute set."""
    r = _make_resolver()
    info = r.info
    assert hasattr(info, "domains")
    assert hasattr(info, "routing_mode")
    assert hasattr(info, "max_query_length")
    assert hasattr(info, "closed")
    assert hasattr(info, "resolvekit_version")
    assert hasattr(info, "data_versions")
    assert hasattr(info, "data_version")
    assert hasattr(info, "cache")
    assert hasattr(info, "modules")


def test_resolver_info_domains_is_tuple() -> None:
    """``info.domains`` is a tuple (not a list)."""
    r = _make_resolver()
    assert isinstance(r.info.domains, tuple)


def test_resolver_info_closed_reflects_state() -> None:
    """``info.closed`` tracks resolver state."""
    r = _make_resolver()
    assert r.info.closed is False
    r.close()
    assert r.info.closed is True


def test_resolver_info_cache_is_none_when_disabled() -> None:
    """``info.cache`` is ``None`` when ``cache_size=0``."""
    r = _make_resolver(cache_size=0)
    assert r.info.cache is None


def test_resolver_info_cache_has_stats_when_enabled() -> None:
    """``info.cache`` is a ``CacheInfo`` when the cache is active."""
    from resolvekit.core.api.cache import CacheInfo

    r = _make_resolver(cache_size=64)
    assert isinstance(r.info.cache, CacheInfo)


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------


def test_resolver_info_repr_html_returns_string() -> None:
    """``info._repr_html_()`` returns an HTML string."""
    r = _make_resolver()
    html = r.info._repr_html_()
    assert isinstance(html, str)
    assert "<table" in html


def test_resolver_info_repr_contains_version() -> None:
    """The HTML representation includes resolvekit_version."""
    r = _make_resolver()
    html = r.info._repr_html_()
    assert "resolvekit_version" in html


# ---------------------------------------------------------------------------
# Repr
# ---------------------------------------------------------------------------


def test_resolver_info_repr() -> None:
    """``repr(info)`` includes domains and routing_mode."""
    r = _make_resolver()
    rep = repr(r.info)
    assert "ResolverInfo" in rep
    assert "routing_mode" in rep


# ---------------------------------------------------------------------------
# build_resolver_info unit test (no Resolver needed)
# ---------------------------------------------------------------------------


def test_build_resolver_info_without_resolver() -> None:
    """``build_resolver_info`` assembles a ``ResolverInfo`` from plain dicts."""
    from unittest.mock import MagicMock

    from resolvekit.core.api.info import ResolverInfo, build_resolver_info

    # Build a fake LoadedDataPack-like object.
    fake_module = MagicMock()
    fake_module.module_id = "geo.countries"
    fake_module.metadata.datapack_id = "geo.countries-v1"
    fake_module.metadata.data_version = "2024.01"
    fake_module.metadata.build_timestamp = "2024-01-01T00:00:00Z"

    info = build_resolver_info(
        domains=("geo",),
        routing_mode="auto",
        max_query_length=1000,
        closed=False,
        resolvekit_version="0.1.0",
        loaded_modules={"geo": [fake_module]},
        data_version="2024.01",
        cache_info=None,
        modules_catalog=(),
    )

    assert isinstance(info, ResolverInfo)
    assert info.domains == ("geo",)
    assert info.routing_mode == "auto"
    assert info.data_version == "2024.01"
    assert info.cache is None
    # data_versions should reflect the fake module.
    assert "geo" in info.data_versions
    assert "geo.countries" in info.data_versions["geo"]
    assert info.data_versions["geo"]["geo.countries"]["data_version"] == "2024.01"
