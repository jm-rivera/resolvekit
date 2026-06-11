"""Build-time source adapter protocol for extraction variability points.

Stateful multi-domain extraction contract (discover → fetch → normalize → write)
instantiated once per build run, holding per-domain connection state or caches.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, TypeVar, runtime_checkable

from resolvekit.builder.inspection import DomainInspection

if TYPE_CHECKING:
    from resolvekit.builder.sources.discovery_events import DiscoveryProgressEvent

T = TypeVar("T")


class SourceAdapter(Protocol):
    """Source adapter abstraction for extraction/normalization."""

    def supported_domains(self) -> set[str]:
        """Return supported domain IDs (e.g., {"geo"})."""

    def discover_entities(self, domain: str) -> list[str]:
        """Discover entity IDs to be chunked for extraction."""

    def fetch_raw_chunk(self, domain: str, entity_ids: list[str]) -> dict[str, Any]:
        """Fetch raw payload for a chunk of entities."""

    def normalize_raw_chunk(
        self, domain: str, raw_chunk: dict[str, Any]
    ) -> dict[str, list[dict[str, Any]]]:
        """Normalize raw payload to canonical row dictionaries."""


class FilteredDiscoveryAdapter(Protocol):
    """Explicit capability for type-aware discovery optimizations.

    Not ``@runtime_checkable``; use ``adapter_supports_filtered_discovery(adapter)``
    to check capability — ``isinstance`` against this protocol raises ``TypeError``.
    """

    def discover_entities_filtered(
        self,
        domain: str,
        include_entity_types: list[str],
        include_relation_targets: bool,
    ) -> list[str]:
        """Discover entity IDs using caller-provided type requirements."""

    def filter_discovered_entities(
        self,
        domain: str,
        entity_ids: list[str],
        include_entity_types: list[str],
    ) -> list[str]:
        """Filter already discovered IDs by canonical entity type."""


DiscoveryBatchFn = Callable[[str, list[str], "DiscoveryProgressEvent"], None]
DiscoveryProgressFn = Callable[["DiscoveryProgressEvent"], None]


@runtime_checkable
class IncrementalFilteredDiscoveryAdapter(Protocol):
    """Explicit capability for streaming filtered discovery progress."""

    def discover_entities_filtered_incremental(
        self,
        domain: str,
        *,
        include_entity_types: list[str],
        include_relation_targets: bool,
        emit_entities: DiscoveryBatchFn,
        emit_progress: DiscoveryProgressFn,
        seed_frontier: dict[str, list[str]] | None = None,
    ) -> None:
        """Discover entities incrementally and emit progress + entity batches."""


class InspectableSourceAdapter(Protocol):
    """Explicit capability for coverage inspection.

    Not ``@runtime_checkable``; use ``adapter_supports_inspection(adapter)``
    to check capability — ``isinstance`` against this protocol raises ``TypeError``.
    """

    def inspect_domain(
        self,
        domain: str,
        *,
        include_entity_types: list[str],
        include_relation_targets: bool,
    ) -> DomainInspection:
        """Inspect source coverage for one domain."""


class RetryFn(Protocol):
    """Bounded retry wrapper callable used by source discovery/fetch flows."""

    def __call__(self, fn: Callable[..., T], **kwargs: Any) -> T: ...


def adapter_supports_filtered_discovery(adapter: object) -> bool:
    """True if the adapter advertises type-aware filtered discovery.

    Prefers the explicit ``supports_filtered_discovery()`` predicate; falls
    back to a structural ``hasattr`` probe for v0.x non-DC adapters that
    implement the method directly without the predicate.
    """
    probe = getattr(adapter, "supports_filtered_discovery", None)
    if callable(probe):
        return bool(probe())
    return hasattr(adapter, "discover_entities_filtered")  # structural fallback (v0.x)


def adapter_supports_inspection(adapter: object) -> bool:
    """True if the adapter advertises coverage inspection.

    Prefers the explicit ``supports_inspection()`` predicate; falls back to a
    structural ``hasattr`` probe for v0.x non-DC adapters that implement the
    method directly without the predicate.
    """
    probe = getattr(adapter, "supports_inspection", None)
    if callable(probe):
        return bool(probe())
    return hasattr(adapter, "inspect_domain")  # structural fallback (v0.x)
