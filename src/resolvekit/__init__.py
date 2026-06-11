"""ResolveKit

Resolve free-text strings to canonical entity IDs - fast, deterministic
resolution.

Quick start (module-level)::

    import resolvekit
    resolvekit.resolve_id("United States")  # -> "country/USA"

Quick start (instance-level)::

    from resolvekit import Resolver

    resolver = Resolver.from_modules(module_ids=["geo.countries"])
    result = resolver.resolve("United States")
    print(result.entity_id)  # "country/USA"

With context hints::

    from resolvekit import Resolver, ResolutionContext

    resolver = Resolver.from_modules(module_ids=["geo.countries"])
    result = resolver.resolve(
        "Paris",
        context=ResolutionContext(country="FR"),
    )

With explanation::

    resolver = Resolver.from_modules(module_ids=["geo.countries"])
    result = resolver.resolve("US")
    scorecard = result.explain(verbosity="full")
    print(scorecard.as_text())
"""

import importlib.metadata
import pkgutil

__path__ = pkgutil.extend_path(__path__, __name__)

try:
    __version__ = importlib.metadata.version("resolvekit")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0+unknown"

from resolvekit._convenience import (
    bulk,
    configure,
    download,
    entity,
    modules,
    parse,
    parse_bulk,
    resolve,
    resolve_id,
    snap,
    to,
)

# Re-exports excluded from __all__ — importable but not surfaced via star-import.
# The ``x as x`` form is ruff's idiom for "intentional re-export, keep silent".
from resolvekit._convenience import clear_cache as clear_cache
from resolvekit._convenience import default as default
from resolvekit._convenience import download_all as download_all
from resolvekit._convenience import reset as reset
from resolvekit.core.api import Resolver
from resolvekit.core.byod.result import AugmentResult
from resolvekit.core.errors import (
    AmbiguousResolutionError,
    CrosswalkError,
    DataPackNotAvailableError,
    EntityNotFoundError,
    GroupNotFoundError,
    NoModulesInstalledError,
    OutputMissingError,
    ResolutionError,
    UnknownCodeSystemError,
    UnknownDomainError,
    UnknownOutputError,
)
from resolvekit.core.errors_base import ExplainNotAvailableError, ResolverError
from resolvekit.core.model import (
    BulkResult,
    EntityRecord,
    ResolutionContext,
    ResolutionResult,
    ResolutionStatus,
)
from resolvekit.core.model.crosswalk import IGNORE, Crosswalk
from resolvekit.core.parse import DroppedSpan as DroppedSpan
from resolvekit.core.parse import ParsedEntity as ParsedEntity
from resolvekit.core.parse import ParseResult as ParseResult
from resolvekit.core.util.sentinel import SentinelBlocklist as SentinelBlocklist

# ``default``, ``download_all``, ``clear_cache``, and ``reset`` are importable
# but excluded from star-imports.
__all__ = [
    "IGNORE",
    "AmbiguousResolutionError",
    "AugmentResult",
    "BulkResult",
    "Crosswalk",
    "CrosswalkError",
    "DataPackNotAvailableError",
    "DroppedSpan",
    "EntityNotFoundError",
    "EntityRecord",
    "ExplainNotAvailableError",
    "GroupNotFoundError",
    "NoModulesInstalledError",
    "OutputMissingError",
    "ParseResult",
    "ParsedEntity",
    "ResolutionContext",
    "ResolutionError",
    "ResolutionResult",
    "ResolutionStatus",
    "Resolver",
    "ResolverError",
    "UnknownCodeSystemError",
    "UnknownDomainError",
    "UnknownOutputError",
    "bulk",
    "configure",
    "download",
    "entity",
    "modules",
    "parse",
    "parse_bulk",
    "resolve",
    "resolve_id",
    "snap",
    "to",
]
