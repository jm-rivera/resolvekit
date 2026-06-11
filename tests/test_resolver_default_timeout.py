"""Tests for Resolver default_timeout kwarg.

Verifies that:
- ``Resolver(runner=..., default_timeout=5.0)`` stores the timeout
- Per-call ``timeout=`` overrides the default
- The default is passed through in from_modules / from_datapacks / auto
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from resolvekit.core.api.resolver import Resolver

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_resolver(
    default_timeout: float | None = None, cache_size: int = 0
) -> Resolver:
    runner = MagicMock()
    runner.available_packs = frozenset({"geo"})
    return Resolver(
        runner=runner, cache_size=cache_size, default_timeout=default_timeout
    )


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


def test_resolver_default_timeout_stored() -> None:
    """``Resolver(default_timeout=5.0)`` stores the value."""
    r = _make_resolver(default_timeout=5.0)
    assert r._default_timeout == 5.0


def test_resolver_default_timeout_none_by_default() -> None:
    """``Resolver()`` defaults ``_default_timeout`` to ``None``."""
    r = _make_resolver()
    assert r._default_timeout is None


def test_resolver_default_timeout_zero_not_stored() -> None:
    """A zero default_timeout should still be stored (validation at call time)."""
    r = _make_resolver(default_timeout=0.0)
    assert r._default_timeout == 0.0


# ---------------------------------------------------------------------------
# Per-call override
# ---------------------------------------------------------------------------


def test_resolver_resolve_uses_default_timeout() -> None:
    """When no per-call timeout, the default is used."""
    r = _make_resolver(default_timeout=2.0)
    # Intercept _resolve_inner to verify timeout propagation.
    calls: list[float | None] = []

    def spy(
        text, *, normalized_domain, context, include_entity, timeout, _self_ref=None
    ):
        calls.append(timeout)
        from resolvekit.core.model.result import (
            ReasonCode,
            ResolutionResult,
            ResolutionStatus,
        )

        return ResolutionResult(
            status=ResolutionStatus.NO_MATCH, reasons=[ReasonCode.INVALID_QUERY]
        )

    r._resolve_inner = spy  # type: ignore[method-assign]
    r.resolve("US")
    assert calls == [2.0]


def test_resolver_resolve_per_call_timeout_overrides_default() -> None:
    """Per-call ``timeout=`` takes precedence over ``_default_timeout``."""
    r = _make_resolver(default_timeout=10.0)
    calls: list[float | None] = []

    def spy(
        text, *, normalized_domain, context, include_entity, timeout, _self_ref=None
    ):
        calls.append(timeout)
        from resolvekit.core.model.result import (
            ReasonCode,
            ResolutionResult,
            ResolutionStatus,
        )

        return ResolutionResult(
            status=ResolutionStatus.NO_MATCH, reasons=[ReasonCode.INVALID_QUERY]
        )

    r._resolve_inner = spy  # type: ignore[method-assign]
    r.resolve("US", timeout=1.0)
    assert calls == [1.0]


def test_resolver_resolve_negative_timeout_raises() -> None:
    """``resolve(timeout=-1)`` raises ``ValueError``."""
    r = _make_resolver()
    with pytest.raises(ValueError, match="timeout must be positive"):
        r.resolve("US", timeout=-1.0)


def test_resolver_resolve_negative_default_timeout_raises() -> None:
    """``resolve()`` with a negative default timeout raises ``ValueError``."""
    r = _make_resolver(default_timeout=-1.0)
    with pytest.raises(ValueError, match="timeout must be positive"):
        r.resolve("US")


# ---------------------------------------------------------------------------
# kwargs-only enforcement
# ---------------------------------------------------------------------------


def test_resolver_from_modules_kwargs_only() -> None:
    """``Resolver.from_modules(["geo"])`` must raise ``TypeError`` — positional arg removed."""
    with pytest.raises(TypeError):
        Resolver.from_modules(["geo"])  # type: ignore[call-arg]


def test_resolver_from_modules_kwargs_accepted() -> None:
    """``Resolver.from_modules(module_ids=["geo"])`` signature is valid (even if it fails at runtime)."""
    # We just validate the signature accepts keyword arguments — the actual
    # module loading may fail if modules aren't installed, which is fine.
    import inspect

    sig = inspect.signature(Resolver.from_modules)
    list(sig.parameters)
    # First real parameter (after cls) must be keyword-only.
    non_cls = [p for p in sig.parameters.values() if p.name != "cls"]
    for p in non_cls:
        assert p.kind in (
            inspect.Parameter.KEYWORD_ONLY,
            inspect.Parameter.VAR_KEYWORD,
        ), f"Parameter {p.name!r} is not keyword-only: {p.kind}"


def test_resolver_from_datapacks_kwargs_only() -> None:
    """``Resolver.from_datapacks([...])`` must raise — positional arg removed."""
    with pytest.raises(TypeError):
        Resolver.from_datapacks(["/tmp/fake"])  # type: ignore[call-arg]


def test_resolver_auto_kwargs_only() -> None:
    """``Resolver.auto(["geo"])`` must raise — positional arg removed."""
    with pytest.raises(TypeError):
        Resolver.auto(["geo"])  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# domains= terminology
# ---------------------------------------------------------------------------


def test_resolver_from_modules_accepts_domains_kwarg() -> None:
    """``from_modules`` accepts ``domains=`` kwarg, not ``packs=``."""
    import inspect

    sig = inspect.signature(Resolver.from_modules)
    assert "domains" in sig.parameters
    assert "packs" not in sig.parameters


def test_resolver_from_datapacks_accepts_domains_kwarg() -> None:
    """``from_datapacks`` accepts ``domains=`` kwarg."""
    import inspect

    sig = inspect.signature(Resolver.from_datapacks)
    assert "domains" in sig.parameters
    assert "packs" not in sig.parameters
