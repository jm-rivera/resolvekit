"""Tests for the opt-in polars accessor.

Verifies:
- The ``resolvekit`` namespace is not available before ``import resolvekit.polars``.
- After the import, the namespace is registered and ``translate()`` is present.
- Registration is idempotent.
"""

from __future__ import annotations

import sys

import pytest

pl = pytest.importorskip("polars")


# ---------------------------------------------------------------------------
# Before opt-in: namespace must NOT be available
# ---------------------------------------------------------------------------


def test_namespace_not_available_before_import():
    """pl.Expr.resolvekit should not exist before import resolvekit.polars."""
    if (
        "resolvekit.polars" in sys.modules
        or "resolvekit._polars_integration" in sys.modules
    ):
        from resolvekit._polars_integration import _REGISTERED

        assert _REGISTERED
        pytest.skip("namespace already registered from a previous test")

    expr = pl.col("country")
    with pytest.raises(AttributeError):
        _ = expr.resolvekit  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# After opt-in: namespace is available
# ---------------------------------------------------------------------------


def test_namespace_available_after_import():
    """After ``import resolvekit.polars``, the namespace must be available."""
    import resolvekit.polars  # noqa: F401

    expr = pl.col("country")
    ns = expr.resolvekit
    assert ns is not None


# ---------------------------------------------------------------------------
# resolve() method exists
# ---------------------------------------------------------------------------


def test_namespace_has_resolve():
    import resolvekit.polars  # noqa: F401

    expr = pl.col("country")
    assert hasattr(expr.resolvekit, "resolve")


# ---------------------------------------------------------------------------
# Registration is idempotent
# ---------------------------------------------------------------------------


def test_register_idempotent():
    from resolvekit._polars_integration import register

    register()
    register()  # second call must be safe

    expr = pl.col("country")
    ns = expr.resolvekit
    assert ns is not None


# ---------------------------------------------------------------------------
# resolve() produces an Expr
# ---------------------------------------------------------------------------


def test_resolve_returns_expr():
    import resolvekit.polars  # noqa: F401

    expr = pl.col("country").resolvekit.resolve(to="iso3")
    assert isinstance(expr, pl.Expr)
