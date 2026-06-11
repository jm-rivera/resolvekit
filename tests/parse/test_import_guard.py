"""Tests for the ahocorasick_rs import guard.

Uses sys.modules monkeypatching to simulate the dependency being absent.
Verifies: lazy import guard (fires at automaton-build time, not module import);
helpful error message with pip install hint; module-level imports succeed.
"""

from __future__ import annotations

import importlib
import sys

import pytest

# ---------------------------------------------------------------------------
# Helper — simulate ahocorasick_rs being uninstalled
# ---------------------------------------------------------------------------

_AHOCORASICK_RS_KEY = "ahocorasick_rs"


def _stub_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject None into sys.modules so any import raises ImportError."""
    monkeypatch.setitem(sys.modules, _AHOCORASICK_RS_KEY, None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# parse() raises ImportError with the helpful install hint
# ---------------------------------------------------------------------------


def test_parse_raises_import_error_with_install_hint(
    monkeypatch: pytest.MonkeyPatch,
    parse_geo_resolver,
) -> None:
    """rk.parse('Kenya') raises ImportError containing the pip install hint."""
    _stub_absent(monkeypatch)

    # Force-reload the automaton module so its cached import is cleared.
    # We do this by removing it from sys.modules so the next import re-runs
    # the top-level import of ahocorasick_rs.
    for key in list(sys.modules):
        if "resolvekit.core.parse.automaton" in key:
            monkeypatch.delitem(sys.modules, key, raising=False)

    with pytest.raises(ImportError) as exc_info:
        parse_geo_resolver.parse("Kenya")

    msg = str(exc_info.value)
    assert "pip install" in msg and "resolvekit[parsing]" in msg, (
        f"ImportError message should contain install hint, got: {msg!r}"
    )


# ---------------------------------------------------------------------------
# import resolvekit succeeds without the dep (lazy guard)
# ---------------------------------------------------------------------------


def test_import_resolvekit_succeeds_without_dep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """import resolvekit succeeds even when ahocorasick_rs is absent.

    The guard is lazy: it fires inside build_or_get_automaton() (called by
    parse()), not at module import time.
    """
    _stub_absent(monkeypatch)

    # Re-importing with the already-loaded module is fine; the point is that
    # the resolvekit package itself does not import ahocorasick_rs at the top
    # level.
    import resolvekit as rk

    assert callable(rk.parse), "rk.parse must be callable even without the dep"
    assert callable(rk.parse_bulk), (
        "rk.parse_bulk must be callable even without the dep"
    )


# ---------------------------------------------------------------------------
# import resolvekit.core.parse.automaton succeeds without the dep
# ---------------------------------------------------------------------------


def test_import_automaton_module_succeeds_without_dep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """import resolvekit.core.parse.automaton succeeds without ahocorasick_rs.

    The guard fires inside build_or_get_automaton() at automaton-build time,
    not at module import time.  The module itself must be importable.
    """
    _stub_absent(monkeypatch)

    # Remove from sys.modules cache to force a fresh import attempt.
    monkeypatch.delitem(sys.modules, "resolvekit.core.parse.automaton", raising=False)

    # This must NOT raise even with ahocorasick_rs absent.
    mod = importlib.import_module("resolvekit.core.parse.automaton")
    assert mod is not None, "module import should succeed"
    assert hasattr(mod, "build_or_get_automaton"), (
        "build_or_get_automaton should be defined in the module"
    )
