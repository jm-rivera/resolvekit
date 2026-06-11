"""Exact-match gazetteer baseline adapter.

``GazetteerAdapter`` builds an in-memory lookup table from
:meth:`~resolvekit.core.store.EntityStore.iter_names` at construction time,
then performs a longest-match scan over each document using normalized text.
No heavy external dependencies are required.

Tie-break for collisions (multiple entity IDs sharing the same
``value_norm``): pick the entity with the largest numeric ``population``
attribute from :attr:`~resolvekit.core.model.EntityRecord.attributes`,
falling back to lexicographic ``entity_id`` order for determinism.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from benchmarks.parse.metrics import PredSpan

if TYPE_CHECKING:
    from resolvekit import Resolver

logger = logging.getLogger(__name__)


def _prominence_key(entity_id: str, store) -> tuple[float, str]:  # type: ignore[type-arg]
    """Return a sort key for prominence-based tie-breaking.

    Returns ``(-population, entity_id)`` so that ``min()`` yields the entity
    with the highest population (descending) and lexicographically smallest
    ID on ties.
    """
    record = store.get_entity(entity_id)
    if record is None:
        return (0.0, entity_id)

    pop_raw = record.attributes.get("population", None)
    try:
        population = float(pop_raw) if pop_raw is not None else 0.0
    except (TypeError, ValueError):
        population = 0.0

    # Negate so min() picks highest population.
    return (-population, entity_id)


class GazetteerAdapter:
    """Parse adapter using an exact-match gazetteer built from the entity store.

    Constructs a ``value_norm → entity_id`` mapping once at adapter creation
    by iterating :meth:`~resolvekit.core.store.EntityStore.iter_names`.
    At predict time, normalizes the document text with the resolver's internal
    normalizer and performs a longest-match left-to-right scan.

    Collision tie-break: highest numeric ``population`` attribute wins;
    lexicographic ``entity_id`` as a secondary key ensures determinism.

    Args:
        resolver: A live :class:`~resolvekit.Resolver` instance.
        domain:   Domain pack to build the gazetteer from (default ``"geo"``).
    """

    def __init__(self, resolver: Resolver, *, domain: str = "geo") -> None:
        self._resolver = resolver
        self._domain = domain

        store = resolver.store_for_domain(domain)

        # Build: value_norm → list[entity_id] (there may be collisions).
        raw: dict[str, list[str]] = {}
        for value_norm, entity_id in store.iter_names():
            raw.setdefault(value_norm, []).append(entity_id)

        # Resolve collisions to a single winner via prominence tie-break.
        self._gazetteer: dict[str, tuple[str, str | None]] = {}
        for value_norm, entity_ids in raw.items():
            if len(entity_ids) == 1:
                winner_id = entity_ids[0]
            else:
                winner_id = min(entity_ids, key=lambda eid: _prominence_key(eid, store))

            record = store.get_entity(winner_id)
            entity_type = record.entity_type if record is not None else None
            self._gazetteer[value_norm] = (winner_id, entity_type)

        logger.debug(
            "GazetteerAdapter: built %d entries from domain %r",
            len(self._gazetteer),
            domain,
        )

        self._normalizer = resolver._normalizer  # internal hook for benchmarks

    def predict(self, text: str) -> list[PredSpan]:
        """Longest-match scan over *text* using the gazetteer.

        Normalizes the full text with the resolver's normalizer, then scans
        left-to-right trying progressively shorter windows at each position
        (longest-match-first).  Matched spans are non-overlapping; after a
        match the scan advances past its end.

        Offset mapping: normalizer alignment is character-based (NFC +
        casefold does not change character counts for ASCII/Latin text, which
        is the primary use case).  For simplicity we scan the normalized text
        and use its character offsets as the span offsets, which are
        comparable to the gold set offsets (both reference the same text).

        Args:
            text: Raw document text.

        Returns:
            List of :class:`~benchmarks.parse.metrics.PredSpan` objects.
        """
        if not text.strip():
            return []

        try:
            norm_text = self._normalizer.normalize(text)
        except Exception:
            return []

        spans: list[PredSpan] = []
        tokens = norm_text.split()
        # Build a flat list of (start_char, end_char, token) from norm_text.
        # We scan token windows to find multi-word gazetteer entries.
        token_offsets: list[tuple[int, int]] = []
        pos = 0
        for tok in tokens:
            start = norm_text.find(tok, pos)
            if start == -1:
                pos += len(tok)
                continue
            token_offsets.append((start, start + len(tok)))
            pos = start + len(tok)

        i = 0
        while i < len(token_offsets):
            # Try windows from longest to shortest starting at position i.
            matched = False
            for j in range(len(token_offsets), i, -1):
                window_start = token_offsets[i][0]
                window_end = token_offsets[j - 1][1]
                window_text = norm_text[window_start:window_end]

                if window_text in self._gazetteer:
                    entity_id, entity_type = self._gazetteer[window_text]
                    spans.append(
                        PredSpan(
                            start=window_start,
                            end=window_end,
                            entity_id=entity_id,
                            entity_type=entity_type,
                        )
                    )
                    i = j
                    matched = True
                    break

            if not matched:
                i += 1

        return spans
