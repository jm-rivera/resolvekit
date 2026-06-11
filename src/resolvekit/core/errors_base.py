"""Base error class for ResolveKit — imported by errors.py to avoid import cycles."""

from __future__ import annotations


class ResolverError(Exception):
    """Base class for all public ResolveKit errors.

    Every subclass carries an optional ``hint`` that surfaces as a PEP 678
    ``__notes__`` entry so it appears in tracebacks automatically.

    Attributes:
        hint: Short suggestion for the caller, or None.
    """

    hint: str | None

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint
        if hint is not None:
            self.add_note(f"Hint: {hint}")


class ExplainNotAvailableError(ResolverError):
    """Raised when ``result.explain()`` is called on a detached result.

    A ``ResolutionResult`` is detached when it was constructed outside a live
    ``Resolver`` (e.g. deserialised from JSON, or returned by a Resolver that
    has since been closed).
    """

    def __init__(self, *, hint: str | None = None) -> None:
        super().__init__(
            "explain() requires a live resolver",
            hint=hint
            or "call resolver.resolve(text, to=None).explain() to re-acquire one",
        )
