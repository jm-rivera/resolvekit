"""Typed inspection models for builder source coverage reporting."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from resolvekit.builder.utils import utc_now_iso


class DiscoveredEntityFacts(BaseModel):
    """Inspection facts for one discovered source entity."""

    model_config = ConfigDict(frozen=True)

    entity_id: str
    raw_entity_type: str | None = None
    canonical_entity_type: str | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)


class EntityClassificationSummary(BaseModel):
    """Aggregated classification counts for one inspected domain."""

    model_config = ConfigDict(frozen=True)

    raw_type_counts: dict[str, int] = Field(default_factory=dict)
    canonical_type_counts: dict[str, int] = Field(default_factory=dict)
    unclassified_entity_ids: list[str] = Field(default_factory=list)


class DomainInspection(BaseModel):
    """Inspection report for one build domain."""

    model_config = ConfigDict(frozen=True)

    domain: str
    requested_entity_types: list[str] = Field(default_factory=list)
    include_relation_targets: bool = True
    discovered_entity_count: int = 0
    classification: EntityClassificationSummary = Field(
        default_factory=EntityClassificationSummary
    )
    sample_entities: list[DiscoveredEntityFacts] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class InspectionOutcome(BaseModel):
    """Outcome returned by ``inspect()``."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    domains: list[DomainInspection] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    reports: dict[str, str] = Field(default_factory=dict)
    started_at: str
    finished_at: str = Field(default_factory=utc_now_iso)


def summarize_domain_inspection(
    *,
    domain: str,
    requested_entity_types: list[str],
    include_relation_targets: bool,
    facts_by_entity: dict[str, DiscoveredEntityFacts],
    warnings: list[str] | None = None,
    sample_size: int = 25,
) -> DomainInspection:
    """Build a compact domain inspection report from per-entity facts."""
    raw_type_counts: dict[str, int] = {}
    canonical_type_counts: dict[str, int] = {}
    unclassified_entity_ids: list[str] = []

    for entity_id, facts in facts_by_entity.items():
        raw_type = (facts.raw_entity_type or "").strip() or "<missing>"
        raw_type_counts[raw_type] = raw_type_counts.get(raw_type, 0) + 1

        canonical_type = (facts.canonical_entity_type or "").strip()
        if canonical_type:
            canonical_type_counts[canonical_type] = (
                canonical_type_counts.get(canonical_type, 0) + 1
            )
        else:
            unclassified_entity_ids.append(entity_id)

    sample_entities = [
        facts_by_entity[entity_id]
        for entity_id in sorted(facts_by_entity)[:sample_size]
    ]

    return DomainInspection(
        domain=domain,
        requested_entity_types=list(requested_entity_types),
        include_relation_targets=include_relation_targets,
        discovered_entity_count=len(facts_by_entity),
        classification=EntityClassificationSummary(
            raw_type_counts=raw_type_counts,
            canonical_type_counts=canonical_type_counts,
            unclassified_entity_ids=sorted(unclassified_entity_ids),
        ),
        sample_entities=sample_entities,
        warnings=list(warnings or []),
    )
