"""Shared raw bundle builders for Data Commons adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel

from resolvekit.builder.sources.datacommons.models import (
    RawAlias,
    RawChunk,
    RawCode,
    RawEntity,
    RawRelation,
)


def relation_rows_from_targets(
    targets_by_entity: Mapping[str, Sequence[str]],
    *,
    relation_type: str,
) -> dict[str, list[RawRelation]]:
    """Convert entity->target-id mappings into typed relation rows."""
    return {
        entity_id: [
            RawRelation(
                relation_type=relation_type,
                target_id=str(target_id).strip(),
            )
            for target_id in target_ids
            if str(target_id).strip()
        ]
        for entity_id, target_ids in targets_by_entity.items()
    }


def build_raw_chunk(
    *,
    entity_ids: list[str],
    canonical_names: Mapping[str, str],
    entity_types: Mapping[str, str],
    attrs_by_entity: Mapping[str, Mapping[str, Any]] | None = None,
    aliases_by_entity: Mapping[str, Sequence[RawAlias | Mapping[str, Any]]]
    | None = None,
    codes_by_entity: Mapping[str, Sequence[RawCode | Mapping[str, Any]]] | None = None,
    relations_by_entity: Mapping[str, Sequence[RawRelation | Mapping[str, Any]]]
    | None = None,
    default_entity_type: str = "Other",
) -> RawChunk:
    """Build canonical raw chunk model from per-entity maps."""
    return RawChunk(
        entities={
            entity_id: _build_entity(
                entity_id=entity_id,
                canonical_names=canonical_names,
                entity_types=entity_types,
                attrs_by_entity=attrs_by_entity,
                default_entity_type=default_entity_type,
            )
            for entity_id in entity_ids
        },
        aliases={
            entity_id: _rows_for_entity(
                RawAlias,
                aliases_by_entity,
                entity_id,
            )
            for entity_id in entity_ids
        },
        codes={
            entity_id: _rows_for_entity(
                RawCode,
                codes_by_entity,
                entity_id,
            )
            for entity_id in entity_ids
        },
        relations={
            entity_id: _rows_for_entity(
                RawRelation,
                relations_by_entity,
                entity_id,
            )
            for entity_id in entity_ids
        },
    )


def _coerce_rows[ModelT: BaseModel](
    model_type: type[ModelT],
    rows: Sequence[ModelT | Mapping[str, Any]],
) -> list[ModelT]:
    """Coerce heterogeneous model/dict rows into typed model rows."""
    out: list[ModelT] = []
    for row in rows:
        if isinstance(row, model_type):
            out.append(row)
        else:
            out.append(model_type.model_validate(row))
    return out


def _rows_for_entity[ModelT: BaseModel](
    model_type: type[ModelT],
    source: Mapping[str, Sequence[ModelT | Mapping[str, Any]]] | None,
    entity_id: str,
) -> list[ModelT]:
    if source is None:
        return []
    return _coerce_rows(model_type, source.get(entity_id, ()))


def _build_entity(
    *,
    entity_id: str,
    canonical_names: Mapping[str, str],
    entity_types: Mapping[str, str],
    attrs_by_entity: Mapping[str, Mapping[str, Any]] | None,
    default_entity_type: str,
) -> RawEntity:
    attrs = attrs_by_entity.get(entity_id, {}) if attrs_by_entity else {}
    return RawEntity(
        entity_type=entity_types.get(entity_id, default_entity_type),
        canonical_name=canonical_names.get(entity_id, ""),
        attrs_json=dict(attrs),
    )
