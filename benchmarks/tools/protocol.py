"""Common adapter interface for the competitive benchmark.

Every competitor tool (pycountry, countryguess, resolvekit itself, etc.)
is wrapped in a small adapter that returns a Response. The runner
never inspects tool internals; it only sees this shape.
"""

from __future__ import annotations

from typing import ClassVar, Protocol, runtime_checkable

from benchmarks.core.kernel import Query, Response, Status
from benchmarks.core.toolspec import ToolSpec

__all__ = ["Query", "ResolverAdapter", "Response", "Status", "ToolSpec"]


@runtime_checkable
class ResolverAdapter(Protocol):
    """Every benchmark adapter implements this shape."""

    spec: ClassVar[ToolSpec]

    def warmup(self) -> None: ...

    def resolve(self, query: Query) -> Response: ...

    def version(self) -> str | None: ...
