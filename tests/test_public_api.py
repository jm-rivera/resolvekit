"""Freeze the public __all__ for all published modules.

If a name is added or removed, update the tuple here and bump the API changelog.
Tests intentionally fail loudly on drift.
"""

from __future__ import annotations

import importlib

import resolvekit


def _all(module_name: str) -> tuple[str, ...]:
    return tuple(sorted(importlib.import_module(module_name).__all__))


_EXPECTED: dict[str, tuple[str, ...]] = {
    "resolvekit": (
        "AmbiguousResolutionError",
        "AugmentResult",
        "BulkResult",
        "Crosswalk",
        "CrosswalkError",
        "DataPackNotAvailableError",
        "DroppedSpan",
        "EntityNotFoundError",
        "EntityRecord",
        "ExplainNotAvailableError",
        "GroupNotFoundError",
        "IGNORE",
        "NoModulesInstalledError",
        "OutputMissingError",
        "ParseResult",
        "ParsedEntity",
        "ResolutionContext",
        "ResolutionError",
        "ResolutionResult",
        "ResolutionStatus",
        "Resolver",
        "ResolverError",
        "UnknownCodeSystemError",
        "UnknownDomainError",
        "UnknownOutputError",
        "bulk",
        "configure",
        "download",
        "entity",
        "modules",
        "parse",
        "parse_bulk",
        "resolve",
        "resolve_id",
        "snap",
        "to",
    ),
    "resolvekit.types": (
        "BulkResult",
        "CacheInfo",
        "CandidateSummary",
        "EntityRecord",
        "InspectMatch",
        "InspectionReport",
        "LoggingTraceSink",
        "MatchTier",
        "ModuleInfo",
        "ReasonCode",
        "RefinementHint",
        "ResolutionContext",
        "ResolutionResult",
        "ResolutionStatus",
        "ResolverInfo",
        "RoutingMode",
        "SQLiteTuning",
        "Scorecard",
        "Verbosity",
    ),
    "resolvekit.errors": (
        "AmbiguousLinkError",
        "AmbiguousResolutionError",
        "CrosswalkError",
        "DataModuleNotFoundError",
        "DataPackError",
        "DataPackNormalizerVersionError",
        "DataPackNotAvailableError",
        "DataPackRuntimeVersionError",
        "EntityNotFoundError",
        "ExplainNotAvailableError",
        "GroupNotFoundError",
        "IncompatibleFeatureSchemaError",
        "IncompatibleVersionError",
        "InvalidKeyError",
        "LinkError",
        "MissingModuleDependencyError",
        "ModuleConflictError",
        "ModuleRegistryError",
        "NoModulesInstalledError",
        "OutputMissingError",
        "OverlayConstraintError",
        "RegistryError",
        "ResolutionError",
        "ResolverError",
        "UnknownCodeSystemError",
        "UnknownDomainError",
        "UnknownOutputError",
        "UnsupportedStoreError",
    ),
    "resolvekit.diagnostics": (
        "inspect",
        "search",
    ),
    "resolvekit.core": (
        "AmbiguousLinkError",
        "AmbiguousResolutionError",
        "Candidate",
        "CandidateEvidence",
        "CandidateSummary",
        "ConstraintOutcome",
        "DataModuleNotFoundError",
        "DataPackError",
        "DataPackLoader",
        "DataPackMetadata",
        "DataPackNormalizerVersionError",
        "DataPackRuntimeVersionError",
        "DomainPack",
        "DomainRegistry",
        "EntityRecord",
        "EntityStore",
        "ExplainedResolution",
        "GenerationContext",
        "IncompatibleFeatureSchemaError",
        "IncompatibleVersionError",
        "InvalidKeyError",
        "LinkError",
        "LoadedDataPack",
        "MatchTier",
        "MissingModuleDependencyError",
        "ModuleConflictError",
        "ModuleRegistryError",
        "NoModulesInstalledError",
        "NormalizationProfile",
        "NormalizedText",
        "Query",
        "ReasonCode",
        "RefinementHint",
        "RegistryError",
        "ResolutionContext",
        "ResolutionError",
        "ResolutionResult",
        "ResolutionStatus",
        "RetrievalSummary",
        "SQLiteEntityStore",
        "ScoreSummary",
        "Severity",
        "TextNormalizer",
        "UnknownDomainError",
        "UnsupportedStoreError",
        "default_registry",
        "get_module_path",
        "get_pack_factory",
        "list_available_modules",
        "register_module",
        "register_pack_factory",
        "unregister_module",
    ),
    "resolvekit.builder": (
        "BuildOptions",
        "BuildOutcome",
        "BuildPlan",
        "BuildStatus",
        "DiscoveredEntityFacts",
        "DomainInspection",
        "EntityClassificationSummary",
        "EntityFilter",
        "InspectionOutcome",
        "ModuleRecipe",
        "QualityPolicy",
        "ReleaseRecord",
        "build",
        "inspect",
        "list_releases",
        "presets",
        "resume",
    ),
    "resolvekit.extensions": (
        "CandidateSource",
        "Constraint",
        "ConstraintRole",
        "EntityRecord",
        "EntityStore",
        "FeatureExtractor",
        "FeatureVector",
        "FeaturesV1",
        "MatchTier",
        "Scorer",
        "TraceSink",
    ),
    "resolvekit.builder.pipeline": (
        "ADAPTER_FACTORIES",
        "BuildContext",
        "BuildExecutionError",
        "ChunkWorkItem",
        "DomainArtifacts",
        "FEATURE_SCHEMA_BY_DOMAIN",
        "ReleaseCandidate",
        "STAGES",
        "build_adapter_registry",
        "build_inspection_adapter_registry",
        "execute_build",
        "run_stage",
        "validate_packaged_artifacts",
        "write_build_report",
    ),
    "resolvekit.builder.sources": (
        "DataCommonsGeoSourceAdapter",
        "DataCommonsOrgSourceAdapter",
        "SourceAdapter",
    ),
    "resolvekit.builder.sqlite": (
        "REQUIRED_TABLES",
        "SCHEMA_SQL",
        "TABLE_DIFF_SPECS",
        "attached_db",
        "build_symspell_dictionary",
        "compute_selected_ids",
        "compute_table_diff",
        "connect_sqlite",
        "copy_subset_to_datapack",
        "count_entities",
        "count_missing_relation_targets",
        "ensure_sqlite_schema",
        "insert_normalized_payload",
        "list_missing_relation_targets",
        "quote_identifier",
        "rebuild_fts",
        "sample_keys",
        "staging_db_path",
        "table_count",
        "transaction",
        "validate_domain_db",
        "write_domain_diffs",
    ),
}


