"""Reusable Data Commons client access, retries, and chunked query helpers."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from importlib import import_module
from threading import BoundedSemaphore
from typing import Any, TypeVar

from resolvekit.builder.sources.datacommons.constants import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_LANGUAGE,
    DEFAULT_MAX_CONCURRENT_REQUESTS,
    NODE_DCID_ATTR,
    PUBLIC_DC_INSTANCE,
)
from resolvekit.builder.sources.datacommons.models import FetchedName
from resolvekit.builder.sources.datacommons.node import node_string
from resolvekit.builder.utils import chunk_list

T = TypeVar("T")

# HTTP 429 (rate-limit) handling for requests through the concurrency limiter.
# The public Data Commons instances are fronted by a WAF that throttles bursty
# clients; on 429 we wait the server's Retry-After (when present) or an
# exponential backoff, rather than failing the chunk after a few fast retries.
_RATE_LIMIT_STATUS = 429
_RATE_LIMIT_MAX_RETRIES = 6
_RATE_LIMIT_BASE_DELAY_SEC = 2.0
_RATE_LIMIT_MAX_DELAY_SEC = 120.0


def _is_rate_limited(exc: BaseException) -> bool:
    """Return True if the exception represents an HTTP 429 response."""
    for status in (
        getattr(exc, "status_code", None),
        getattr(getattr(exc, "response", None), "status_code", None),
    ):
        if status == _RATE_LIMIT_STATUS:
            return True
    return f"Status Code: {_RATE_LIMIT_STATUS}" in str(exc)


def _retry_after_seconds(exc: BaseException) -> float | None:
    """Return the Retry-After delay (seconds) from a 429 response, if given.

    Honors both the integer-seconds and HTTP-date forms of the header. Returns
    None when the header is absent or unparseable, signalling the caller to fall
    back to its own backoff schedule.
    """
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if not headers:
        return None
    raw = headers.get("Retry-After")
    if raw is None:
        return None
    raw = str(raw).strip()
    if raw.isdigit():
        return float(raw)
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _load_datacommons_client_class() -> Any | None:
    """Load the optional Data Commons client class at runtime."""
    try:
        return import_module("datacommons_client").DataCommonsClient
    except ImportError:
        return None


class DataCommons:
    """Thin runtime wrapper around the Data Commons Python client."""

    def __init__(
        self,
        *,
        dc_instance: str,
        api_key: str | None = None,
        default_chunk_size: int = DEFAULT_CHUNK_SIZE,
        max_concurrent_requests: int = DEFAULT_MAX_CONCURRENT_REQUESTS,
    ) -> None:
        self._dc_instance = dc_instance
        self._api_key = api_key
        self._default_chunk_size = default_chunk_size
        self._request_limiter = BoundedSemaphore(value=max_concurrent_requests)
        self._client: Any | None = None

    def with_retries(
        self,
        fn: Callable[..., T],
        *,
        retries: int = 2,
        base_delay: float = 0.5,
        factor: float = 2.0,
        max_delay: float = 8.0,
        **kwargs: Any,
    ) -> T:
        """Call ``fn`` with bounded exponential backoff retries."""
        delay = base_delay
        for attempt in range(retries + 1):
            try:
                return fn(**kwargs)
            except Exception:
                if attempt >= retries:
                    raise
                time.sleep(delay)
                delay = min(delay * factor, max_delay)
        raise RuntimeError("Retry loop exhausted unexpectedly.")

    def chunks(
        self,
        values: list[str],
        size: int | None = None,
    ) -> Iterable[list[str]]:
        """Yield list slices for chunked Data Commons requests."""
        chunk_size = size or self._default_chunk_size
        yield from chunk_list(values, chunk_size)

    def _call_limited(
        self,
        fn: Callable[..., T],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Run one request under the concurrency limiter, retrying on HTTP 429.

        Non-429 errors propagate immediately (callers such as the place-children
        splitter depend on that). Rate-limit responses back off outside the
        limiter — honoring the server's Retry-After header when present — and
        retry, so a throttling instance is waited out instead of failing the
        chunk after a handful of fast attempts.
        """
        delay = _RATE_LIMIT_BASE_DELAY_SEC
        for attempt in range(_RATE_LIMIT_MAX_RETRIES + 1):
            try:
                with self._request_limiter:
                    return fn(*args, **kwargs)
            except Exception as exc:
                if not _is_rate_limited(exc) or attempt >= _RATE_LIMIT_MAX_RETRIES:
                    raise
                retry_after = _retry_after_seconds(exc)
            wait = retry_after if retry_after is not None else delay
            time.sleep(min(wait, _RATE_LIMIT_MAX_DELAY_SEC))
            delay = min(delay * 2.0, _RATE_LIMIT_MAX_DELAY_SEC)
        raise RuntimeError("Rate-limit retry loop exhausted unexpectedly.")

    def client_or_raise(self) -> Any:
        """Return initialized Data Commons client or raise dependency error."""
        if self._client is not None:
            return self._client

        client_class = _load_datacommons_client_class()
        if client_class is None:
            raise RuntimeError(
                "datacommons-client is required for Data Commons adapters. "
                "Install the optional data dependencies first."
            )

        self._client = client_class(**self._client_kwargs())
        return self._client

    def _client_kwargs(self) -> dict[str, Any]:
        """Build constructor kwargs for the Data Commons Python client."""
        instance = self._dc_instance.strip()
        api_key = self._resolved_api_key()
        kwargs: dict[str, Any] = {}

        if api_key:
            kwargs["api_key"] = api_key

        if instance.startswith(("https://", "http://")):
            kwargs["url"] = self._resolve_base_url(instance)
            return kwargs

        normalized_instance = instance.strip("/")
        kwargs["dc_instance"] = normalized_instance or PUBLIC_DC_INSTANCE
        return kwargs

    def _resolved_api_key(self) -> str | None:
        """Resolve API key from explicit config or environment."""
        if self._api_key:
            return self._api_key
        return os.getenv("DATACOMMONS_API_KEY") or os.getenv("DATA_COMMONS_API_KEY")

    def _resolve_base_url(self, value: str) -> str:
        """Normalize an instance or URL into a v2 API base URL."""
        url = value.rstrip("/")
        if url.endswith("/core/api/v2") or url.endswith("/v2"):
            return url
        if url.startswith(("https://", "http://")):
            return f"{url}/core/api/v2"
        return f"https://{url}/core/api/v2"

    def fetch_entity_names(
        self,
        entity_ids: list[str],
        *,
        lang: str = DEFAULT_LANGUAGE,
    ) -> dict[str, str]:
        """Fetch names for entities, chunking requests as needed."""
        return {
            entity_id: name.value
            for entity_id, name in self.fetch_entity_name_rows(
                entity_ids,
                lang=lang,
            ).items()
        }

    def fetch_entity_name_rows(
        self,
        entity_ids: list[str],
        *,
        lang: str = DEFAULT_LANGUAGE,
        fallback_lang: str | None = None,
    ) -> dict[str, FetchedName]:
        """Fetch structured names for entities, preserving language metadata."""
        dc = self.client_or_raise()
        out: dict[str, FetchedName] = {}
        for chunk in self.chunks(entity_ids):
            rows = self._call_limited(
                dc.node.fetch_entity_names,
                entity_dcids=chunk,
                language=lang,
                fallback_language=fallback_lang,
            )
            for entity_id, value in rows.items():
                node_value = str(getattr(value, "value", "") or "").strip()
                if not node_value:
                    continue
                out[str(entity_id)] = FetchedName(
                    value=node_value,
                    language=str(getattr(value, "language", lang) or lang).lower(),
                    property=str(getattr(value, "property", "name") or "name"),
                )
        return out

    def fetch_all_classes(self) -> list[str]:
        """Fetch all schema classes available in the configured instance."""
        dc = self.client_or_raise()
        rows = self._call_limited(dc.node.fetch_all_classes).get_properties()
        classes: list[str] = []
        for props in rows.values():
            for nodes in props.values():
                for node in nodes:
                    if class_name := node_string(node):
                        classes.append(class_name)
        return list(dict.fromkeys(classes))

    def fetch_property_values(
        self,
        entity_ids: list[str],
        properties: list[str],
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        **kwargs: Any,
    ) -> dict[str, dict[str, list[Any]]]:
        """Fetch node property values in chunks and return merged dict payload."""
        dc = self.client_or_raise()
        out: dict[str, dict[str, list[Any]]] = {}
        for chunk in self.chunks(entity_ids, size=chunk_size):
            rows = self._call_limited(
                dc.node.fetch_property_values,
                node_dcids=chunk,
                properties=properties,
                **kwargs,
            ).get_properties()
            for entity_id, props in rows.items():
                out[str(entity_id)] = dict(props)
        return out

    def fetch_property_labels(
        self,
        entity_ids: list[str],
        *,
        out: bool = True,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> dict[str, list[str]]:
        """Fetch outgoing or incoming property labels for the given entities."""
        dc = self.client_or_raise()
        labels_by_entity: dict[str, list[str]] = {}
        for chunk in self.chunks(entity_ids, size=chunk_size):
            rows = self._call_limited(
                dc.node.fetch_property_labels,
                node_dcids=chunk,
                out=out,
            ).get_properties()
            for entity_id, props in rows.items():
                if isinstance(props, dict):
                    labels = list(props.keys())
                else:
                    labels = [str(label) for label in props]
                labels_by_entity[str(entity_id)] = list(dict.fromkeys(labels))
        return labels_by_entity

    def fetch_place_children(self, *, place_type: str, parent_place: str) -> list[str]:
        """Fetch direct place children for one parent place and child type."""
        dc = self.client_or_raise()
        rows = self._call_limited(
            dc.node.fetch_place_children,
            place_dcids=[parent_place],
            children_type=place_type,
        ).get(parent_place, [])
        return [
            str(row[NODE_DCID_ATTR])
            for row in rows
            if isinstance(row, dict) and NODE_DCID_ATTR in row
        ]

    def fetch_place_children_for_parents(
        self,
        *,
        place_type: str,
        parent_places: list[str],
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        max_workers: int = 1,
        on_chunk_complete: Callable[[int, list[str], dict[str, list[str]]], None]
        | None = None,
    ) -> dict[str, list[str]]:
        """Fetch direct place children for multiple parent places."""
        if not parent_places:
            return {}

        out: dict[str, list[str]] = {}
        unique_parents = list(dict.fromkeys(parent_places))
        parent_chunks = list(self.chunks(unique_parents, size=chunk_size))
        worker_count = min(max(1, max_workers), len(parent_chunks))

        if worker_count == 1:
            for batch_index, chunk in enumerate(parent_chunks):
                result = self._fetch_place_children_with_split(
                    place_type=place_type,
                    parent_chunk=chunk,
                )
                out.update(result)
                if on_chunk_complete is not None:
                    on_chunk_complete(batch_index, chunk, result)
            return out

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    self._fetch_place_children_with_split,
                    place_type=place_type,
                    parent_chunk=chunk,
                ): (batch_index, chunk)
                for batch_index, chunk in enumerate(parent_chunks)
            }
            for future in as_completed(futures):
                batch_index, chunk = futures[future]
                result = future.result()
                out.update(result)
                if on_chunk_complete is not None:
                    on_chunk_complete(batch_index, chunk, result)
        return out

    def _fetch_place_children_with_split(
        self,
        *,
        place_type: str,
        parent_chunk: list[str],
    ) -> dict[str, list[str]]:
        """Fetch children for one parent chunk and split on oversized failures."""
        dc = self.client_or_raise()
        try:
            rows_by_parent = self._call_limited(
                dc.node.fetch_place_children,
                place_dcids=parent_chunk,
                children_type=place_type,
            )
        except Exception:
            if len(parent_chunk) <= 1:
                raise
            midpoint = len(parent_chunk) // 2
            left = self._fetch_place_children_with_split(
                place_type=place_type,
                parent_chunk=parent_chunk[:midpoint],
            )
            right = self._fetch_place_children_with_split(
                place_type=place_type,
                parent_chunk=parent_chunk[midpoint:],
            )
            return {**left, **right}

        out: dict[str, list[str]] = {}
        for parent_place, rows in rows_by_parent.items():
            children = [
                str(row[NODE_DCID_ATTR])
                for row in rows or []
                if isinstance(row, dict) and NODE_DCID_ATTR in row
            ]
            out[str(parent_place)] = children
        return out

    def fetch_observations(
        self,
        entity_ids: list[str],
        *,
        variable_dcid: str,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> dict[str, float]:
        """Return {entity_id: latest_observation_value} for a statvar."""
        dc = self.client_or_raise()
        out: dict[str, float] = {}
        for chunk in self.chunks(entity_ids, size=chunk_size):
            response = self._call_limited(
                dc.observation.fetch_observations_by_entity_dcid,
                date="LATEST",
                entity_dcids=chunk,
                variable_dcids=[variable_dcid],
            )
            data = response.get_data_by_entity()
            for var_data in data.values():
                for entity_id, facets in var_data.items():
                    if facets.orderedFacets:
                        obs_list = facets.orderedFacets[0].observations
                        if obs_list and obs_list[0].value is not None:
                            out[str(entity_id)] = float(obs_list[0].value)
        return out

    def fetch_place_parents(self, entity_ids: list[str]) -> dict[str, list[str]]:
        """Fetch place parents for entity IDs in chunks."""
        dc = self.client_or_raise()
        out: dict[str, list[str]] = {}
        for chunk in self.chunks(entity_ids):
            rows = self._call_limited(
                dc.node.fetch_place_parents,
                chunk,
                as_dict=True,
            )
            for entity_id, parent_rows in rows.items():
                parents = [
                    str(parent[NODE_DCID_ATTR])
                    for parent in parent_rows or []
                    if isinstance(parent, dict) and NODE_DCID_ATTR in parent
                ]
                if parents:
                    out[str(entity_id)] = parents
        return out
