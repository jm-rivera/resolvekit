"""Generic Data Commons source adapter parameterized by domain config."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from resolvekit.builder.inspection import DomainInspection
from resolvekit.builder.sources.datacommons.client import DataCommons
from resolvekit.builder.sources.datacommons.constants import (
    DEFAULT_ADAPTER_LANGUAGES,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_DC_INSTANCE,
    DEFAULT_MAX_CONCURRENT_REQUESTS,
)
from resolvekit.builder.sources.datacommons.models import NormalizedChunk, RawChunk
from resolvekit.builder.sources.datacommons.rows import normalize_bundle_to_rows
from resolvekit.builder.sources.datacommons.specs import DataCommonsDomainSpec
from resolvekit.core.linking.base_normalizer import BaseNormalizer
from resolvekit.core.util.normalization import TextNormalizer


@dataclass(frozen=True, slots=True)
class DomainAdapterConfig:
    """All domain-specific wiring for a DataCommons source adapter."""

    domain_spec: DataCommonsDomainSpec
    dc_api_factory: Callable[[DataCommons], Any]
    fetch_raw_chunk_fn: Callable[..., RawChunk]
    filter_entities_fn: Callable[..., list[str]]
    # Code normalizer for value_norm. Defaults to the base (casefold-only)
    # normalizer; domain adapters inject their own (e.g. OrgNormalizer) so the
    # write side matches the query-side code normalizer by construction.
    code_normalizer: BaseNormalizer = field(default_factory=BaseNormalizer)


class DataCommonsSourceAdapter:
    """Generic Data Commons adapter delegating to a DomainAdapterConfig."""

    def __init__(
        self,
        config: DomainAdapterConfig,
        *,
        languages: list[str] | None = None,
        dc_instance: str = DEFAULT_DC_INSTANCE,
        api_key: str | None = None,
        default_chunk_size: int = DEFAULT_CHUNK_SIZE,
        max_concurrent_requests: int = DEFAULT_MAX_CONCURRENT_REQUESTS,
        cache_dir: Path | None = None,
    ):
        self._config = config
        self._languages = languages or list(DEFAULT_ADAPTER_LANGUAGES)
        self._normalizer = TextNormalizer()
        self._code_normalizer = config.code_normalizer
        self._runtime = DataCommons(
            dc_instance=dc_instance,
            api_key=api_key,
            default_chunk_size=default_chunk_size,
            max_concurrent_requests=max_concurrent_requests,
            cache_dir=cache_dir,
        )
        self._dc_api = config.dc_api_factory(self._runtime)
        self._spec = config.domain_spec

    def supported_domains(self) -> set[str]:
        return {self._spec.domain}

    def discover_entities(self, domain: str) -> list[str]:
        self._ensure_domain(domain)
        return self._spec.discover_entities(
            dc_api=self._dc_api,
            with_retries=self._runtime.with_retries,
        )

    def supports_filtered_discovery(self) -> bool:
        return self._spec.supports_filtered_discovery

    def supports_inspection(self) -> bool:
        return self._spec.supports_inspection

    def discover_entities_filtered(
        self,
        domain: str,
        include_entity_types: list[str],
        include_relation_targets: bool,
    ) -> list[str]:
        if not self._spec.supports_filtered_discovery:
            raise NotImplementedError(
                f"Domain '{self._spec.domain}' does not support filtered discovery."
            )
        self._ensure_domain(domain)
        return self._spec.discover_entities_filtered(
            dc_api=self._dc_api,
            with_retries=self._runtime.with_retries,
            include_entity_types=include_entity_types,
            include_relation_targets=include_relation_targets,
        )

    def filter_discovered_entities(
        self,
        domain: str,
        entity_ids: list[str],
        include_entity_types: list[str],
    ) -> list[str]:
        self._ensure_domain(domain)
        return self._config.filter_entities_fn(
            runtime=self._runtime,
            dc_api=self._dc_api,
            entity_ids=entity_ids,
            include_entity_types=include_entity_types,
        )

    def inspect_domain(
        self,
        domain: str,
        *,
        include_entity_types: list[str],
        include_relation_targets: bool,
    ) -> DomainInspection:
        if not self._spec.supports_inspection:
            raise NotImplementedError(
                f"Domain '{self._spec.domain}' does not support inspection."
            )
        self._ensure_domain(domain)
        return self._spec.inspect_domain(
            dc_api=self._dc_api,
            with_retries=self._runtime.with_retries,
            include_entity_types=include_entity_types,
            include_relation_targets=include_relation_targets,
        )

    def fetch_raw_chunk(self, domain: str, entity_ids: list[str]) -> RawChunk:
        self._ensure_domain(domain)
        return self._config.fetch_raw_chunk_fn(
            entity_ids=entity_ids,
            dc_api=self._dc_api,
            languages=self._languages,
        )

    def normalize_raw_chunk(
        self,
        domain: str,
        raw_chunk: dict[str, Any],
    ) -> NormalizedChunk:
        self._ensure_domain(domain)
        return normalize_bundle_to_rows(
            domain=self._spec.domain,
            raw_chunk=raw_chunk,
            profile=self._spec.profile,
            text_normalize=self._normalizer.normalize,
            code_normalize=self._code_normalizer.normalize_code,
        )

    def _ensure_domain(self, domain: str) -> None:
        self._spec.profile.ensure_domain(domain)
