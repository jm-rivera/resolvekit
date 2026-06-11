"""Chunk-callback adapter for GeoDcApi.get_places_by_parents."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from functools import lru_cache

from resolvekit.builder.sources.datacommons.geo.dc_api import GeoDcApi
from resolvekit.builder.sources.datacommons.geo.mappings import (
    DISCOVERY_MAX_WORKERS,
    DISCOVERY_PARENT_BATCH_SIZE,
)
from resolvekit.builder.sources.protocol import RetryFn


@lru_cache(maxsize=8)
def _supports_on_chunk_complete(cls: type) -> bool:
    """Return True if the dc_api class's get_places_by_parents accepts on_chunk_complete."""
    method = getattr(cls, "get_places_by_parents", None)
    if method is None:
        return False
    return "on_chunk_complete" in inspect.signature(method).parameters


def call_get_places_by_parents_with_progress(
    *,
    dc_api: GeoDcApi,
    with_retries: RetryFn,
    place_type: str,
    parent_places: list[str],
    on_chunk_complete: Callable[[int, dict[str, list[str]]], None],
    discovery_parent_batch_size: int = DISCOVERY_PARENT_BATCH_SIZE,
) -> tuple[dict[str, list[str]], bool]:
    """Call dc_api.get_places_by_parents with optional per-chunk callback.

    Returns (results_by_parent, callback_seen) where callback_seen is True
    iff the dc_api class supports on_chunk_complete and the callback fired
    at least once. Callers use callback_seen=False as the signal to
    synthesize batches inline (sync-fallback path).
    """
    supports_callback = _supports_on_chunk_complete(type(dc_api))

    if supports_callback:
        callback_seen = False

        def _callback(
            batch_index: int,
            _parent_chunk: list[str],
            batch_result: dict[str, list[str]],
        ) -> None:
            nonlocal callback_seen
            callback_seen = True
            on_chunk_complete(batch_index, batch_result)

        result = with_retries(
            dc_api.get_places_by_parents,
            place_type=place_type,
            parent_places=parent_places,
            chunk_size=discovery_parent_batch_size,
            max_workers=DISCOVERY_MAX_WORKERS,
            on_chunk_complete=_callback,
        )
        return result, callback_seen

    result = with_retries(
        dc_api.get_places_by_parents,
        place_type=place_type,
        parent_places=parent_places,
        chunk_size=discovery_parent_batch_size,
        max_workers=DISCOVERY_MAX_WORKERS,
    )
    return result, False
