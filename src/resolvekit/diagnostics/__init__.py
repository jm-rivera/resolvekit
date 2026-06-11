"""resolvekit.diagnostics — module-level diagnostic convenience functions.

Delegates to the default resolver's diagnostics namespace, so users can
call diagnostics without constructing a resolver explicitly.

Example::

    import resolvekit.diagnostics as rk_diag

    report = rk_diag.inspect("US")
    candidates = rk_diag.search("United Stats", top_k=5)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resolvekit.core.model import CandidateSummary, ResolutionContext
    from resolvekit.core.model.inspection import InspectionReport

__all__ = [
    "inspect",
    "search",
]


def inspect(
    text: str,
    *,
    domain: str | list[str] | None = None,
) -> InspectionReport:
    """Diagnostic inspection via the default resolver.

    Returns an :class:`~resolvekit.core.model.inspection.InspectionReport`
    showing exact-code matches, exact-name matches, and top-5 fuzzy
    candidates for *text* (unfiltered by the confidence threshold).

    Args:
        text: Query text to inspect.
        domain: Optional domain filter.

    Returns:
        InspectionReport with match details.
    """
    from resolvekit._convenience import _get_default

    return _get_default().diagnostics.inspect(text, domain=domain)


def search(
    text: str,
    *,
    top_k: int = 10,
    domain: str | list[str] | None = None,
    context: ResolutionContext | None = None,
) -> list[CandidateSummary]:
    """Return top-K candidates via the default resolver.

    Runs the full pipeline without a decision step.  The query cache does
    not apply — every call re-runs retrieval and scoring.

    Args:
        text: Text to search for candidates.
        top_k: Maximum number of candidates to return (default 10).
        domain: Optional domain(s) to route to.
        context: Optional resolution context.

    Returns:
        List of enriched CandidateSummary objects ordered by confidence
        descending.  Returns ``[]`` for empty or non-string input.
    """
    from resolvekit._convenience import _get_default

    return _get_default().diagnostics.search(
        text, top_k=top_k, domain=domain, context=context
    )
