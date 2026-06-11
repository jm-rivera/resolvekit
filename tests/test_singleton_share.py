"""Tests for singleton lifecycle: configure() invalidates the default resolver."""

from __future__ import annotations

from pathlib import Path

import resolvekit
from resolvekit._convenience import reset


def _get_convenience_default() -> object:
    """Read the module-level _default variable directly."""
    import resolvekit._convenience as _c

    return _c._default


class TestSingletonInvalidation:
    def setup_method(self) -> None:
        """Ensure a clean slate before each test."""
        reset()

    def teardown_method(self) -> None:
        """Restore clean state after each test."""
        from resolvekit.core.config import _reset_config

        _reset_config()
        reset()

    def test_default_returns_resolver(self) -> None:
        """default() returns a Resolver instance."""
        from resolvekit.core.api.resolver import Resolver

        r = resolvekit.default()
        assert isinstance(r, Resolver)

    def test_default_is_singleton(self) -> None:
        """Two calls to default() return the same instance."""
        r1 = resolvekit.default()
        r2 = resolvekit.default()
        assert r1 is r2

    def test_configure_invalidates_singleton(self) -> None:
        """configure() discards the cached singleton.

        After configure(), the next call to default() builds a fresh resolver.
        """
        resolvekit.default()
        # configure() should close and discard r1
        resolvekit.configure()
        # The internal _default should be None after configure
        assert _get_convenience_default() is None

    def test_configure_with_cache_dir_rebuilds(self, tmp_path: Path) -> None:
        """configure(cache_dir=...) invalidates and the next call rebuilds."""
        r1 = resolvekit.default()
        resolvekit.configure(cache_dir=tmp_path)
        # After configure, _default is None
        assert _get_convenience_default() is None
        # Accessing default() again triggers a rebuild
        r2 = resolvekit.default()
        from resolvekit.core.api.resolver import Resolver

        assert isinstance(r2, Resolver)
        # It's a new instance
        assert r1 is not r2

    def test_reset_discards_singleton(self) -> None:
        """reset() closes and discards the singleton."""
        resolvekit.default()  # build it
        assert _get_convenience_default() is not None
        resolvekit.reset()
        assert _get_convenience_default() is None

    def test_resolve_after_configure_uses_new_singleton(self, tmp_path: Path) -> None:
        """Module-level resolve() after configure() uses the new resolver."""
        # Prime the singleton
        r_before = resolvekit.default()
        # Reconfigure (no real semantic change needed — just invalidate)
        resolvekit.configure(cache_dir=tmp_path)
        # Next resolve() builds a new singleton
        result = resolvekit.resolve("United States")
        r_after = resolvekit.default()
        assert r_before is not r_after
        assert result is not None
