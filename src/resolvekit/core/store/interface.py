"""EntityStore interface - the data access boundary.

Candidate sources MUST use EntityStore for all data access.
They must NOT run ad-hoc SQL directly. This abstraction enables:
- Swappable backends (SQLite, Postgres, search indexes)
- Overlay support via CompositeStore
- Consistent caching and connection management
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import date

from resolvekit.core.model import EntityRecord


class EntityStore(ABC):
    """Abstract interface for entity data access.

    This is the ONLY way candidate sources should access entity data.
    Implementations handle backend-specific details (SQL, search, etc.).

    All lookup methods use normalized values for consistent matching.
    """

    @abstractmethod
    def get_entity(self, entity_id: str) -> EntityRecord | None:
        """Get a single entity by ID.

        Args:
            entity_id: The entity identifier (e.g., "country/USA")

        Returns:
            EntityRecord if found, None otherwise
        """
        ...

    @abstractmethod
    def lookup_code(self, system: str, value_norm: str) -> list[str]:
        """Look up entity IDs by code.

        Args:
            system: Code system (e.g., "iso2", "wikidata")
            value_norm: Normalized code value

        Returns:
            List of matching entity IDs (may be empty)
        """
        ...

    @abstractmethod
    def lookup_name_exact(
        self, value_norm: str, name_kinds: set[str] | None = None
    ) -> list[str]:
        """Look up entity IDs by exact name match.

        Args:
            value_norm: Normalized name to match
            name_kinds: Optional filter by name kinds (e.g., {"canonical", "alias"})

        Returns:
            List of matching entity IDs
        """
        ...

    @abstractmethod
    def search_fulltext(
        self,
        query_norm: str,
        fields: set[str] | None = None,
        limit: int = 10,
    ) -> list[tuple[str, float, int]]:
        """Full-text search for entities.

        Args:
            query_norm: Normalized search query
            fields: Optional filter by fields to search
            limit: Maximum results to return

        Returns:
            List of (entity_id, raw_score, rank) tuples
        """
        ...

    @abstractmethod
    def bulk_get_entities(self, entity_ids: list[str]) -> dict[str, EntityRecord]:
        """Get multiple entities by ID.

        Args:
            entity_ids: List of entity IDs to fetch

        Returns:
            Dict mapping entity_id to EntityRecord (missing IDs omitted)
        """
        ...

    # Optional methods with default implementations

    def lookup_code_any(self, value_norm: str) -> list[tuple[str, str]]:
        """Look up entity IDs across all code systems by normalized value.

        Used as a catch-all fallback when targeted system lookups miss.

        Args:
            value_norm: Normalized code value to search across all systems

        Returns:
            List of (entity_id, system) tuples (may be empty).
        """
        return []

    def get_relations(
        self, entity_id: str, relation_type: str | None = None
    ) -> list[str]:
        """Get related entity IDs.

        Default implementation returns empty list.
        Backends can override for efficient relation queries.

        Args:
            entity_id: Source entity ID
            relation_type: Optional filter by relation type

        Returns:
            List of related entity IDs
        """
        return []

    def all_entity_ids(self) -> set[str]:
        """Return all entity IDs in this store. Override for efficient implementation."""
        raise NotImplementedError("all_entity_ids not implemented for this store type")

    def iter_names(
        self,
        *,
        entity_type_prefixes: frozenset[str] | None = None,
        with_name_meta: bool = False,
    ) -> Iterator[tuple[str, str]] | Iterator[tuple[str, str, str, str]]:
        """Yield name rows for every name in the store.

        The automaton-based parser builds its pattern set from this stream. One
        ``value_norm`` may yield multiple rows (surface→entity is many-to-one is
        normal: collisions like "Georgia" the country vs a region). When
        ``entity_type_prefixes`` is given, only names whose entity's type starts with
        one of the prefixes are yielded — this powers the SMALL/LARGE automaton
        gating (e.g. country-only resolvers never enumerate city names).

        Args:
            entity_type_prefixes: Optional set of entity-type prefixes (e.g.
                ``{"geo.country", "geo.admin1"}``) to restrict enumeration.
            with_name_meta: When ``False`` (default), yield 2-tuples
                ``(value_norm, entity_id)`` — byte-identical to the original
                contract, preserving all existing callers. When ``True``, yield
                4-tuples ``(value_norm, entity_id, name_kind, value)`` where
                ``value`` is the original-cased name (e.g. ``"AND"`` for
                Andorra's ISO alias). Used by the automaton builder to
                construct the code-shaped-alias side-table.

        Yields:
            ``(value_norm, entity_id)`` 2-tuples when ``with_name_meta=False``;
            ``(value_norm, entity_id, name_kind, value)`` 4-tuples when
            ``with_name_meta=True``. Order is unspecified.

        Raises:
            NotImplementedError: If the backend does not support enumeration.
        """
        raise NotImplementedError("iter_names not implemented for this store type")

    def code_systems(self) -> frozenset[str]:
        """Return the code system names known to this store.

        Default returns an empty frozenset. Backends with a codes table should
        override with an efficient ``SELECT DISTINCT`` (or equivalent) query.
        """
        return frozenset()

    def relation_types(self) -> frozenset[str] | None:
        """Return the distinct relation types stored, or None if unknown.

        None means "this store cannot characterize its relation types, so callers
        must not prune it" — the default. SQL backends override with a concrete set
        (possibly empty, meaning known to hold no relations).
        """
        return None

    def close(self) -> None:  # noqa: B027
        """Release resources held by this store.

        Default implementation is a no-op. Backends with persistent
        connections (e.g., SQLite) should override to close them.
        Safe to call multiple times.
        """

    def search_prefix(
        self, query_norm: str, field: str, limit: int = 10
    ) -> list[tuple[str, float, int]]:
        """Prefix search (useful for acronyms).

        Default implementation returns empty list.
        Backends can override if prefix search is supported.

        Args:
            query_norm: Normalized prefix to match
            field: Field to search
            limit: Maximum results

        Returns:
            List of (entity_id, raw_score, rank) tuples
        """
        return []

    def get_relations_as_of(
        self, entity_id: str, relation_type: str, as_of: date
    ) -> list[str]:
        """Return target entity IDs for relations active on the given date.

        Default returns empty list. Override in backends that support temporal queries.
        Null bounds are treated as always-valid.

        Args:
            entity_id: Source entity ID.
            relation_type: Relation type to filter by.
            as_of: Reference date for the temporal filter.

        Returns:
            List of target entity IDs whose validity window contains ``as_of``.
        """
        return []

    def get_reverse_relations(
        self,
        target_id: str,
        relation_type: str,
        *,
        as_of: date | None = None,
    ) -> list[str]:
        """Return entity IDs that have a relation of given type pointing to target_id.

        When ``as_of`` is None, returns all such entities regardless of validity.
        Default returns empty list. Override in backends that support reverse lookups.

        Args:
            target_id: Target entity ID to look up.
            relation_type: Relation type to filter by.
            as_of: When provided, only returns relations active on that date.

        Returns:
            List of source entity IDs with the given relation to ``target_id``.
        """
        return []

    def list_entities_by_type(self, entity_type: str) -> list[EntityRecord]:
        """Return all entities of the given type.

        Default returns empty list. Override in backends that support type filtering.

        Args:
            entity_type: Entity type string to filter by (e.g., "geo.organization").

        Returns:
            List of ``EntityRecord`` objects with the given type.
        """
        return []

    def iter_suggest_names(
        self,
        *,
        entity_type_prefixes: frozenset[str] | None = None,
        entity_type_exclude_prefixes: frozenset[str] | None = None,
    ) -> Iterator[tuple[str, str, str, bool, str]]:
        """Yield name rows for suggest() candidate materialization.

        Streams 5-tuples for every name in the store, optionally filtered by
        entity type prefix.  The caller memoizes the resulting list; this
        method should not be called per-keystroke.

        Yields:
            ``(value_norm, entity_id, name_kind, is_preferred, value)`` where
            ``value`` is the original-cased name string.

        Args:
            entity_type_prefixes: When given, only names whose entity type
                starts with one of the prefixes are yielded.
            entity_type_exclude_prefixes: When given, names whose entity type
                starts with any of these prefixes are excluded.  Useful for
                filtering denylist tiers (e.g. ``geo.city``) from a broad
                unfiltered pool without listing every allowed type.

        Raises:
            NotImplementedError: If the backend does not support enumeration.
        """
        raise NotImplementedError(
            "iter_suggest_names not implemented for this store type"
        )

    def search_token_infix(
        self,
        query_norm: str,
        *,
        entity_type_prefixes: frozenset[str] | None = None,
        limit: int = 10,
    ) -> list[tuple[str, float, int]]:
        """Search for entities where ``query_norm`` appears as a name token.

        Used by the suggest engine to find token-infix matches (e.g. ``"york"``
        finding "New York").  FTS5 stores use a bare-token MATCH; non-FTS stores
        fall back to a ``LIKE %query%`` scan.

        Interior-substring (mid-token) infix matching is out of scope — this
        matches whole FTS5 tokens only.  Document callers that expect mid-token
        matches as a known limitation.

        Args:
            query_norm: Normalized query token.
            entity_type_prefixes: Optional entity type filter.
            limit: Maximum results to return.

        Returns:
            List of ``(entity_id, raw_score, rank)`` tuples, or ``[]`` when
            the store does not support infix search.
        """
        return []
