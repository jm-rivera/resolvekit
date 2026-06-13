"""ContainmentAPI — geographic containment traversal collaborator.

Owns the reverse BFS walk over ``contained_in`` edges.  Depends only on the
``ResolverBackend`` protocol (calls ``get_reverse_relations`` and
``get_entity``); the facade's public ``Resolver.within`` resolves the container
and delegates to ``ContainmentAPI.within``.

Parallel to ``GroupAPI``: constructed once in ``Resolver.__init__``, reused
across all calls.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resolvekit.core.engine.interfaces import ResolverBackend
    from resolvekit.core.model import EntityRecord


class ContainmentAPI:
    """Geographic containment traversal.  Constructed once in ``Resolver.__init__``.

    Args:
        runner: ``ResolverBackend`` for relation and entity queries.
    """

    def __init__(self, *, runner: ResolverBackend) -> None:
        self._runner = runner

    def within(
        self,
        *,
        container_id: str,
        relation: str = "contained_in",
        entity_type: frozenset[str] | None,
        recursive: bool,
        max_depth: int | None,
        as_of: date | None,
    ) -> list[EntityRecord]:
        """Reverse BFS from *container_id* over *relation* edges.

        Returns hydrated, deduplicated ``EntityRecord``s for all descendants,
        sorted by ``entity_id``.  ``entity_type`` filters the output only;
        intermediate nodes are always traversed.  ``recursive=False`` stops
        after the first hop (equivalent to ``max_depth=1``).  The
        ``container_id`` is seeded into the visited set so a back-edge cannot
        surface it in results.

        Args:
            container_id: Entity ID of the geographic container.
            relation: Relation type to walk (default ``"contained_in"``).
                Kept as an internal arg for testability; not exposed publicly.
            entity_type: If given, keep only descendants whose
                ``EntityRecord.entity_type`` is in this set.  ``None`` keeps all.
            recursive: Walk transitively when ``True``.  ``False`` ⇒ one hop.
            max_depth: Bound the descent in hops.  ``None`` means unbounded.
            as_of: Edge validity filter (half-open ``[valid_from, valid_until)``).
                ``None`` returns all edges regardless of date.

        Returns:
            Sorted list of hydrated ``EntityRecord``s (sorted by ``entity_id``).
        """
        # Seed the visited set with the container itself so a back-edge can't
        # surface it in results.
        visited: set[str] = {container_id}
        result_ids: list[str] = []

        frontier: list[str] = [container_id]
        depth = 0

        while frontier:
            if max_depth is not None and depth >= max_depth:
                break
            next_frontier: list[str] = []
            for node in frontier:
                for child in self._runner.get_reverse_relations(
                    entity_id=node,
                    relation_type=relation,
                    as_of=as_of,
                ):
                    if child in visited:
                        continue
                    visited.add(child)
                    result_ids.append(child)
                    next_frontier.append(child)
            depth += 1
            if not recursive:
                # recursive=False ≡ max_depth=1 — stop after the first hop.
                break
            frontier = next_frontier

        # Hydrate in one batch — bulk bypasses the per-entity SQLite LRU cache, which is
        # acceptable here: within()'s result set is not reused across calls.
        hydrated = self._runner.bulk_get_entities(result_ids)
        records: list[EntityRecord] = []
        for eid in result_ids:  # preserve BFS-collected order pre-sort
            entity = hydrated.get(eid)  # None-on-missing: absent IDs skipped
            if entity is None:
                continue
            if entity_type is not None and entity.entity_type not in entity_type:
                continue
            records.append(entity)

        records.sort(key=lambda e: e.entity_id)
        return records
