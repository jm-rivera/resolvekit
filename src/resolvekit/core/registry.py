"""Domain pack registry for managing available packs."""

from collections.abc import Callable
from importlib import import_module
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from resolvekit.core.engine import (
        CandidateSource,
        Constraint,
        DecisionPolicy,
        PipelineConfig,
    )
    from resolvekit.core.engine.interfaces import FeatureExtractor, Scorer
    from resolvekit.core.linking import Normalizer
    from resolvekit.core.util.normalization import NormalizationProfile

# Scoring function type for pack-declared routing heuristics.
# Args are (text, text_lower) — the router calls scorer(text, text_lower).
type PackScoringFn = Callable[[str, str], float]


class RoutingHints(BaseModel):
    """Routing metadata that packs declare about themselves.

    ``type_prefixes`` is a ``list[str]`` (ordered, per-pack declaration);
    ``country_relation_prefixes`` is a ``frozenset[str]`` (order-independent set
    of relation-target prefixes, e.g. ``frozenset({'country/'})``) — the two
    fields serve different roles and are intentionally different container types.

    Instances with a non-None ``scoring_fn`` compare by identity, not value;
    two ``RoutingHints`` objects with the same callable will not be equal unless
    they hold the exact same function object.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    type_prefixes: list[str] = Field(default_factory=list)
    supported_languages: list[str] | None = Field(default=None)
    keywords: list[str] = Field(default_factory=list)
    scoring_fn: PackScoringFn | None = Field(
        default=None,
        description="Pack-declared routing scorer; args are (text, text_lower).",
    )
    country_relation_prefixes: frozenset[str] = Field(
        default_factory=frozenset,
        description=(
            "Relation target prefixes that identify country-relation targets "
            "(e.g. frozenset({'country/'}))."
        ),
    )
    country_scoped_type_prefixes: frozenset[str] = Field(
        default_factory=frozenset,
        description=(
            "Entity-type prefixes for which a COUNTRY refinement hint is "
            "meaningful (e.g. geographic types). Empty (the default) means a "
            "country hint is only offered when an entity carries explicit "
            "country metadata (a country_code attribute or a country relation)."
        ),
    )


class DomainPack(Protocol):
    """Protocol for domain packs.

    Domain packs define the sources, constraints, and scoring logic
    for a specific entity domain (e.g., geo, org).
    """

    @property
    def pack_id(self) -> str:
        """Unique identifier for this pack."""
        ...

    @property
    def sources(self) -> list["CandidateSource"]:
        """Candidate sources for this pack."""
        ...

    @property
    def constraints(self) -> list["Constraint"]:
        """Constraints for this pack."""
        ...

    @property
    def feature_extractor(self) -> "FeatureExtractor | None":
        """Feature extractor for this pack."""
        ...

    @property
    def scorer(self) -> "Scorer | None":
        """Scorer for this pack."""
        ...

    @property
    def decision_policy(self) -> "DecisionPolicy":
        """Decision policy for this pack."""
        ...

    @property
    def routing_hints(self) -> RoutingHints | None:
        """Routing hints for query routing."""
        ...

    @property
    def normalization_profile(self) -> "NormalizationProfile | None":
        """Domain-specific normalization profile."""
        ...

    @property
    def merge_normalizer(self) -> "Normalizer | None":
        """Normalizer for entity merge deduplication."""
        ...

    @property
    def config(self) -> "PipelineConfig | None":
        """Pipeline configuration for this pack."""
        ...

    @property
    def group_entity_types(self) -> frozenset[str]:
        """Entity types this pack treats as 'group-like' for tiebreak rules.

        Used by Resolver.resolve() and Resolver.resolve_explained() to
        disambiguate AMBIGUOUS results where exactly one of the top-2
        candidates is a group entity. Also enumerated by
        Resolver.known_groups(). Return an empty frozenset to opt out.

        Populate this when your domain has entities that *aggregate* other
        entities (e.g. a country group like G7, an alliance like NATO) —
        these are the types where a query for the group name should win over
        an exact name match against one of its members. Leave empty
        otherwise.
        """
        ...

    def candidate_ordering_key(self, entity_type: str) -> int | None:
        """Return a sort key for re-ordering candidates by entity type.

        Used by the pipeline to promote specific entity types (e.g. country)
        above aggregating ones (e.g. region) when confidence scores are equal.

        Returns:
            An integer rank (lower = higher priority), or None when this pack
            has no opinion on ordering.
        """
        ...


class DomainRegistry:
    """Registry for domain packs.

    Provides centralized management of available domain packs.
    Supports runtime registration and discovery.

    Example:
        registry = DomainRegistry()
        registry.register(GeoPack())
        registry.register(OrgPack())

        pack = registry.get("geo")
    """

    def __init__(self) -> None:
        self._packs: dict[str, DomainPack] = {}

    def register(self, pack: DomainPack, *, allow_replace: bool = False) -> None:
        """Register a domain pack.

        Args:
            pack: Pack implementing DomainPack protocol
            allow_replace: If True, allows replacing existing pack

        Raises:
            ValueError: If pack_id already registered and allow_replace=False
        """
        pack_id = pack.pack_id
        if pack_id in self._packs and not allow_replace:
            raise ValueError(f"Pack '{pack_id}' already registered")
        self._packs[pack_id] = pack

    def unregister(self, pack_id: str) -> None:
        """Unregister a domain pack.

        Args:
            pack_id: ID of pack to remove
        """
        self._packs.pop(pack_id, None)

    def get(self, pack_id: str) -> DomainPack | None:
        """Get a registered pack by ID.

        Args:
            pack_id: Pack identifier

        Returns:
            Pack instance or None if not found
        """
        return self._packs.get(pack_id)

    @property
    def available_packs(self) -> list[str]:
        """List of registered pack IDs."""
        return list(self._packs.keys())

    def all_packs(self) -> dict[str, DomainPack]:
        """Get all registered packs."""
        return self._packs.copy()


_pack_factories: dict[str, type] = {}


def register_pack_factory(pack_id: str, factory: type) -> None:
    """Register a pack factory for dynamic pack creation.

    Args:
        pack_id: Pack identifier
        factory: Pack class to instantiate
    """
    _pack_factories[pack_id] = factory


def get_pack_factory(pack_id: str) -> type | None:
    """Get a pack factory by ID.

    Args:
        pack_id: Pack identifier

    Returns:
        Pack class or None if not found
    """
    return _pack_factories.get(pack_id)


def _ensure_builtin_factories() -> None:
    """Lazily register built-in pack factories.

    Checks each built-in pack independently to avoid blocking
    one built-in if another was pre-registered with a custom factory.
    """
    if "geo" not in _pack_factories:
        _pack_factories["geo"] = import_module("resolvekit.packs.geo").GeoPack

    if "org" not in _pack_factories:
        _pack_factories["org"] = import_module("resolvekit.packs.org").OrgPack

    if "custom" not in _pack_factories:
        _pack_factories["custom"] = import_module("resolvekit.packs.custom").GenericPack


# Global default registry (lazy initialized) - use dict to avoid global statements
_registry_state: dict[str, DomainRegistry | None] = {"instance": None}


def default_registry() -> DomainRegistry:
    """Get the default global registry.

    Lazily initializes with built-in packs on first access.
    Built-in packs (geo, org) are registered without SymSpell dictionaries.
    For full functionality with SymSpell support, use Resolver.from_datapacks().
    """
    if _registry_state["instance"] is None:
        _ensure_builtin_factories()
        registry = DomainRegistry()
        # Register built-in packs (without symspell dictionaries)
        for _, factory in _pack_factories.items():
            registry.register(factory())
        _registry_state["instance"] = registry
    instance = _registry_state["instance"]
    if instance is None:
        raise RuntimeError("Default registry initialization failed")
    return instance


def reset_default_registry() -> None:
    """Reset the default registry (for testing)."""
    _registry_state["instance"] = None
