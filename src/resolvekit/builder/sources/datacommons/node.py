"""Shared node-parsing helpers for Data Commons dc_api modules."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Collection, Iterable, Mapping
from typing import Any

from resolvekit.builder.sources.datacommons.constants import (
    ALIAS_TEXT_KEY,
    ALIAS_TYPE_KEY,
    CODE_SYSTEM_KEY,
    CODE_VALUE_KEY,
    DATACOMMONS_SOURCE,
    DEFAULT_LANGUAGE,
    LANGUAGE_KEY,
    NODE_DCID_ATTR,
    NODE_PROVENANCE_ATTR,
    NODE_VALUE_ATTR,
    SOURCE_KEY,
)
from resolvekit.builder.sources.datacommons.models import FetchedName

GENERIC_ENTITY_TYPES = frozenset({"Thing", "Place", "Class", "ProvisionalNode"})


def node_string(node: Any) -> str | None:
    """Extract a non-empty string from a DC node object or plain string."""
    if isinstance(node, str):
        stripped = node.strip()
        return stripped or None
    value = getattr(node, NODE_VALUE_ATTR, None)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    dcid = getattr(node, NODE_DCID_ATTR, None)
    if isinstance(dcid, str):
        stripped = dcid.strip()
        if stripped:
            return stripped
    return None


def node_scalar_string(node: Any) -> str | None:
    """Extract a non-empty scalar string from a DC node object."""
    if isinstance(node, str):
        stripped = node.strip()
        return stripped or None
    value = getattr(node, NODE_VALUE_ATTR, None)
    if value is not None:
        stripped = str(value).strip()
        if stripped:
            return stripped
    dcid = getattr(node, NODE_DCID_ATTR, None)
    if dcid is not None:
        stripped = str(dcid).strip()
        if stripped:
            return stripped
    return None


def build_code_rows(
    raw: dict[str, dict[str, list[Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Build code rows from raw property-values response."""
    out: dict[str, list[dict[str, Any]]] = {}
    for entity_id, props in raw.items():
        code_rows: list[dict[str, Any]] = []
        for system, nodes in props.items():
            for node in nodes:
                value = node_scalar_string(node)
                if value is None:
                    continue
                code_rows.append(
                    {
                        CODE_SYSTEM_KEY: system,
                        CODE_VALUE_KEY: value,
                        SOURCE_KEY: getattr(node, NODE_PROVENANCE_ATTR, None),
                    }
                )
        out[entity_id] = code_rows
    return out


def alias_entry(
    *,
    language: str,
    alias_text: str,
    alias_type: str,
    source: str | None,
) -> dict[str, Any]:
    """Build a single alias row dict."""
    return {
        LANGUAGE_KEY: language.lower(),
        ALIAS_TEXT_KEY: alias_text,
        ALIAS_TYPE_KEY: alias_type,
        SOURCE_KEY: source,
    }


def is_acronym_like(alias_text: str) -> bool:
    """Return whether a short label looks like an acronym."""
    compact = (
        alias_text.replace(".", "")
        .replace("-", "")
        .replace("/", "")
        .replace("&", "")
        .strip()
    )
    return 2 <= len(compact) <= 12 and compact.isupper() and " " not in compact


def build_alias_rows_from_properties(
    raw: dict[str, dict[str, list[Any]]],
    *,
    property_roles: Mapping[str, str],
    canonical_names: Mapping[str, str] | None = None,
    default_language: str = DEFAULT_LANGUAGE,
) -> dict[str, list[dict[str, Any]]]:
    """Build alias rows from property values using property-role mappings."""
    out: dict[str, list[dict[str, Any]]] = {}
    canonical_names = canonical_names or {}
    for entity_id, props in raw.items():
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        canonical_name = canonical_names.get(entity_id, "").strip()
        for property_name, alias_role in property_roles.items():
            for node in props.get(property_name, []):
                alias_text = node_scalar_string(node)
                if not alias_text or alias_text == canonical_name:
                    continue
                alias_type = alias_role
                if alias_role == "short_name" and is_acronym_like(alias_text):
                    alias_type = "acronym"
                key = (default_language.lower(), alias_type, alias_text)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    alias_entry(
                        language=default_language,
                        alias_text=alias_text,
                        alias_type=alias_type,
                        source=getattr(node, NODE_PROVENANCE_ATTR, None),
                    )
                )
        out[entity_id] = rows
    return out


