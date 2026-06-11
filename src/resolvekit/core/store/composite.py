"""CompositeStore for overlay support."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from resolvekit.core.model import EntityRecord
from resolvekit.core.store.interface import EntityStore


class CompositeStore(EntityStore):
    """Wraps multiple stores with overlay precedence.

    The first store has highest priority. Lookups merge results in order,
    preserving precedence and de-duplicating IDs.
    """

    def __init__(self, stores: Iterable[EntityStore]) -> None:
        self._stores = list(stores)

    def close(self) -> None:
        """Close all inner stores."""
        for store in self._stores:
            store.close()

    def get_entity(self, entity_id: str) -> EntityRecord | None:
        for store in self._stores:
            entity = store.get_entity(entity_id)
            if entity is not None:
                return entity
        return None

    def lookup_code(self, system: str, value_norm: str) -> list[str]:
        return self._merge_ids(
            store.lookup_code(system, value_norm) for store in self._stores
        )

    def lookup_code_any(self, value_norm: str) -> list[tuple[str, str]]:
        merged: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for store in self._stores:
            for pair in store.lookup_code_any(value_norm):
                if pair not in seen:
                    seen.add(pair)
                    merged.append(pair)
        return merged

    def lookup_name_exact(
        self, value_norm: str, name_kinds: set[str] | None = None
    ) -> list[str]:
        return self._merge_ids(
            store.lookup_name_exact(value_norm, name_kinds) for store in self._stores
        )

    def search_fulltext(
        self,
        query_norm: str,
        fields: set[str] | None = None,
        limit: int = 10,
    ) -> list[tuple[str, float, int]]:
        # Simple merge: concatenate in store order and trim
        results: list[tuple[str, float, int]] = []
        seen: set[str] = set()
        for store in self._stores:
            remaining = limit - len(results)
            if remaining <= 0:
                break
            for entity_id, score, rank in store.search_fulltext(
                query_norm, fields, remaining
            ):
                if entity_id in seen:
                    continue
                seen.add(entity_id)
                results.append((entity_id, score, rank))
                if len(results) >= limit:
                    return results
        return results

    def bulk_get_entities(self, entity_ids: list[str]) -> dict[str, EntityRecord]:
        # Fill from highest priority store first
        result: dict[str, EntityRecord] = {}
        remaining = list(entity_ids)
        for store in self._stores:
            if not remaining:
                break
            found = store.bulk_get_entities(remaining)
            result.update(found)
            remaining = [eid for eid in remaining if eid not in result]
        return result

    def _merge_ids(self, sequences: Iterable[list[str]]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for ids in sequences:
            for eid in ids:
                if eid in seen:
                    continue
                seen.add(eid)
                merged.append(eid)
        return merged

    def get_relations(
        self, entity_id: str, relation_type: str | None = None
    ) -> list[str]:
        return self._merge_ids(
            store.get_relations(entity_id, relation_type) for store in self._stores
        )

    def search_prefix(
        self, query_norm: str, field: str, limit: int = 10
    ) -> list[tuple[str, float, int]]:
        results: list[tuple[str, float, int]] = []
        seen: set[str] = set()
        for store in self._stores:
            remaining = limit - len(results)
            if remaining <= 0:
                break
            for entity_id, score, rank in store.search_prefix(
                query_norm, field, remaining
            ):
                if entity_id in seen:
                    continue
                seen.add(entity_id)
                results.append((entity_id, score, rank))
                if len(results) >= limit:
                    return results
        return results

    def code_systems(self) -> frozenset[str]:
        merged: set[str] = set()
        for store in self._stores:
            merged.update(store.code_systems())
        return frozenset(merged)

    def iter_suggest_names(
        self,
        *,
        entity_type_prefixes: frozenset[str] | None = None,
        entity_type_exclude_prefixes: frozenset[str] | None = None,
    ) -> Iterator[tuple[str, str, str, bool, str]]:
        """Yield suggest-name 5-tuples from all stores, deduped by entity_id.

        First-store precedence: when the same entity_id appears in multiple
        stores, ALL name rows for that entity from its home (first) store are
        yielded; later stores skip that entity entirely.  This preserves the
        full multi-name row set for each entity (needed for the fuzzy pool),
        unlike a global entity_id dedup which would truncate to the first row.
        """
        seen_entities: set[str] = set()
        for store in self._stores:
            seen_in_this_store: set[str] = set()
            for row in store.iter_suggest_names(
                entity_type_prefixes=entity_type_prefixes,
                entity_type_exclude_prefixes=entity_type_exclude_prefixes,
            ):
                eid = row[1]
                if eid in seen_entities:
                    continue
                seen_in_this_store.add(eid)
                yield row
            seen_entities |= seen_in_this_store

    def search_token_infix(
        self,
        query_norm: str,
        *,
        entity_type_prefixes: frozenset[str] | None = None,
        limit: int = 10,
    ) -> list[tuple[str, float, int]]:
        """Token-infix search across all stores, deduped by entity_id.

        Overlay order: first-store results take precedence.
        """
        results: list[tuple[str, float, int]] = []
        seen: set[str] = set()
        for store in self._stores:
            remaining = limit - len(results)
            if remaining <= 0:
                break
            for entity_id, score, rank in store.search_token_infix(
                query_norm,
                entity_type_prefixes=entity_type_prefixes,
                limit=remaining,
            ):
                if entity_id in seen:
                    continue
                seen.add(entity_id)
                results.append((entity_id, score, rank))
                if len(results) >= limit:
                    return results
        return results
