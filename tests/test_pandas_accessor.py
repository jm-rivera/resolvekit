"""Tests for the opt-in pandas accessor.

Verifies:
- Accessing ``.resolvekit`` before ``import resolvekit.pandas`` raises
  ``AttributeError``.
- After the import, the accessor is registered and ``resolve()`` works.
- Registration is idempotent (calling ``register()`` twice is safe).
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

pd = pytest.importorskip("pandas")


# ---------------------------------------------------------------------------
# Before opt-in: accessor must NOT be available
# ---------------------------------------------------------------------------


def test_accessor_not_available_before_import():
    """pd.Series.resolvekit should not exist before import resolvekit.pandas."""
    # Ensure the accessor is not already registered from a prior test.
    # We can't fully un-register it once registered, so we skip this test
    # if the integration module has already been imported.
    if (
        "resolvekit.pandas" in sys.modules
        or "resolvekit._pandas_integration" in sys.modules
    ):
        # Already registered in a prior test run — check idempotency instead.
        from resolvekit._pandas_integration import _REGISTERED

        assert _REGISTERED
        pytest.skip("accessor already registered from a previous test")

    s = pd.Series(["US", "DE"])
    with pytest.raises(AttributeError):
        _ = s.resolvekit  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# After opt-in: accessor is available
# ---------------------------------------------------------------------------


def test_accessor_available_after_import():
    """After ``import resolvekit.pandas``, the accessor must be available."""
    import resolvekit.pandas  # noqa: F401

    s = pd.Series(["US"])
    # Should not raise; accessor object is constructed
    acc = s.resolvekit
    assert acc is not None


# ---------------------------------------------------------------------------
# resolve() method calls bulk dispatch
# ---------------------------------------------------------------------------


def test_accessor_resolve_calls_bulk_dispatch():
    """resolve(to='iso3') should call _bulk_dispatch with to='iso3'."""
    import resolvekit.pandas  # noqa: F401

    with patch("resolvekit.core.api.bulk._bulk_dispatch") as mock_dispatch:
        mock_dispatch.return_value = pd.Series(["USA"])
        s = pd.Series(["US"])
        s.resolvekit.resolve(to="iso3")
        mock_dispatch.assert_called_once()
        kwargs = mock_dispatch.call_args.kwargs
        assert kwargs["to"] == "iso3"
        assert "resolver" in kwargs


# ---------------------------------------------------------------------------
# Registration is idempotent
# ---------------------------------------------------------------------------


def test_register_idempotent():
    from resolvekit._pandas_integration import register

    register()  # first call
    register()  # second call — should not raise or duplicate

    # The accessor should still work normally
    s = pd.Series(["US"])
    acc = s.resolvekit
    assert acc is not None


# ---------------------------------------------------------------------------
# bulk() method is available on accessor
# ---------------------------------------------------------------------------


def test_accessor_bulk_method_exists():
    import resolvekit.pandas  # noqa: F401

    s = pd.Series(["US"])
    acc = s.resolvekit
    assert hasattr(acc, "bulk")
