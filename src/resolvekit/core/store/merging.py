"""MergingCompositeStore for overlay composition with entity merging."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from resolvekit.core.merge import EntityMerger
from resolvekit.core.model import EntityRecord
from resolvekit.core.store.interface import EntityStore

if TYPE_CHECKING:
    from resolvekit.core.linking import Normalizer


@dataclass(frozen=True)
class OverlayPolicy:
    """Enforcement policy for an overlay store."""

    allow_new_entities: bool = False


class MergingCompositeStore(EntityStore):
    """Wraps multiple stores with overlay merging.

    Unlike CompositeStore which returns first-match, MergingCompositeStore
    merges entities from all stores in order, applying full merge semantics:
    - Scalars: Later store wins
    - Lists: Union with deduplication
    - Dicts: Deep merge, later wins on conflict

    Stores are ordered base-first, overlays after in precedence order.
    """

    def __init__(
        self,
        stores: list[EntityStore],
        normalizer: Normalizer,
        overlay_policies: list[OverlayPolicy | None] | None = None,
    ) -> None:
        """Initialize MergingCompositeStore.

        Args:
            stores: List of stores, base first, overlays in precedence order
            normalizer: Domain-specific normalizer for merge deduplication
            overlay_policies: Per-store policies; None = base store (no policy)
        """
        self._stores = list(stores)
        self._merger = EntityMerger(normalizer)
        self._overlay_policies = overlay_policies or [None] * len(self._stores)

        # Pre-compute base entity IDs for enforcement
        self._base_entity_ids: set[str] | None = None
        if any(
            p is not None and not p.allow_new_entities for p in self._overlay_policies
        ):
            base_ids: set[str] = set()
            for i, store in enumerate(self._stores):
                if self._overlay_policies[i] is None and hasattr(
                    store, "all_entity_ids"
                ):
                    base_ids.update(store.all_entity_ids())
            self._base_entity_ids = base_ids

    def _is_overlay_blocked(self, store_index: int, entity_id: str) -> bool:
        """Check if an entity from an overlay store should be filtered out."""
        if self._base_entity_ids is None:
            return False
        policy = self._overlay_policies[store_index]
        if policy is None or policy.allow_new_entities:
            return False
        return entity_id not in self._base_entity_ids

    def close(self) -> None:
        """Close all inner stores."""
        for store in self._stores:
            store.close()

    def get_entity(self, entity_id: str) -> EntityRecord | None:
        """Get entity, merging from all stores.

        Collects entity from each store that has it, then merges
        in order (base first, overlays after). Overlay entities that
        introduce new IDs when allow_new_entities=False are filtered out.
        """
        entities: list[EntityRecord] = []

        for i, store in enumerate(self._stores):
            entity = store.get_entity(entity_id)
            if entity is not None:
                if self._is_overlay_blocked(i, entity_id):
                    continue
                entities.append(entity)

        if not entities:
            return None

        if len(entities) == 1:
            return entities[0]

        merged = entities[0]
        for overlay in entities[1:]:
            merged = self._merger.merge(merged, overlay)

        return merged

    def lookup_code(self, system: str, value_norm: str) -> list[str]:
        """Lookup by code, merging IDs from all stores."""
        return self._merge_ids_indexed(
            (i, store.lookup_code(system, value_norm))
            for i, store in enumerate(self._stores)
        )

    def lookup_code_any(self, value_norm: str) -> list[tuple[str, str]]:
        """Lookup across all code systems, merging with overlay filtering."""
        merged: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for i, store in enumerate(self._stores):
            for entity_id, system in store.lookup_code_any(value_norm):
                pair = (entity_id, system)
                if pair in seen:
                    continue
                if self._is_overlay_blocked(i, entity_id):
                    continue
                seen.add(pair)
                merged.append(pair)
        return merged

    def lookup_name_exact(
        self, value_norm: str, name_kinds: set[str] | None = None
    ) -> list[str]:
        """Lookup by exact name, merging IDs from all stores."""
        return self._merge_ids_indexed(
            (i, store.lookup_name_exact(value_norm, name_kinds))
            for i, store in enumerate(self._stores)
        )

    def search_fulltext(
        self,
        query_norm: str,
        fields: set[str] | None = None,
        limit: int = 10,
    ) -> list[tuple[str, float, int]]:
        """Search fulltext, merging results from all stores."""
        results: list[tuple[str, float, int]] = []
        seen: set[str] = set()

        for i, store in enumerate(self._stores):
            remaining = limit - len(results)
            if remaining <= 0:
                break
            for entity_id, score, rank in store.search_fulltext(
                query_norm, fields, remaining
            ):
                if entity_id in seen:
                    continue
                if self._is_overlay_blocked(i, entity_id):
                    continue
                seen.add(entity_id)
                results.append((entity_id, score, rank))
                if len(results) >= limit:
                    return results

        return results

    def bulk_get_entities(self, entity_ids: list[str]) -> dict[str, EntityRecord]:
        """Bulk get entities, merging each from all stores."""
        if not entity_ids:
            return {}

        store_results: list[tuple[int, dict[str, EntityRecord]]] = [
            (i, store.bulk_get_entities(entity_ids))
            for i, store in enumerate(self._stores)
        ]

        result: dict[str, EntityRecord] = {}
        all_ids = {eid for _, sr in store_results for eid in sr}

        for eid in all_ids:
            entities = [
                sr[eid]
                for i, sr in store_results
                if eid in sr and not self._is_overlay_blocked(i, eid)
            ]

            if not entities:
                continue

            if len(entities) == 1:
                result[eid] = entities[0]
            else:
                merged = entities[0]
                for overlay in entities[1:]:
                    merged = self._merger.merge(merged, overlay)
                result[eid] = merged

        return result

    def _merge_ids_indexed(
        self, indexed_sequences: Iterable[tuple[int, list[str]]]
    ) -> list[str]:
        """Merge ID lists preserving order, deduplicating, and filtering overlays."""
        merged: list[str] = []
        seen: set[str] = set()

        for store_index, ids in indexed_sequences:
            for eid in ids:
                if eid in seen:
                    continue
                if self._is_overlay_blocked(store_index, eid):
                    continue
                seen.add(eid)
                merged.append(eid)

        return merged

    def get_relations(
        self, entity_id: str, relation_type: str | None = None
    ) -> list[str]:
        """Lookup relations, merging IDs from all stores."""
        return self._merge_ids_indexed(
            (i, store.get_relations(entity_id, relation_type))
            for i, store in enumerate(self._stores)
        )

    def search_prefix(
        self, query_norm: str, field: str, limit: int = 10
    ) -> list[tuple[str, float, int]]:
        """Search prefixes, merging results from all stores."""
        results: list[tuple[str, float, int]] = []
        seen: set[str] = set()
        for i, store in enumerate(self._stores):
            remaining = limit - len(results)
            if remaining <= 0:
                break
            for entity_id, score, rank in store.search_prefix(
                query_norm, field, remaining
            ):
                if entity_id in seen:
                    continue
                if self._is_overlay_blocked(i, entity_id):
                    continue
                seen.add(entity_id)
                results.append((entity_id, score, rank))
                if len(results) >= limit:
                    return results
        return results

    def code_systems(self) -> frozenset[str]:
        """Union of code systems across all stores."""
        merged: set[str] = set()
        for store in self._stores:
            merged.update(store.code_systems())
        return frozenset(merged)
