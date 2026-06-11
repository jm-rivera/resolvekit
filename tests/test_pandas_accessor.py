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


# ---------------------------------------------------------------------------
# on_error propagation: caller mistakes must raise, not silently produce Nones
# ---------------------------------------------------------------------------


def test_resolve_bad_to_raises_unknown_code_system():
    """resolve(to='iso33') must raise UnknownCodeSystemError, not all-None."""
    import resolvekit.pandas  # noqa: F401
    from resolvekit.core.errors import UnknownCodeSystemError

    s = pd.Series(["France"])
    with pytest.raises(UnknownCodeSystemError):
        s.resolvekit.resolve(to="iso33")


def test_resolve_bad_domain_raises_unknown_domain():
    """resolve(domain='bad_xyz') must raise UnknownDomainError, not all-None."""
    import resolvekit.pandas  # noqa: F401
    from resolvekit.core.errors import UnknownDomainError

    s = pd.Series(["France"])
    with pytest.raises(UnknownDomainError):
        s.resolvekit.resolve(to="iso3", domain="bad_xyz")


def test_resolve_bad_on_ambiguous_raises_value_error():
    """resolve(on_ambiguous='typo') must raise ValueError for invalid param."""
    import resolvekit.pandas  # noqa: F401

    s = pd.Series(["France"])
    with pytest.raises(ValueError, match="on_ambiguous="):
        s.resolvekit.resolve(to="iso3", on_ambiguous="typo")


def test_resolve_valid_call_still_works():
    """resolve(to='iso3') with valid args must return correct codes."""
    import resolvekit.pandas  # noqa: F401

    s = pd.Series(["France", "Germany"])
    result = s.resolvekit.resolve(to="iso3")
    assert isinstance(result, pd.Series)
    assert result.tolist() == ["FRA", "DEU"]


def test_resolve_on_error_null_returns_none_rows():
    """resolve(on_error='null') must suppress per-row errors and return None."""
    import resolvekit.pandas  # noqa: F401

    s = pd.Series(["France"])
    result = s.resolvekit.resolve(to="iso3", from_system="bad_sys", on_error="null")
    assert isinstance(result, pd.Series)
    assert result.tolist() == [None]


def test_bulk_on_error_default_is_raise():
    """bulk() must default on_error='raise', not 'null'."""
    import resolvekit.pandas  # noqa: F401
    from resolvekit.core.errors import UnknownCodeSystemError

    s = pd.Series(["France"])
    with pytest.raises(UnknownCodeSystemError):
        s.resolvekit.bulk(to="iso33")
