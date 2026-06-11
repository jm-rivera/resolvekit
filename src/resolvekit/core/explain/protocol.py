"""Explainer structural protocol.

Any object that implements ``resolve_explained`` with this signature satisfies
``Explainer`` — including ``Resolver`` — without importing the concrete facade.
"""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from resolvekit.core.explain.result_types import ExplainedResolution

if TYPE_CHECKING:
    from resolvekit.core.explain.scorecard import Verbosity
    from resolvekit.core.model.query import ResolutionContext


@runtime_checkable
class Explainer(Protocol):
    """Structural protocol satisfied by any object that can explain a resolution.

    ``Resolver`` conforms structurally — no explicit ``implements`` needed.
    The weakref in ``ResolutionResult._explainer`` is typed as
    ``weakref.ref[Explainer]`` so the model layer never imports the facade.
    """

    def resolve_explained(
        self,
        text: str,
        *,
        domain: "str | list[str] | None" = ...,
        context: "ResolutionContext | None" = ...,
        verbosity: "Verbosity | str" = ...,
    ) -> ExplainedResolution: ...
