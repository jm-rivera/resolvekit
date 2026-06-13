"""StoreView — multi-store data-access union helper.

Wraps an ordered list of ``(pack_id, store)`` pairs and provides the store-read
accessors shared by PipelineRunner (single pair) and MultiPackRunner (multi
pair).  Accessors iterate in insertion order, union results, and dedup by
entity_id; the single-store case is just N=1.
"""

from __future__ import annotations

from datetime import date

from resolvekit.core.model import EntityRecord
from resolvekit.core.store.interface import EntityStore


class StoreView:
    """Multi-store data-access union over an ordered list of ``(pack_id, store)`` pairs.

    Single-pack runners pass one pair; multi-pack runners pass all of their
    ``_stores.items()``.  The union/dedup logic is identical for both.
    """

    def __init__(self, stores: list[tuple[str | None, EntityStore]]) -> None:
        self._stores = stores
        self._relation_type_index: list[frozenset[str] | None] = [
            store.relation_types() for _, store in self._stores
        ]

    # ------------------------------------------------------------------
    # Entity fetch — first non-None wins; no dedup needed
    # ------------------------------------------------------------------

    def get_entity(self, entity_id: str) -> EntityRecord | None:
        """Return the first EntityRecord found for *entity_id*, or None."""
        for _, store in self._stores:
            entity = store.get_entity(entity_id)
            if entity is not None:
                return entity
        return None

    def bulk_get_entities(self, entity_ids: list[str]) -> dict[str, EntityRecord]:
        """Return entities for *entity_ids*, first store wins per ID; missing IDs omitted."""
        result: dict[str, EntityRecord] = {}
        remaining = list(entity_ids)
        for _, store in self._stores:
            if not remaining:
                break
            found = store.bulk_get_entities(remaining)
            result.update(found)
            remaining = [eid for eid in remaining if eid not in result]
        return result

    # ------------------------------------------------------------------
    # Lookups — dedup by entity_id, preserve first-seen order
    # ------------------------------------------------------------------

    def lookup_code(
        self,
        system: str,
        value_norm: str,
        *,
        pack_filter: frozenset[str] | None = None,
    ) -> list[str]:
        """Return entity IDs matching *system*/*value_norm*, deduped."""
        seen: set[str] = set()
        result: list[str] = []
        for pack_id, store in self._stores:
            if pack_filter is not None and pack_id not in pack_filter:
                continue
            for eid in store.lookup_code(system, value_norm):
                if eid not in seen:
                    seen.add(eid)
                    result.append(eid)
        return result

    def lookup_code_attributed(
        self,
        *,
        system: str,
        value_norm: str,
        pack_filter: frozenset[str] | None = None,
    ) -> list[tuple[str, str]]:
        """Return ``(pack_id, entity_id)`` pairs, deduped by entity_id."""
        seen: set[str] = set()
        result: list[tuple[str, str]] = []
        for pack_id, store in self._stores:
            if pack_filter is not None and pack_id not in pack_filter:
                continue
            pid = pack_id or ""
            for eid in store.lookup_code(system, value_norm):
                if eid not in seen:
                    seen.add(eid)
                    result.append((pid, eid))
        return result

    def lookup_name_exact(
        self,
        *,
        value: str,
        pack_filter: frozenset[str] | None = None,
    ) -> list[tuple[str, str]]:
        """Return ``(pack_id, entity_id)`` pairs for an exact name match, deduped."""
        seen: set[str] = set()
        result: list[tuple[str, str]] = []
        for pack_id, store in self._stores:
            if pack_filter is not None and pack_id not in pack_filter:
                continue
            if pack_id is None:
                # Single-pack runner without a declared pack_id returns empty
                continue
            for eid in store.lookup_name_exact(value):
                if eid not in seen:
                    seen.add(eid)
                    result.append((pack_id, eid))
        return result

    # ------------------------------------------------------------------
    # Relations — dedup / union across all stores
    # ------------------------------------------------------------------

    def get_reverse_relations(
        self,
        *,
        entity_id: str,
        relation_type: str,
        as_of: date | None = None,
    ) -> list[str]:
        """Return entity IDs with *relation_type* pointing to *entity_id*, deduped.

        Insertion order is preserved; sorting (multi-pack contract) is the
        caller's responsibility so the single-pack contract (unsorted) is unaffected.
        """
        seen: set[str] = set()
        result: list[str] = []
        for i, (_, store) in enumerate(self._stores):
            rv = self._relation_type_index[i]
            if rv is not None and relation_type not in rv:
                continue
            for eid in store.get_reverse_relations(
                entity_id, relation_type, as_of=as_of
            ):
                if eid not in seen:
                    seen.add(eid)
                    result.append(eid)
        return result

    def get_relations_as_of(
        self,
        *,
        entity_id: str,
        relation_type: str,
        as_of: date,
    ) -> frozenset[str]:
        """Return target entity IDs for relations active on *as_of*, unioned."""
        result: set[str] = set()
        for i, (_, store) in enumerate(self._stores):
            rv = self._relation_type_index[i]
            if rv is not None and relation_type not in rv:
                continue
            result.update(store.get_relations_as_of(entity_id, relation_type, as_of))
        return frozenset(result)

    # ------------------------------------------------------------------
    # Listings & metadata — dedup / union across all stores
    # ------------------------------------------------------------------

    def list_entities_by_type(
        self,
        *,
        entity_type: str,
    ) -> list[EntityRecord]:
        """Return all entities of *entity_type* across all stores, deduped."""
        seen: set[str] = set()
        result: list[EntityRecord] = []
        for _, store in self._stores:
            for entity in store.list_entities_by_type(entity_type):
                if entity.entity_id not in seen:
                    seen.add(entity.entity_id)
                    result.append(entity)
        return result

    def available_code_systems(self) -> frozenset[str]:
        """Return the union of code systems across all stores."""
        systems: set[str] = set()
        for _, store in self._stores:
            systems.update(store.code_systems())
        return frozenset(systems)

    def is_snapshot_entity(self, *, entity_id: str) -> bool:
        """Return True when any store reports ``attributes['snapshot'] = True``."""
        for _, store in self._stores:
            entity = store.get_entity(entity_id)
            if entity is not None and entity.attributes.get("snapshot", False):
                return True
        return False
