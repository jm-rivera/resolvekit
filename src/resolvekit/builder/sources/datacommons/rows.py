"""Generic canonical row builder for Data Commons raw bundles."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from resolvekit.builder.sources.datacommons.constants import DEFAULT_LANGUAGE
from resolvekit.builder.sources.datacommons.models import (
    DataCommonsDomainProfile,
    NormalizedChunk,
    NormalizedCode,
    NormalizedEntity,
    NormalizedName,
    NormalizedRelation,
    RawAlias,
    RawChunk,
    RawCode,
    RawEntity,
    RawRelation,
)
from resolvekit.core.linking.base_normalizer import BaseNormalizer

_CANONICAL_NAME_KIND = "canonical"
_DCID_CODE_SYSTEM = "dcid"
_ALIAS_FALLBACK_KIND = "alias"

# Default code normalizer for callers that don't inject a domain-specific one.
# The DataCommons adapter passes the owning domain's normalizer so the write-side
# value_norm matches the query-side normalizer by construction (e.g. OrgNormalizer
# strips DUNS dashes); a bare BaseNormalizer here would diverge from that read path.
_CODE_NORMALIZER = BaseNormalizer()


@dataclass(slots=True)
class _DedupState:
    """Dedup tracking for per-chunk normalized rows."""

    names: set[tuple[str, str, str, str]] = field(default_factory=set)
    codes: set[tuple[str, str]] = field(default_factory=set)
    relations: set[tuple[str, str, str]] = field(default_factory=set)


def normalize_bundle_to_rows(
    *,
    domain: str,
    raw_chunk: RawChunk | dict[str, Any],
    profile: DataCommonsDomainProfile,
    text_normalize: Callable[[str], str],
    code_normalize: Callable[[str, str], str] = _CODE_NORMALIZER.normalize_code,
) -> NormalizedChunk:
    """Normalize a raw bundle into canonical table-row model payloads."""
    profile.ensure_domain(domain)
    chunk = (
        raw_chunk
        if isinstance(raw_chunk, RawChunk)
        else RawChunk.model_validate(raw_chunk)
    )

    rows = NormalizedChunk()
    dedup = _DedupState()

    _normalize_entities(
        raw_entities=chunk.entities,
        profile=profile,
        text_normalize=text_normalize,
        code_normalize=code_normalize,
        rows=rows,
        dedup=dedup,
    )
    _normalize_aliases(
        raw_aliases=chunk.aliases,
        profile=profile,
        text_normalize=text_normalize,
        rows=rows,
        dedup=dedup,
    )
    _normalize_codes(
        raw_codes=chunk.codes,
        profile=profile,
        code_normalize=code_normalize,
        rows=rows,
        dedup=dedup,
    )
    _normalize_relations(
        raw_relations=chunk.relations,
        profile=profile,
        rows=rows,
        dedup=dedup,
    )

    return rows


def _normalize_entities(
    *,
    raw_entities: dict[str, RawEntity],
    profile: DataCommonsDomainProfile,
    text_normalize: Callable[[str], str],
    code_normalize: Callable[[str, str], str],
    rows: NormalizedChunk,
    dedup: _DedupState,
) -> None:
    for entity_id, payload in raw_entities.items():
        # Keep entity rows closed even when Data Commons omits names.
        # We use the dcid as a deterministic fallback canonical name.
        canonical_name = payload.canonical_name.strip() or entity_id

        rows.entities.append(
            NormalizedEntity(
                entity_id=entity_id,
                entity_type=profile.entity_type_mapper(
                    payload.entity_type,
                    dict(payload.attrs_json),
                ),
                canonical_name=canonical_name,
                canonical_name_norm=text_normalize(canonical_name),
                valid_from=None,
                valid_until=None,
                attrs_json=dict(payload.attrs_json),
            )
        )

        _append_name_row(
            text_normalize=text_normalize,
            rows=rows,
            dedup=dedup,
            entity_id=entity_id,
            name_kind=_CANONICAL_NAME_KIND,
            value=canonical_name,
            lang=DEFAULT_LANGUAGE,
            is_preferred=1,
        )
        _append_code_row(
            rows=rows,
            dedup=dedup,
            entity_id=entity_id,
            system=_DCID_CODE_SYSTEM,
            value=entity_id,
            code_normalize=code_normalize,
        )


def _normalize_aliases(
    *,
    raw_aliases: dict[str, list[RawAlias]],
    profile: DataCommonsDomainProfile,
    text_normalize: Callable[[str], str],
    rows: NormalizedChunk,
    dedup: _DedupState,
) -> None:
    for entity_id, alias_list in raw_aliases.items():
        for alias in alias_list or []:
            alias_text = alias.alias_text.strip()
            if not alias_text:
                continue

            _append_name_row(
                text_normalize=text_normalize,
                rows=rows,
                dedup=dedup,
                entity_id=entity_id,
                name_kind=profile.alias_kind_mapper(
                    alias.alias_type or _ALIAS_FALLBACK_KIND
                ),
                value=alias_text,
                lang=(alias.language or DEFAULT_LANGUAGE).lower(),
                is_preferred=0,
            )


def _normalize_codes(
    *,
    raw_codes: dict[str, list[RawCode]],
    profile: DataCommonsDomainProfile,
    code_normalize: Callable[[str, str], str],
    rows: NormalizedChunk,
    dedup: _DedupState,
) -> None:
    for entity_id, code_list in raw_codes.items():
        for code in code_list or []:
            system = profile.code_system_mapper(code.code_system or "")
            value = code.code_value.strip()
            if not system or not value:
                continue
            _append_code_row(
                rows=rows,
                dedup=dedup,
                entity_id=entity_id,
                system=system,
                value=value,
                code_normalize=code_normalize,
            )


def _normalize_relations(
    *,
    raw_relations: dict[str, list[RawRelation]],
    profile: DataCommonsDomainProfile,
    rows: NormalizedChunk,
    dedup: _DedupState,
) -> None:
    for entity_id, relation_list in raw_relations.items():
        for relation in relation_list or []:
            target_id = relation.target_id.strip()
            relation_type = (
                relation.relation_type.strip() or profile.default_relation_type
            )
            if not target_id or not relation_type:
                continue

            relation_key = (entity_id, relation_type, target_id)
            if relation_key in dedup.relations:
                continue
            dedup.relations.add(relation_key)
            # DC parent relations are atemporal today; fields reserved for future use.
            rows.relations.append(
                NormalizedRelation(
                    entity_id=entity_id,
                    relation_type=relation_type,
                    target_id=target_id,
                    valid_from=None,
                    valid_until=None,
                )
            )


def _append_name_row(
    *,
    text_normalize: Callable[[str], str],
    rows: NormalizedChunk,
    dedup: _DedupState,
    entity_id: str,
    name_kind: str,
    value: str,
    lang: str,
    is_preferred: int,
) -> None:
    key = (entity_id, name_kind, value, lang)
    if key in dedup.names:
        return
    dedup.names.add(key)
    rows.names.append(
        NormalizedName(
            entity_id=entity_id,
            name_kind=name_kind,
            value=value,
            value_norm=text_normalize(value),
            lang=lang,
            script=None,
            is_preferred=is_preferred,
        )
    )


def _append_code_row(
    *,
    rows: NormalizedChunk,
    dedup: _DedupState,
    entity_id: str,
    system: str,
    value: str,
    code_normalize: Callable[[str, str], str],
) -> None:
    key = (entity_id, system)
    if key in dedup.codes:
        return
    dedup.codes.add(key)
    rows.codes.append(
        NormalizedCode(
            entity_id=entity_id,
            system=system,
            value=value,
            value_norm=code_normalize(system, value),
        )
    )