def build_alias_rows_from_names(
    names_by_entity: Mapping[str, FetchedName],
    *,
    canonical_names: Mapping[str, str] | None = None,
    alias_type: str = "alias",
    source: str = DATACOMMONS_SOURCE,
) -> dict[str, list[dict[str, Any]]]:
    """Build alias rows from structured name rows."""
    out: dict[str, list[dict[str, Any]]] = {}
    canonical_names = canonical_names or {}
    for entity_id, name in names_by_entity.items():
        alias_text = name.value.strip()
        if not alias_text or alias_text == canonical_names.get(entity_id, "").strip():
            out[entity_id] = []
            continue
        out[entity_id] = [
            alias_entry(
                language=name.language or DEFAULT_LANGUAGE,
                alias_text=alias_text,
                alias_type=alias_type,
                source=source,
            )
        ]
    return out


def merge_alias_rows(
    *mappings: Mapping[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Merge alias mappings while preserving order and removing duplicates."""
    out: dict[str, list[dict[str, Any]]] = {}
    seen_by_entity: dict[str, set[tuple[str, str, str, str | None]]] = {}
    for mapping in mappings:
        for entity_id, rows in mapping.items():
            entity_rows = out.setdefault(entity_id, [])
            seen = seen_by_entity.setdefault(entity_id, set())
            for row in rows:
                key = (
                    str(row.get(LANGUAGE_KEY, DEFAULT_LANGUAGE)).lower(),
                    str(row.get(ALIAS_TYPE_KEY, "alias")),
                    str(row.get(ALIAS_TEXT_KEY, "")),
                    row.get(SOURCE_KEY),
                )
                if key in seen:
                    continue
                seen.add(key)
                entity_rows.append(dict(row))
    return out


def build_scalar_attrs(
    raw: dict[str, dict[str, list[Any]]],
    *,
    property_names: Mapping[str, str],
) -> dict[str, dict[str, str]]:
    """Build scalar attrs from property values using property->attr mappings."""
    out: dict[str, dict[str, str]] = {}
    for entity_id, props in raw.items():
        attrs: dict[str, str] = {}
        for property_name, attr_name in property_names.items():
            values = props.get(property_name, [])
            if not values:
                continue
            if value := node_scalar_string(values[0]):
                attrs[attr_name] = value
        out[entity_id] = attrs
    return out


def select_preferred_type(
    raw_types: Iterable[Any],
    *,
    rank_by_type: Mapping[str, int] | None = None,
    allowed_types: Collection[str] | None = None,
    generic_types: Collection[str] = GENERIC_ENTITY_TYPES,
) -> str | None:
    """Select the most specific raw type from a node's ``typeOf`` values."""
    ordered: list[str] = []
    seen: set[str] = set()
    for raw_type in raw_types:
        value = raw_type.strip() if isinstance(raw_type, str) else node_string(raw_type)
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)

    if not ordered:
        return None

    candidates = [value for value in ordered if value not in generic_types]
    if allowed_types:
        allowed_specific = [value for value in candidates if value in allowed_types]
        allowed_fallback = [value for value in ordered if value in allowed_types]
        if allowed_specific:
            candidates = allowed_specific
        elif allowed_fallback:
            candidates = allowed_fallback
    elif not candidates:
        candidates = ordered

    if not candidates:
        candidates = ordered

    if rank_by_type is None:
        return candidates[0]

    return max(
        enumerate(candidates),
        key=lambda item: (rank_by_type.get(item[1], 0), -item[0]),
    )[1]


def walk_type_families(
    *,
    roots: Iterable[str],
    fetch_children: Callable[[str], list[str]],
) -> tuple[dict[str, int], dict[str, str]]:
    """Walk a type subtree and return depth and root-family mappings."""
    depth_by_type: dict[str, int] = {}
    family_by_type: dict[str, str] = {}
    queue = deque((root, 0, root) for root in roots)

    while queue:
        raw_type, depth, family = queue.popleft()
        if raw_type in depth_by_type:
            continue
        depth_by_type[raw_type] = depth
        family_by_type[raw_type] = family
        for child in fetch_children(raw_type):
            queue.append((child, depth + 1, family))

    return depth_by_type, family_by_type
