"""GroupAPI — group/membership surface collaborator.

Owns ``members_of``, ``is_member``, ``known_groups``, and the private helpers
that back them.  Depends on the ``ResolverBackend`` protocol (calls
``get_reverse_relations``, ``get_relations_as_of``, ``get_pack_group_types``,
``available_group_types``, ``is_snapshot_entity``), not the concrete Resolver.

The facade's public ``members_of``/``is_member``/``known_groups`` methods
delegate here with a bound ``resolve_fn`` injected at call time so GroupAPI
stays circular-import-free.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING

from resolvekit.core.errors import (
    AmbiguousResolutionError,
    GroupNotFoundError,
    UnknownCodeSystemError,
)
from resolvekit.core.model import (
    CandidateSummary,
    ReasonCode,
    ResolutionResult,
    ResolutionStatus,
)

if TYPE_CHECKING:
    from resolvekit.core.engine.interfaces import ResolverBackend


class GroupAPI:
    """Group/membership surface.  Constructed once in ``Resolver.__init__``.

    Args:
        runner: ``ResolverBackend`` for relation and entity queries.
    """

    def __init__(self, *, runner: ResolverBackend) -> None:
        self._runner = runner

    # ------------------------------------------------------------------
    # Public surface — called by Resolver.members_of / is_member / known_groups
    # ------------------------------------------------------------------

    def members_of(
        self,
        group: str,
        *,
        as_of: date | None = None,
        as_codes: str | None = None,
        resolve_fn: Callable[[str], ResolutionResult],
    ) -> list[str]:
        """Return entity IDs (or codes) of all members of the given group.

        Args:
            group: Group name, abbreviation, or entity ID.
            as_of: Reference date for membership lookup. Defaults to today.
            as_codes: When None, returns sorted entity_ids.  Pass a code system
                name (e.g. ``"iso3"``) to return code values instead.
            resolve_fn: ``Resolver.resolve`` bound method injected by the facade.

        Raises:
            UnknownCodeSystemError: If as_codes is not a recognized code system.
            GroupNotFoundError: If group does not resolve to any entity.
            AmbiguousResolutionError: If group resolves ambiguously.
        """
        if as_codes is not None:
            known = self._runner.available_code_systems
            if as_codes not in known:
                raise UnknownCodeSystemError(system=as_codes, available=sorted(known))

        effective_as_of = as_of if as_of is not None else date.today()
        group_entity_id = self.resolve_group_id(group, resolve_fn=resolve_fn)

        if as_of is not None and self.is_snapshot_entity(group_entity_id):
            warnings.warn(
                f"as_of is ignored for snapshot entity {group_entity_id!r}; "
                "the snapshot is frozen by construction.",
                UserWarning,
                stacklevel=3,
            )

        member_ids = sorted(
            set(
                self._runner.get_reverse_relations(
                    entity_id=group_entity_id,
                    relation_type="member_of",
                    as_of=effective_as_of,
                )
            )
        )

        if as_codes is None:
            return member_ids

        codes_set: set[str] = set()
        for eid in member_ids:
            entity = self._runner.get_entity(eid)
            if entity is None:
                continue
            for code in entity.codes:
                if code.system == as_codes:
                    codes_set.add(code.value)
        return sorted(codes_set)

    def is_member(
        self,
        country: str,
        group: str,
        *,
        as_of: date | None = None,
        resolve_fn: Callable[[str], ResolutionResult],
    ) -> bool:
        """Check whether a country is a member of a group on the given date.

        Args:
            country: Country name, code, or entity ID.
            group: Group name, abbreviation, or entity ID.
            as_of: Reference date. Defaults to today.
            resolve_fn: ``Resolver.resolve`` bound method injected by the facade.

        Returns:
            True if the country is a member of the group on the reference date.
        """
        effective_as_of = as_of if as_of is not None else date.today()
        group_entity_id = self.resolve_group_id(group, resolve_fn=resolve_fn)
        country_entity_id = self.resolve_group_id(country, resolve_fn=resolve_fn)

        if as_of is not None and self.is_snapshot_entity(group_entity_id):
            warnings.warn(
                f"as_of is ignored for snapshot entity {group_entity_id!r}; "
                "the snapshot is frozen by construction.",
                UserWarning,
                stacklevel=3,
            )

        return group_entity_id in self._runner.get_relations_as_of(
            entity_id=country_entity_id,
            relation_type="member_of",
            as_of=effective_as_of,
        )

    def known_groups(self) -> list[str]:
        """Return canonical names of all queryable group entities, sorted.

        Returns:
            Sorted list of canonical names (e.g. ["African Union", "ASEAN", ...]).
        """
        names: set[str] = set()
        for entity_type in self._runner.available_group_types:
            for entity in self._runner.list_entities_by_type(entity_type=entity_type):
                if entity.canonical_name:
                    names.add(entity.canonical_name)
        return sorted(names)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def resolve_group_id(
        self, text: str, *, resolve_fn: Callable[[str], ResolutionResult]
    ) -> str:
        """Resolve a group/country string to a single entity_id."""
        from resolvekit.core.api.loading import _resolution_error

        result = resolve_fn(text)
        if result.is_resolved and result.entity_id is not None:
            return result.entity_id
        if result.is_ambiguous:
            raise AmbiguousResolutionError(candidates=list(result.candidates))
        if result.status == ResolutionStatus.ERROR:
            raise _resolution_error(text, result)
        raise GroupNotFoundError(f"No entity found for {text!r}")

    def apply_group_preference_tiebreak(
        self, result: ResolutionResult
    ) -> ResolutionResult:
        """Promote a unique top-2 group candidate from AMBIGUOUS to RESOLVED.

        Fires only when result.is_ambiguous, the top 2 candidates contain
        exactly one entity whose type is in its pack's group_entity_types,
        and that group candidate is at rank 1 or 2.
        """
        if not result.is_ambiguous:
            return result
        if len(result.candidates) < 2:
            return result
        top_two = result.candidates[:2]
        group_typed: list[CandidateSummary] = []
        for cand in top_two:
            if cand.pack_id is None or cand.entity_type is None:
                continue
            pack_types = self._runner.get_pack_group_types(pack_id=cand.pack_id)
            if cand.entity_type in pack_types:
                group_typed.append(cand)
        if len(group_typed) != 1:
            return result
        winner = group_typed[0]
        return result.model_copy(
            update={
                "status": ResolutionStatus.RESOLVED,
                "entity_id": winner.entity_id,
                "confidence": winner.confidence,
                "pack_id": winner.pack_id,
                # match_tier omitted: GROUP_PREFERENCE_TIEBREAK is a decision-level
                # signal, not a match-level signal (e.g. FUZZY).
                "match_tier": None,
                "reasons": [ReasonCode.GROUP_PREFERENCE_TIEBREAK],
            }
        )

    def is_snapshot_entity(self, entity_id: str) -> bool:
        """Return True when any store reports attributes['snapshot'] = True."""
        return self._runner.is_snapshot_entity(entity_id=entity_id)
