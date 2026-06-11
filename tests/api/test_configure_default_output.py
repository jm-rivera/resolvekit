"""Integration tests for module-global configure() + to() wiring.

Coverage:
- configure(default_to="iso3") → module-level resolve() returns str, not ResolutionResult
- configure(default_to="name:") → raises UnknownOutputError immediately (grammar validation is eager)
- configure(default_to="iso33") with no prior singleton → does NOT raise at configure time
- configure(default_to="iso33") with a prior singleton → raises at configure time
- _convenience.to("iso3").resolve("United States") == "USA"
- configure(default_to=None) resets → resolve() returns ResolutionResult again
- get_default_to() / get_on_missing() reflect configure(); _reset_config() clears them
- Autouse teardown prevents singleton/config bleed across tests

Note: resolvekit.to() is wired in __init__.py.  Tests here call
_convenience.to directly so the configure suite is self-contained.
"""

from __future__ import annotations

import pytest

import resolvekit
from resolvekit._convenience import to as _module_to
from resolvekit.core.config import _reset_config, get_default_to, get_on_missing
from resolvekit.core.errors import UnknownOutputError
from resolvekit.core.model import ResolutionResult

# ---------------------------------------------------------------------------
# Teardown fixture — prevents singleton/config bleed across tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_after_each() -> None:  # type: ignore[return]
    """Autouse fixture: reset config + singleton after every test."""
    yield
    resolvekit.configure(default_to=None, on_missing="auto")
    resolvekit.reset()


# ---------------------------------------------------------------------------
# configure() sets default output and affects module-level resolve
# ---------------------------------------------------------------------------


class TestConfigureDefaultTo:
    def test_configure_iso3_returns_str(self) -> None:
        """After configure(default_to='iso3'), resolve() returns a str code."""
        resolvekit.configure(default_to="iso3")
        result = resolvekit.resolve("United States")
        assert result == "USA"
        assert isinstance(result, str)

    def test_configure_iso3_not_resolution_result(self) -> None:
        """Module-level resolve returns str, not ResolutionResult, when spec is active."""
        resolvekit.configure(default_to="iso3")
        result = resolvekit.resolve("United States")
        assert not isinstance(result, ResolutionResult)

    def test_configure_none_resets_to_resolution_result(self) -> None:
        """configure(default_to=None) clears spec; resolve() returns ResolutionResult."""
        resolvekit.configure(default_to="iso3")
        resolvekit.configure(default_to=None)
        result = resolvekit.resolve("United States")
        assert isinstance(result, ResolutionResult)
        assert result.entity_id == "country/USA"


# ---------------------------------------------------------------------------
# Eager grammar validation (always immediate, for name: tokens)
# ---------------------------------------------------------------------------


class TestConfigureEagerGrammar:
    def test_malformed_name_grammar_raises_immediately(self) -> None:
        """configure(default_to='name:') raises UnknownOutputError at configure time.

        'name:' has an empty middle segment — malformed grammar caught immediately
        by _validate_grammar_only before any resolver is built.
        """
        with pytest.raises(UnknownOutputError):
            resolvekit.configure(default_to="name:")

    def test_malformed_name_grammar_too_many_parts(self) -> None:
        """configure(default_to='name:fr:Latn:extra') raises immediately."""
        with pytest.raises(UnknownOutputError):
            resolvekit.configure(default_to="name:fr:Latn:extra")

    def test_valid_name_grammar_does_not_raise(self) -> None:
        """configure(default_to='name:fr') is valid grammar and does not raise."""
        resolvekit.configure(default_to="name:fr")

    def test_valid_name_kind_does_not_raise(self) -> None:
        """configure(default_to='name:acronym') is valid grammar and does not raise."""
        resolvekit.configure(default_to="name:acronym")


# ---------------------------------------------------------------------------
# code-system validation — deferred vs. eager depending on singleton
# ---------------------------------------------------------------------------


