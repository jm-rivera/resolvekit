"""Pydantic models for Data Commons raw chunk payloads."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True, slots=True)
class FetchedName:
    """Structured entity name returned by the shared runtime wrapper."""

    value: str
    language: str
    property: str


@dataclass(frozen=True, slots=True)
class DataCommonsDomainProfile:
    """Domain-specific mapping policy for canonical row normalization."""

    domain: str
    entity_type_mapper: Callable[[str, dict[str, Any]], str]
    alias_kind_mapper: Callable[[str], str]
    code_system_mapper: Callable[[str], str]
    default_relation_type: str
    source_label: str = "datacommons"

    def ensure_domain(self, domain: str) -> None:
        """Validate that the requested domain matches the profile domain."""
        if domain != self.domain:
            raise ValueError(
                f"Profile for domain '{self.domain}' cannot normalize '{domain}'."
            )


class RawEntity(BaseModel):
    """Raw per-entity payload before canonical row normalization."""

    model_config = ConfigDict(extra="ignore")

    entity_type: str
    canonical_name: str = ""
    attrs_json: dict[str, Any] = Field(default_factory=dict)


class RawAlias(BaseModel):
    """Raw alias payload for one entity."""

    model_config = ConfigDict(extra="ignore")

    alias_text: str
    language: str = "en"
    alias_type: str = "alias"
    source: str | None = None


class RawCode(BaseModel):
    """Raw code payload for one entity."""

    model_config = ConfigDict(extra="ignore")

    code_system: str
    code_value: str
    source: str | None = None


class RawRelation(BaseModel):
    """Raw relation payload for one entity."""

    model_config = ConfigDict(extra="ignore")

    relation_type: str
    target_id: str


class RawChunk(BaseModel):
    """Canonical raw chunk shape shared by Data Commons adapters."""

    model_config = ConfigDict(extra="ignore")

    entities: dict[str, RawEntity] = Field(default_factory=dict)
    aliases: dict[str, list[RawAlias]] = Field(default_factory=dict)
    codes: dict[str, list[RawCode]] = Field(default_factory=dict)
    relations: dict[str, list[RawRelation]] = Field(default_factory=dict)


class NormalizedEntity(BaseModel):
    """Canonical entity row payload for materialization."""

    entity_id: str
    entity_type: str
    canonical_name: str
    canonical_name_norm: str
    valid_from: str | None = None
    valid_until: str | None = None
    attrs_json: dict[str, Any] = Field(default_factory=dict)


class NormalizedName(BaseModel):
    """Canonical name row payload for materialization."""

    entity_id: str
    name_kind: str
    value: str
    value_norm: str
    lang: str = "en"
    script: str | None = None
    is_preferred: int = 0


class NormalizedCode(BaseModel):
    """Canonical code row payload for materialization."""

    entity_id: str
    system: str
    value: str
    value_norm: str


class NormalizedRelation(BaseModel):
    """Canonical relation row payload for materialization."""

    entity_id: str
    relation_type: str
    target_id: str
    valid_from: str | None = None
    valid_until: str | None = None


class NormalizedChunk(BaseModel):
    """Canonical normalized chunk payload grouped by destination table."""

    entities: list[NormalizedEntity] = Field(default_factory=list)
    names: list[NormalizedName] = Field(default_factory=list)
    codes: list[NormalizedCode] = Field(default_factory=list)
    relations: list[NormalizedRelation] = Field(default_factory=list)
