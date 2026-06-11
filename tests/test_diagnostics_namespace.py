"""Tests for Resolver.diagnostics namespace.

Verifies that:
- ``resolver.diagnostics`` is a cached_property (not a method)
- ``resolver.diagnostics.inspect(...)`` and ``.search(...)`` work
- ``resolver.diagnostics.cache.info()`` and ``.cache.clear()`` work
- Old direct ``resolver.inspect`` / ``resolver.search`` /
  ``resolver.cache_info`` / ``resolver.cache_clear`` attributes do NOT exist
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from resolvekit.core.api.diagnostics import _CacheNamespace, _DiagnosticsNamespace
from resolvekit.core.api.resolver import Resolver

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_resolver(cache_size: int = 64) -> Resolver:
    runner = MagicMock()
    runner.available_packs = frozenset({"geo"})
    return Resolver(runner=runner, cache_size=cache_size)


# ---------------------------------------------------------------------------
# Namespace availability
# ---------------------------------------------------------------------------


def test_resolver_diagnostics_is_namespace() -> None:
    """``resolver.diagnostics`` is a ``_DiagnosticsNamespace``."""
    r = _make_resolver()
    assert isinstance(r.diagnostics, _DiagnosticsNamespace)


def test_resolver_diagnostics_cached_property() -> None:
    """``resolver.diagnostics`` is the same object on repeated access."""
    r = _make_resolver()
    d1 = r.diagnostics
    d2 = r.diagnostics
    assert d1 is d2


def test_resolver_no_inspect_attribute() -> None:
    """``resolver.inspect`` must NOT exist as a top-level method."""
    r = _make_resolver()
    public_methods = {name for name in dir(r) if not name.startswith("_")}
    assert "inspect" not in public_methods


def test_resolver_no_search_attribute() -> None:
    """``resolver.search`` must NOT exist as a top-level public method."""
    r = _make_resolver()
    public_methods = {name for name in dir(r) if not name.startswith("_")}
    assert "search" not in public_methods


def test_resolver_no_cache_info_attribute() -> None:
    """``resolver.cache_info`` must NOT exist as a top-level public method."""
    r = _make_resolver()
    public_methods = {name for name in dir(r) if not name.startswith("_")}
    assert "cache_info" not in public_methods


def test_resolver_no_cache_clear_attribute() -> None:
    """``resolver.cache_clear`` must NOT exist as a top-level public method."""
    r = _make_resolver()
    public_methods = {name for name in dir(r) if not name.startswith("_")}
    assert "cache_clear" not in public_methods


# ---------------------------------------------------------------------------
# cache sub-namespace
# ---------------------------------------------------------------------------


def test_diagnostics_cache_is_namespace() -> None:
    """``resolver.diagnostics.cache`` is a ``_CacheNamespace``."""
    r = _make_resolver()
    assert isinstance(r.diagnostics.cache, _CacheNamespace)


def test_diagnostics_cache_info_returns_cache_info() -> None:
    """``resolver.diagnostics.cache.info()`` returns CacheInfo or None."""
    from resolvekit.core.api.cache import CacheInfo

    r = _make_resolver(cache_size=64)
    info = r.diagnostics.cache.info()
    assert isinstance(info, CacheInfo)


def test_diagnostics_cache_info_none_when_disabled() -> None:
    """``resolver.diagnostics.cache.info()`` is None when cache is off."""
    r = _make_resolver(cache_size=0)
    assert r.diagnostics.cache.info() is None


def test_diagnostics_cache_clear_no_error() -> None:
    """``resolver.diagnostics.cache.clear()`` runs without error."""
    r = _make_resolver(cache_size=64)
    r.diagnostics.cache.clear()  # should not raise


def test_diagnostics_cache_clear_noop_when_disabled() -> None:
    """``resolver.diagnostics.cache.clear()`` is a no-op when cache is off."""
    r = _make_resolver(cache_size=0)
    r.diagnostics.cache.clear()  # must not raise


# ---------------------------------------------------------------------------
# inspect / search delegates
# ---------------------------------------------------------------------------


def test_diagnostics_inspect_delegates() -> None:
    """``resolver.diagnostics.inspect(text)`` calls ``_run_inspection``."""
    r = _make_resolver()
    with patch("resolvekit.core.api.inspect._run_inspection") as mock_inspect:
        mock_inspect.return_value = MagicMock()
        r.diagnostics.inspect("United States")
        mock_inspect.assert_called_once()


def test_diagnostics_search_delegates() -> None:
    """``resolver.diagnostics.search(text)`` calls ``_search_internal``."""
    r = _make_resolver()
    r._search_internal = MagicMock(return_value=[])
    results = r.diagnostics.search("US", top_k=5)
    r._search_internal.assert_called_once_with("US", top_k=5, domain=None, context=None)
    assert results == []


def test_diagnostics_inspect_raises_when_closed() -> None:
    """``diagnostics.inspect()`` raises ``RuntimeError`` after close."""
    r = _make_resolver()
    r.close()
    with pytest.raises(RuntimeError, match="closed"):
        r.diagnostics.inspect("US")


def test_diagnostics_search_raises_when_closed() -> None:
    """``diagnostics.search()`` raises ``RuntimeError`` after close."""
    r = _make_resolver()
    r._closed = True
    with pytest.raises(RuntimeError, match="closed"):
        r.diagnostics.search("US")