def test_resolvekit_all() -> None:
    assert _all("resolvekit") == _EXPECTED["resolvekit"]


def test_resolvekit_all_count() -> None:
    assert len(resolvekit.__all__) == 36


def test_resolvekit_all_excludes_removed_names() -> None:
    assert "translate" not in resolvekit.__all__
    assert "default" not in resolvekit.__all__


def test_resolvekit_types_all() -> None:
    assert _all("resolvekit.types") == _EXPECTED["resolvekit.types"]


def test_resolvekit_errors_all() -> None:
    assert _all("resolvekit.errors") == _EXPECTED["resolvekit.errors"]


def test_resolvekit_diagnostics_all() -> None:
    assert _all("resolvekit.diagnostics") == _EXPECTED["resolvekit.diagnostics"]


def test_resolvekit_core_all() -> None:
    assert _all("resolvekit.core") == _EXPECTED["resolvekit.core"]


def test_resolvekit_builder_all() -> None:
    assert _all("resolvekit.builder") == _EXPECTED["resolvekit.builder"]


def test_resolvekit_extensions_all() -> None:
    assert _all("resolvekit.extensions") == _EXPECTED["resolvekit.extensions"]


def test_resolvekit_builder_pipeline_all() -> None:
    assert (
        _all("resolvekit.builder.pipeline") == _EXPECTED["resolvekit.builder.pipeline"]
    )


def test_resolvekit_builder_sources_all() -> None:
    assert _all("resolvekit.builder.sources") == _EXPECTED["resolvekit.builder.sources"]


def test_resolvekit_builder_sqlite_all() -> None:
    assert _all("resolvekit.builder.sqlite") == _EXPECTED["resolvekit.builder.sqlite"]
