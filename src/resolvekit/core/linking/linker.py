"""Linker protocol and LinkResult for overlay composition.

The Linker protocol defines how overlay rows are linked to base entities.
Each domain pack provides its own Linker implementation with domain-specific
tie-breaking rules.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from resolvekit.core.store import EntityStore


@dataclass(frozen=True)
class LinkResult:
    """Result of attempting to link an overlay row to a base entity.

    This is a structured result that can express:
    - Success (linked): Single match found
    - Failure (not_found): No match for any key
    - Ambiguity (ambiguous): Multiple matches, tie-break failed
    - Invalid input (invalid_key): Key format invalid or unsupported

    Attributes:
        status: One of "linked", "not_found", "ambiguous", "invalid_key"
        entity_id: The matched entity ID (set when status == "linked")
        candidates: Entity IDs that matched (set when status == "ambiguous")
        message: Diagnostic info for errors
    """

    status: Literal["linked", "not_found", "ambiguous", "invalid_key"]
    entity_id: str | None = None
    candidates: tuple[str, ...] = ()
    message: str | None = None

    @classmethod
    def linked(cls, entity_id: str) -> "LinkResult":
        """Create a successful link result.

        Args:
            entity_id: The matched base entity ID

        Returns:
            LinkResult with status="linked"
        """
        return cls(status="linked", entity_id=entity_id)

    @classmethod
    def not_found(cls, message: str | None = None) -> "LinkResult":
        """Create a not-found result.

        Args:
            message: Optional diagnostic message

        Returns:
            LinkResult with status="not_found"
        """
        return cls(status="not_found", message=message)

    @classmethod
    def ambiguous(
        cls,
        candidates: tuple[str, ...],
        message: str | None = None,
    ) -> "LinkResult":
        """Create an ambiguous result with multiple candidates.

        Args:
            candidates: Tuple of entity IDs that matched
            message: Optional diagnostic message

        Returns:
            LinkResult with status="ambiguous"
        """
        return cls(status="ambiguous", candidates=candidates, message=message)

    @classmethod
    def invalid_key(cls, message: str) -> "LinkResult":
        """Create an invalid-key result.

        Args:
            message: Diagnostic message explaining the issue

        Returns:
            LinkResult with status="invalid_key"
        """
        return cls(status="invalid_key", message=message)

    @property
    def is_success(self) -> bool:
        """Return True if link was successful."""
        return self.status == "linked"


@runtime_checkable
class Linker(Protocol):
    """Protocol for domain-specific link resolvers.

    Each domain pack provides a Linker that understands its link keys
    and implements domain-specific tie-breaking rules.

    Example implementations:
    - GeoLinker: Understands dcid, iso3, iso2, geonameid
    - OrgLinker: Understands dcid, lei, duns, permid
    """

    def resolve_link(
        self,
        overlay_row: dict,
        link_keys: list[str],
        base_store: "EntityStore",
    ) -> LinkResult:
        """Attempt to link an overlay row to a base entity.

        The linker tries each key in `link_keys` order until one produces
        a definitive result. If multiple base entities match a key, the
        linker should apply domain-specific tie-breaking rules. If no
        tie-break is possible, return `LinkResult.ambiguous()`.

        Args:
            overlay_row: Row data from overlay pack
            link_keys: Ordered list of keys to try (from overlay metadata)
            base_store: Store to search for matching entities

        Returns:
            LinkResult with one of:
            - linked: Single match found, entity_id set
            - not_found: No match for any key (new entity or error)
            - ambiguous: Multiple matches, tie-break failed, candidates listed
            - invalid_key: Key format invalid or unsupported
        """
        ...
