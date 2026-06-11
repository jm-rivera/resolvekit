"""Entity merging for overlay composition.

Implements the merge semantics for combining base and overlay entities:
- Scalars: Later pack wins
- Lists (names, codes, relations): Union with deduplication
- Dicts (attributes): Deep merge, later wins on conflict
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

from resolvekit.core.model.entity import (
    EntityRecord,
)

if TYPE_CHECKING:
    from resolvekit.core.linking import Normalizer

T = TypeVar("T")


class EntityMerger:
    """Merges entities from multiple packs.

    Uses a Normalizer for deduplication of names and codes.
    """

    def __init__(self, normalizer: "Normalizer"):
        """Initialize the merger with a normalizer."""
        self._normalizer = normalizer

    def merge(self, base: EntityRecord, overlay: EntityRecord) -> EntityRecord:
        """Merge an overlay entity onto a base entity.

        Merge rules:
        - entity_id, entity_type: Preserved from base
        - canonical_name, canonical_name_norm: Overlay wins if non-empty
        - names: Union with deduplication (normalized value + kind)
        - codes: Union with deduplication (system + normalized value)
        - relations: Union with deduplication (relation_type + target_id)
        - valid_from, valid_until: Overlay wins if not None
        - attributes: Deep merge, overlay wins on conflict
        """
        return EntityRecord(
            entity_id=base.entity_id,
            entity_type=base.entity_type,
            canonical_name=overlay.canonical_name or base.canonical_name,
            canonical_name_norm=overlay.canonical_name_norm or base.canonical_name_norm,
            names=self._merge_with_key(
                base.names,
                overlay.names,
                lambda n: (self._normalizer.normalize_name(n.value), n.kind),
            ),
            codes=self._merge_with_key(
                base.codes,
                overlay.codes,
                lambda c: (
                    c.system,
                    self._normalizer.normalize_code(c.system, c.value),
                ),
            ),
            relations=self._merge_with_key(
                base.relations,
                overlay.relations,
                lambda r: (r.relation_type, r.target_id),
            ),
            valid_from=overlay.valid_from if overlay.valid_from else base.valid_from,
            valid_until=overlay.valid_until
            if overlay.valid_until
            else base.valid_until,
            attributes={**base.attributes, **overlay.attributes},
        )

    def _merge_with_key(
        self,
        base_items: list[T],
        overlay_items: list[T],
        key_fn: Callable[[T], tuple],
    ) -> list[T]:
        """Merge lists with deduplication using a key function.

        Overlay items take precedence; base items added if key not seen.
        """
        seen: set[tuple] = set()
        result: list[T] = []

        for item in overlay_items:
            key = key_fn(item)
            if key not in seen:
                seen.add(key)
                result.append(item)

        for item in base_items:
            key = key_fn(item)
            if key not in seen:
                seen.add(key)
                result.append(item)

        return result
