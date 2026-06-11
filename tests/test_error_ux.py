"""Tests for Polars-style error messages with .hint + add_note (PEP 678)."""

from __future__ import annotations

import traceback

from resolvekit.core.errors import (
    AmbiguousResolutionError,
    UnknownCodeSystemError,
    UnknownDomainError,
)
from resolvekit.core.errors_base import ExplainNotAvailableError, ResolverError


def test_resolver_error_hint_attribute_set() -> None:
    """ResolverError stores hint on the instance."""
    err = ResolverError("something went wrong", hint="next call")
    assert err.hint == "next call"


def test_resolver_error_add_note_called() -> None:
    """PEP 678 add_note makes the hint appear in formatted tracebacks."""
    err = ResolverError("something went wrong", hint="try X")
    formatted = "".join(traceback.format_exception(type(err), err, None))
    assert "Hint: try X" in formatted


def test_resolver_error_no_hint_no_note() -> None:
    """When hint is None, no note is added and .hint is None."""
    err = ResolverError("something went wrong")
    assert err.hint is None
    assert not getattr(err, "__notes__", [])


def test_unknown_domain_error_format() -> None:
    """Message is uncapitalized with no trailing period; suggestion is in .hint."""
    err = UnknownDomainError(unknown=["geo"], available=["geo", "org"])
    msg = str(err)
    # Polars style: uncapitalized, no trailing period
    assert msg[0].islower(), f"message should start lowercase, got: {msg!r}"
    assert not msg.endswith("."), f"message should not end with period, got: {msg!r}"
    # Suggestion is in .hint, not concatenated into the main message
    assert err.hint is not None
    assert "available" in err.hint


def test_unknown_domain_error_close_match_in_hint() -> None:
    """Fuzzy close match surfaces in .hint, not in the main message."""
    err = UnknownDomainError(unknown=["gio"], available=["geo", "org"])
    assert err.hint is not None
    assert "geo" in err.hint


def test_unknown_code_system_error_hint_includes_close_match() -> None:
    """Fuzzy suggestion from difflib appears in .hint."""
    err = UnknownCodeSystemError("iso_3", available=["iso3", "iso2", "numeric"])
    assert err.hint is not None
    assert "iso3" in err.hint


def test_unknown_code_system_error_message_style() -> None:
    """Message is uncapitalized and has no trailing period."""
    err = UnknownCodeSystemError("xyz", available=["iso3"])
    msg = str(err)
    assert msg[0].islower(), f"message should start lowercase, got: {msg!r}"
    assert not msg.endswith("."), f"message should not end with period, got: {msg!r}"


def test_existing_errors_inherit_resolver_error() -> None:
    """All re-parented error subclasses are instances of ResolverError."""
    ambiguous = AmbiguousResolutionError(candidates=None)
    assert isinstance(ambiguous, ResolverError)

    unknown_domain = UnknownDomainError(unknown=["foo"], available=["geo"])
    assert isinstance(unknown_domain, ResolverError)

    unknown_code = UnknownCodeSystemError("bar", available=["iso3"])
    assert isinstance(unknown_code, ResolverError)

    explain = ExplainNotAvailableError()
    assert isinstance(explain, ResolverError)


def test_ambiguous_resolution_error_inherits_and_has_hint() -> None:
    """AmbiguousResolutionError has a useful default hint."""
    err = AmbiguousResolutionError(candidates=None)
    assert err.hint is not None
    assert "disambiguate" in err.hint


def test_explain_not_available_error_default_hint() -> None:
    """ExplainNotAvailableError ships with a default hint."""
    err = ExplainNotAvailableError()
    assert err.hint is not None
    assert "resolver" in err.hint


def test_explain_not_available_error_custom_hint() -> None:
    """Custom hint overrides the default."""
    err = ExplainNotAvailableError(hint="use resolver.resolve(...).explain()")
    assert err.hint == "use resolver.resolve(...).explain()"
