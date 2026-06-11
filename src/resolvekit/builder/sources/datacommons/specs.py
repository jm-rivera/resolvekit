"""Shared specification helpers for Data Commons-backed domain adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from resolvekit.builder.inspection import (
    DiscoveredEntityFacts,
    summarize_domain_inspection,
)
from resolvekit.builder.sources.datacommons.models import DataCommonsDomainProfile
from resolvekit.builder.sources.protocol import RetryFn


@dataclass(frozen=True, slots=True)
class DataCommonsDomainSpec:
    """Parameterized domain spec for discovery and inspection."""

    domain: str
    profile: DataCommonsDomainProfile
    discover_entities: Callable[..., list[str]]
    discover_entities_filtered: Callable[..., list[str]]
    collect_discovered_entity_facts: Callable[..., dict[str, DiscoveredEntityFacts]]
    inspection_warning_builder: Callable[..., list[str]] | None = None
    sample_size: int = 25
    supports_filtered_discovery: bool = True
    supports_inspection: bool = True

    def inspect_domain(
        self,
        *,
        dc_api: Any,
        with_retries: RetryFn,
        include_entity_types: list[str],
        include_relation_targets: bool,
    ):
        if include_entity_types:
            entity_ids = self.discover_entities_filtered(
                dc_api=dc_api,
                with_retries=with_retries,
                include_entity_types=include_entity_types,
                include_relation_targets=include_relation_targets,
            )
        else:
            entity_ids = self.discover_entities(
                dc_api=dc_api,
                with_retries=with_retries,
            )

        facts_by_entity = self.collect_discovered_entity_facts(
            dc_api=dc_api,
            profile=self.profile,
            entity_ids=entity_ids,
        )
        collected_warnings: list[str] = []
        if self.inspection_warning_builder is not None:
            collected_warnings.extend(
                self.inspection_warning_builder(
                    dc_api=dc_api,
                    profile=self.profile,
                    entity_ids=entity_ids,
                    facts_by_entity=facts_by_entity,
                    requested_entity_types=include_entity_types,
                    include_relation_targets=include_relation_targets,
                )
            )
        return summarize_domain_inspection(
            domain=self.domain,
            requested_entity_types=include_entity_types,
            include_relation_targets=include_relation_targets,
            facts_by_entity=facts_by_entity,
            warnings=collected_warnings,
            sample_size=self.sample_size,
        )