class TestConfigureCodeValidation:
    def test_unknown_code_no_singleton_defers(self) -> None:
        """configure(default_to='iso33') with no singleton: no raise at configure time."""
        resolvekit.reset()
        # Should NOT raise at configure time — deferred code validation.
        resolvekit.configure(default_to="iso33")

    def test_unknown_code_no_singleton_raises_on_resolve(self) -> None:
        """configure(default_to='iso33') with no singleton: raises on first resolve."""
        resolvekit.reset()
        resolvekit.configure(default_to="iso33")
        with pytest.raises(UnknownOutputError):
            resolvekit.resolve("United States")

    def test_unknown_code_with_singleton_raises_at_configure_time(self) -> None:
        """configure(default_to='iso33') with a prior singleton raises immediately."""
        # Force singleton to exist by resolving.
        resolvekit.resolve("France")
        # Now configure with an unknown code system — should raise immediately.
        with pytest.raises(UnknownOutputError):
            resolvekit.configure(default_to="iso33")

    def test_valid_code_with_singleton_does_not_raise(self) -> None:
        """configure(default_to='iso3') with a prior singleton does not raise."""
        resolvekit.resolve("France")
        # iso3 is valid — should not raise.
        resolvekit.configure(default_to="iso3")


# ---------------------------------------------------------------------------
# module-level to() convenience (called via _convenience module)
# ---------------------------------------------------------------------------


class TestModuleLevelTo:
    def test_to_returns_configured_output(self) -> None:
        """to('iso3').resolve('United States') returns 'USA'."""
        view = _module_to("iso3")
        assert view.resolve("United States") == "USA"

    def test_to_resolve_returns_str_not_result(self) -> None:
        """View resolve returns str, not ResolutionResult."""
        view = _module_to("iso3")
        result = view.resolve("Germany")
        assert isinstance(result, str)

    def test_to_resolve_id_returns_entity_id(self) -> None:
        """View resolve_id returns entity_id, not the pivoted code."""
        view = _module_to("iso3")
        eid = view.resolve_id("United States")
        assert eid == "country/USA"
        assert eid != "USA"


# ---------------------------------------------------------------------------
# get_default_to / get_on_missing / _reset_config
# ---------------------------------------------------------------------------


class TestConfigGetters:
    def test_get_default_to_reflects_configure(self) -> None:
        """get_default_to() returns the value passed to configure()."""
        resolvekit.configure(default_to="iso3")
        assert get_default_to() == "iso3"

    def test_get_on_missing_reflects_configure(self) -> None:
        """get_on_missing() returns the value passed to configure()."""
        resolvekit.configure(default_to="iso3", on_missing="null")
        assert get_on_missing() == "null"

    def test_get_default_to_default_is_none(self) -> None:
        """get_default_to() returns None when nothing is configured."""
        # teardown fixture resets before each test
        assert get_default_to() is None

    def test_get_on_missing_default_is_auto(self) -> None:
        """get_on_missing() returns 'auto' when nothing is configured."""
        assert get_on_missing() == "auto"

    def test_reset_config_clears_default_to(self) -> None:
        """_reset_config() clears default_to back to None."""
        resolvekit.configure(default_to="iso3")
        assert get_default_to() == "iso3"
        _reset_config()
        assert get_default_to() is None

    def test_reset_config_clears_on_missing(self) -> None:
        """_reset_config() clears on_missing back to 'auto'."""
        resolvekit.configure(default_to="iso3", on_missing="raise")
        assert get_on_missing() == "raise"
        _reset_config()
        assert get_on_missing() == "auto"

    def test_configure_default_to_none_preserves_on_missing(self) -> None:
        """configure(default_to=None) does not reset a previously set on_missing."""
        resolvekit.configure(default_to="iso3", on_missing="null")
        assert get_on_missing() == "null"
        resolvekit.configure(default_to=None)
        assert get_on_missing() == "null"
