"""Models for module-oriented build orchestration."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from resolvekit.builder.utils import utc_now_iso


class BuildStatus(StrEnum):
    """Build status values."""

    SUCCESS = "success"
    FAILED = "failed"


class EntityFilter(BaseModel):
    """Filtering options for one emitted module/domain artifact."""

    model_config = ConfigDict(frozen=True)

    include_entity_types: list[str] = Field(default_factory=list)
    include_entity_ids: list[str] = Field(default_factory=list)
    exclude_entity_ids: list[str] = Field(default_factory=list)
    include_relation_targets: bool = True
    include_relation_types: list[str] = Field(default_factory=list)


class QualityPolicy(BaseModel):
    """Release quality thresholds."""

    model_config = ConfigDict(frozen=True)

    fail_on_suspicious_drop: bool = True
    max_entity_drop_pct: float = Field(default=0.1, ge=0.0, le=1.0)
    max_names_coverage_drop_pct: float = Field(default=0.1, ge=0.0, le=1.0)
    max_codes_coverage_drop_pct: float = Field(default=0.1, ge=0.0, le=1.0)
    max_relations_density_drop_pct: float = Field(default=0.1, ge=0.0, le=1.0)


class ModuleRecipe(BaseModel):
    """Definition of one installable module artifact."""

    model_config = ConfigDict(frozen=True)

    module_id: str = Field(..., min_length=1)
    domain: str = Field(..., min_length=1)
    entity_filter: EntityFilter = Field(default_factory=EntityFilter)
    module_dependencies: list[str] = Field(default_factory=list)
    source_datasets: list[str] = Field(default_factory=list)
    description: str | None = None
    include_symspell: bool = True
    include_calibrator: bool = False
    quality_policy: QualityPolicy | None = None

    @field_validator("module_dependencies")
    @classmethod
    def unique_module_dependencies(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class BuildOptions(BaseModel):
    """Execution options for builder runs."""

    model_config = ConfigDict(frozen=True)

    build_root: Path = Path("data/build")
    # Canonical datapacks live under ``src/resolvekit/_data/`` in the v1
    # manifest-first layout. Writer emits to ``datapacks_root/<domain>/<subpath>/``
    # where ``subpath = module_id.split('.', 1)[1].replace('.', '_')``.
    datapacks_root: Path = Path("src/resolvekit/_data")
    reports_root: Path = Path("data/reports")
    datacommons_instance: str = "datacommons.one.org"
    datacommons_api_key: str | None = None
    max_workers: int = Field(default=6, ge=1, le=64)
    chunk_size: int = Field(default=1000, ge=1)
    max_retries: int = Field(default=3, ge=1, le=20)
    retry_base_delay_sec: float = Field(default=0.5, ge=0.0)
    retry_max_delay_sec: float = Field(default=8.0, ge=0.0)
    reconcile_relation_closure: bool = True
    reconcile_relation_types: list[str] = Field(
        default_factory=lambda: ["contained_in", "subsidiary_of"]
    )
    reconcile_max_rounds: int = Field(default=4, ge=1, le=20)
    reconcile_max_entities: int = Field(default=250000, ge=1)
    reconcile_batch_size: int = Field(default=500, ge=1)
    discovery_parent_batch_size: int = Field(default=500, ge=1, le=5000)
    # CalVer data vintage stamp (e.g. "2026.04"). Persisted to DataPackMetadata.data_version
    # and exposed as resolver.info.data_version. Distinct from a module's release version
    # (the datapack_id "-v<...>" suffix). Keep byte-identical to avoid churn in
    # already-bundled datapacks. Bump via scripts/release/release_data.py, which sets
    # data_version and the datapack_id together — change it there, not by hand.
    data_version: str = Field(default="2026.04")

    @property
    def runs_root(self) -> Path:
        """Directory where per-run state is stored."""
        return self.build_root / "runs"

    @property
    def registry_path(self) -> Path:
        """Registry file path for successful releases."""
        return self.build_root / "registry" / "releases.json"

    @property
    def shared_geo_root(self) -> Path:
        """Directory for persistent shared geo staging store."""
        return self.build_root / "shared" / "geo"


class BuildPlan(BaseModel):
    """Plan containing recipes and execution settings."""

    model_config = ConfigDict(frozen=True)

    recipes: list[ModuleRecipe] = Field(..., min_length=1)
    options: BuildOptions = Field(default_factory=BuildOptions)
    quality_policy: QualityPolicy = Field(default_factory=QualityPolicy)
    run_id: str | None = None

    @field_validator("recipes")
    @classmethod
    def unique_recipe_ids(cls, value: list[ModuleRecipe]) -> list[ModuleRecipe]:
        """Ensure recipe IDs are unique."""
        ids = [recipe.module_id for recipe in value]
        if len(ids) != len(set(ids)):
            raise ValueError("recipes must have unique recipe IDs")
        return value


class ReleaseRecord(BaseModel):
    """Registered successful release entry."""

    model_config = ConfigDict(frozen=True)

    module_id: str
    version: str
    run_id: str
    created_at: str = Field(default_factory=utc_now_iso)
    output_path: Path
    domains: list[str]
    metrics: dict[str, float | int] = Field(default_factory=dict)
    reports: dict[str, str] = Field(default_factory=dict)

    @property
    def release_id(self) -> str:
        return self.module_id


class BuildOutcome(BaseModel):
    """Outcome returned by build/resume commands."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    status: BuildStatus
    stage: str
    releases: list[ReleaseRecord] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    reports: dict[str, str] = Field(default_factory=dict)
    started_at: str
    finished_at: str = Field(default_factory=utc_now_iso)
