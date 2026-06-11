"""OutputView — a resolver bound to a fixed OutputSpec.

Forwarding dataclass: every call delegates to the underlying resolver's
private spec-aware helpers.  ``resolve_id`` always returns ``entity_id``
and is deliberately immune to the bound spec.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from resolvekit.core.api.output_spec import UNSET, OutputSpec

if TYPE_CHECKING:
    from resolvekit.core.api.resolver import (
        Resolver,  # noqa: F401 — used in class docstring cross-ref
    )


@dataclass(frozen=True, slots=True)
class OutputView:
    """A resolver bound to a fixed :class:`~resolvekit.core.api.output_spec.OutputSpec`.

    Forwards ``resolve`` / ``bulk`` / ``snap`` applying the compiled spec;
    ``resolve_id`` always returns the ``entity_id`` regardless of the bound
    output — it never pivots.

    Create via :meth:`~resolvekit.core.api.resolver.Resolver.to`::

        view = resolver.to("iso3")
        view.resolve("France")   # → "FRA"
        view.resolve_id("France")  # → "country/FRA"  (entity_id, not pivoted)
    """

    _resolver: Any  # Resolver — typed via TYPE_CHECKING to avoid import cycle
    _spec: OutputSpec

    def resolve(
        self,
        text: str,
        *,
        as_result: bool = False,
        domain: str | list[str] | None = None,
        context: Any = None,
        from_system: str | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Resolve *text* applying the bound output spec.

        Args:
            text: Text to resolve.
            as_result: Return the full :class:`ResolutionResult` instead of the
                configured output — the readable equivalent of ``to=None``.
            domain: Optional domain(s) to route to.
            context: Optional resolution context.
            from_system: Force-disambiguate input as a code system.
            timeout: Maximum seconds to wait.

        Returns:
            The configured output value (``str | None``), or a
            :class:`ResolutionResult` when ``as_result=True``.
        """
        return self._resolver._resolve_with_spec(
            text,
            spec=self._spec,
            as_result=as_result,
            domain=domain,
            context=context,
            from_system=from_system,
            timeout=timeout,
        )

    def resolve_id(
        self,
        text: str,
        *,
        on_ambiguous: str = "raise",
        from_system: str | None = None,
        domain: str | list[str] | None = None,
        context: Any = None,
        timeout: float | None = None,
    ) -> str | None:
        """Resolve *text* and return the entity ID.

        ``resolve_id`` always returns the ``entity_id``, even on a view bound
        to a default output — use ``resolve()`` for the configured output.

        Args:
            text: Text to resolve.
            on_ambiguous: Behaviour on ambiguous matches: ``"raise"`` (default),
                ``"null"``, or ``"best"``.
            from_system: Force-disambiguate input as a code system.
            domain: Optional domain(s) to route to.
            context: Optional resolution context.
            timeout: Maximum seconds to wait.

        Returns:
            Entity ID string, or ``None`` if no match.
        """
        return self._resolver.resolve_id(
            text,
            on_ambiguous=on_ambiguous,
            from_system=from_system,
            domain=domain,
            context=context,
            timeout=timeout,
        )

    def bulk(
        self,
        *,
        values: Any,
        on_missing: Any = UNSET,
        output: str = "series",
        domain: str | list[str] | None = None,
        context: Any = None,
        from_system: str | None = None,
        not_found: str = "null",
        on_error: str = "raise",
        on_ambiguous: str = "null",
    ) -> Any:
        """Resolve *values* in bulk applying the bound output spec.

        Args:
            values: Iterable of text values to resolve.
            on_missing: Miss policy override — ``"auto"`` (default), ``"raise"``,
                or ``"null"``.  ``UNSET`` inherits the spec's configured policy.
            output: Output format — ``"series"`` (default), ``"record"``, or
                ``"frame"``.
            domain: Optional domain(s) to route to.
            context: Optional resolution context.
            from_system: Force-disambiguate inputs as a code system.
            not_found: How to handle unresolved inputs.
            on_error: How to handle pipeline errors.
            on_ambiguous: How to handle ambiguous inputs.

        Returns:
            A native series when ``output="series"`` and spec is active;
            otherwise a :class:`BulkResult`.
        """
        return self._resolver._bulk_with_spec(
            values=values,
            spec=self._spec,
            on_missing=on_missing,
            output=output,
            domain=domain,
            context=context,
            from_system=from_system,
            not_found=not_found,
            on_error=on_error,
            on_ambiguous=on_ambiguous,
        )

    def snap(
        self,
        *,
        query: str,
        candidates: list[str],
        max_distance: float = 0.5,
        domain: str | list[str] | None = None,
        context: Any = None,
    ) -> Any:
        """Snap *query* to the closest candidate and return the configured output.

        Args:
            query: Fuzzy query string.
            candidates: List of candidate strings to snap against.
            max_distance: Maximum normalised edit distance (0-1).
            domain: Optional domain(s) to route to.
            context: Optional resolution context.

        Returns:
            The configured output value for the best-matching candidate, or
            ``None`` if no candidate is within *max_distance*.
        """
        return self._resolver._snap_with_spec(
            query=query,
            candidates=candidates,
            spec=self._spec,
            max_distance=max_distance,
            domain=domain,
            context=context,
        )
