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


# ---------------------------------------------------------------------------
# on_error propagation: caller mistakes must raise, not silently produce Nones
# ---------------------------------------------------------------------------


def test_resolve_valid_call_returns_string_column():
    """resolve(to='iso3') with valid args must return correct codes as strings."""
    import resolvekit.polars  # noqa: F401

    df = pl.DataFrame({"country": ["France", "Germany", None]})
    result = df.with_columns(
        pl.col("country").resolvekit.resolve(to="iso3").alias("iso3")
    )
    assert result["iso3"].to_list() == ["FRA", "DEU", None]


def test_resolve_bad_to_raises_unknown_code_system():
    """resolve(to='iso33') must raise UnknownCodeSystemError, not all-None."""
    import resolvekit.polars  # noqa: F401
    from resolvekit.core.errors import UnknownCodeSystemError

    df = pl.DataFrame({"country": ["France"]})
    with pytest.raises(UnknownCodeSystemError):
        df.with_columns(pl.col("country").resolvekit.resolve(to="iso33").alias("out"))


def test_resolve_bad_domain_raises_unknown_domain():
    """resolve(domain='bad_xyz') must raise UnknownDomainError, not all-None."""
    import resolvekit.polars  # noqa: F401
    from resolvekit.core.errors import UnknownDomainError

    df = pl.DataFrame({"country": ["France"]})
    with pytest.raises(UnknownDomainError):
        df.with_columns(
            pl.col("country").resolvekit.resolve(to="iso3", domain="bad_xyz").alias("out")
        )


def test_resolve_bad_on_ambiguous_raises_value_error():
    """resolve(on_ambiguous='typo') must raise ValueError for invalid param."""
    import resolvekit.polars  # noqa: F401

    df = pl.DataFrame({"country": ["France"]})
    with pytest.raises(ValueError, match="on_ambiguous="):
        df.with_columns(
            pl.col("country").resolvekit.resolve(to="iso3", on_ambiguous="typo").alias("out")
        )


def test_resolve_on_error_null_returns_none_rows():
    """resolve(on_error='null') must suppress per-row errors and return None."""
    import resolvekit.polars  # noqa: F401

    df = pl.DataFrame({"country": ["France"]})
    result = df.with_columns(
        pl.col("country")
        .resolvekit.resolve(to="iso3", from_system="bad_sys", on_error="null")
        .alias("out")
    )
    assert result["out"].to_list() == [None]


def test_resolve_on_error_default_is_raise():
    """resolve() must default on_error='raise', not 'null'."""
    import resolvekit.polars  # noqa: F401
    from resolvekit.core.errors import UnknownCodeSystemError

    df = pl.DataFrame({"country": ["France"]})
    with pytest.raises(UnknownCodeSystemError):
        df.with_columns(
            pl.col("country").resolvekit.resolve(to="iso33").alias("out")
        )
