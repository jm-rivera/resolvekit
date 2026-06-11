"""DataPack loading and management."""

import importlib.metadata
import json
from pathlib import Path
from typing import Any, Literal

from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from resolvekit.core.errors import (
    DataPackNormalizerVersionError,
    DataPackRuntimeVersionError,
)

# Canonical entity schema version written into every built datapack. All builder
# paths (base_builder, packaging, build_continents) import this constant so a bump
# is a single edit. A change here requires a coordinated full rebuild and release.
ENTITY_SCHEMA_VERSION: str = "1.0"

# Bump (e.g. "casefold.2") whenever normalize_code's output changes for ANY system, so the
# load gate forces a rebuild of packs written under the old convention.
NORMALIZER_VERSION: str = "casefold.1"


def _is_version_below(actual: str, required: str) -> bool:
    """Return True if *actual* is a strictly lower PEP 440 version than *required*.

    Uses ``packaging.version.Version`` so pre-release / post-release / dev
    segments compare correctly (``1.0b1 < 1.0b2 < 1.0rc1 < 1.0``). If either
    string is malformed, falls back to a conservative lexicographic compare
    so a borked metadata file still triggers the runtime version gate rather
    than silently passing it.
    """
    try:
        return Version(actual) < Version(required)
    except InvalidVersion:
        return actual < required


class RemoteArtifactSpec(BaseModel):
    """Download spec for one artifact in a remote-distribution datapack.

    Each remote module declares one of these per file the client must fetch
    (the sqlite database and every entry in the module's ``artifacts`` dict).
    Assets are gzip-compressed on the GitHub Release; ``gz_sha256`` verifies
    the wire bytes before decompression and ``sha256`` verifies the
    decompressed file on disk. ``size_mb`` is the decompressed (on-disk) size.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = Field(..., description="GitHub Release asset URL for the .gz file")
    sha256: str = Field(
        ..., description="SHA-256 of the decompressed file as it lives on disk"
    )
    gz_sha256: str = Field(..., description="SHA-256 of the .gz asset on the wire")
    size_mb: float | None = Field(
        default=None,
        description="Decompressed on-disk size in MB (informational)",
    )


class DataPackMetadata(BaseModel):
    """Metadata for a versioned DataPack.

    DataPacks are versioned artifact sets containing:
    - SQLite database with entity data
    - FTS5 index for full-text search
    - Source attribution and lineage

    Base packs contain authoritative entity data.
    Overlay packs link to base packs and provide augmentation data.

    Note: ``remote_url`` and ``download_size_mb`` are computed properties
    derived from ``remote_artifacts['sqlite']`` and are excluded from
    ``model_dump()`` output by Pydantic. Callers serializing then
    reconstructing the model should treat them as read-only views, not
    fields — the structural source of truth is ``remote_artifacts``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    datapack_id: str = Field(..., description="Unique datapack identifier")
    module_id: str = Field(..., description="Stable module identifier")
    domain_pack_id: str = Field(..., description="Domain pack identifier (geo, org)")
    module_dependencies: list[str] = Field(
        default_factory=list,
        description="Module IDs that must be present in the same composition",
    )
    entity_schema_version: str = Field(..., description="Entity schema version")
    feature_schema_version: str = Field(..., description="Feature schema version")
    # Position is load-bearing: model_dump() ordering must match the hand-edited
    # JSON insert position in the 16 bundled metadata.json files.
    normalizer_version: str = Field(
        default="legacy",
        description=(
            "Code-normalizer version used when this pack was built. "
            "Absent/legacy packs pre-date the contract; the load gate rejects them."
        ),
    )
    index_versions: dict[str, Any] = Field(
        default_factory=dict, description="Index versions"
    )
    build_timestamp: str = Field(..., description="ISO timestamp of creation")
    source_datasets: list[str] = Field(
        default_factory=list, description="Source datasets used"
    )
    artifacts: dict[str, str] | None = Field(
        default=None, description="Optional artifact filenames"
    )
    description: str | None = Field(default=None)
    checksums: dict[str, str] | None = Field(
        default=None, description="SHA256 checksums"
    )

    # Distribution fields
    distribution: Literal["bundled", "remote"] = Field(
        default="bundled",
        description="Distribution strategy: 'bundled' (in wheel) or 'remote' (lazy download)",
    )
    remote_artifacts: dict[str, "RemoteArtifactSpec"] | None = Field(
        default=None,
        description=(
            "Per-artifact GitHub Release download specs (URL + checksums + size). "
            "Required for 'remote' distribution; must include the 'sqlite' key for "
            "the main database. Each key in 'artifacts' must also have a matching "
            "entry here. None for 'bundled' distribution."
        ),
    )

    # Data versioning fields
    data_version: str | None = Field(
        default=None,
        description="CalVer (e.g. '2026.04') for pack data version, independent of resolvekit code version.",
    )
    min_resolvekit_version: str | None = Field(
        default=None,
        description="Minimum resolvekit runtime version required to load this pack; raises DataPackRuntimeVersionError on load if older.",
    )

    # Overlay-related fields
    pack_type: Literal["base", "overlay"] = Field(
        default="base", description="Pack type: 'base' or 'overlay'"
    )
    store_type: str = Field(default="sqlite", description="Store implementation type")
    store_file: str = Field(
        default="entities.sqlite", description="Main data file name"
    )
    link_keys: list[str] | None = Field(
        default=None,
        description="Ordered keys for linking overlay rows (overlay only)",
    )
    base_module_ids: list[str] | None = Field(
        default=None,
        description="Module IDs required as overlay composition ancestry",
    )
    allow_new_entities: bool = Field(
        default=False,
        description="Whether overlay can create new entities (overlay only)",
    )
    quality_metrics: dict[str, float | int] | None = Field(
        default=None,
        description=(
            "QA metrics captured at build time (entity_count, names_coverage, "
            "etc.); informational, read by the release ledger. Optional for "
            "back-compat with packs built before this field existed."
        ),
    )

    @field_validator("module_dependencies")
    @classmethod
    def normalize_module_dependencies(cls, value: list[str]) -> list[str]:
        return _normalize_string_list(value)

    @field_validator("base_module_ids")
    @classmethod
    def normalize_base_module_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = _normalize_string_list(value)
        return normalized or None

    @model_validator(mode="after")
    def validate_module_fields(self) -> "DataPackMetadata":
        if self.pack_type == "overlay":
            if not self.base_module_ids:
                raise ValueError("overlay datapacks require base_module_ids")
            if not self.link_keys:
                raise ValueError("overlay datapacks require link_keys")
        elif self.base_module_ids is not None:
            raise ValueError("base datapacks must not declare base_module_ids")

        if self.distribution == "remote":
            if not self.remote_artifacts or "sqlite" not in self.remote_artifacts:
                raise ValueError("remote datapacks require remote_artifacts['sqlite']")
            artifact_keys = set(self.artifacts or {})
            spec_keys = set(self.remote_artifacts) - {"sqlite"}
            missing = artifact_keys - spec_keys
            if missing:
                raise ValueError(
                    f"remote_artifacts missing specs for declared artifacts: "
                    f"{sorted(missing)}"
                )
            stray = spec_keys - artifact_keys
            if stray:
                raise ValueError(
                    f"remote_artifacts has specs for undeclared artifacts: "
                    f"{sorted(stray)}"
                )
        elif self.remote_artifacts is not None:
            raise ValueError("bundled datapacks must not declare remote_artifacts")
        return self

    @property
    def is_overlay(self) -> bool:
        """Return True if this is an overlay pack."""
        return self.pack_type == "overlay"

    @property
    def remote_url(self) -> str | None:
        """URL of the sqlite asset on the GitHub Release, or None for bundled packs.

        Convenience view onto ``remote_artifacts["sqlite"].url`` for UX surfaces
        (``ModuleInfo``, manifest display). Returns None when the pack is bundled
        or has no remote_artifacts.
        """
        if not self.remote_artifacts:
            return None
        sqlite_spec = self.remote_artifacts.get("sqlite")
        return sqlite_spec.url if sqlite_spec else None

    @property
    def download_size_mb(self) -> float | None:
        """Total decompressed on-disk size in MB across all remote artifacts.

        Sum of every ``remote_artifacts[*].size_mb``. Despite the field name,
        this is the *decompressed* footprint (what the cache directory will
        occupy after download), not the compressed wire size. Returns None
        when the pack is bundled or no per-artifact sizes are recorded.
        """
        if not self.remote_artifacts:
            return None
        sizes = [
            spec.size_mb
            for spec in self.remote_artifacts.values()
            if spec.size_mb is not None
        ]
        return sum(sizes) if sizes else None

    @classmethod
    def from_file(cls, path: Path) -> "DataPackMetadata":
        """Load metadata from JSON file."""
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**data)

    def to_file(self, path: Path) -> None:
        """Write metadata to JSON file in canonical format."""
        path.write_text(
            json.dumps(self.model_dump(), indent=2, ensure_ascii=True, sort_keys=False)
            + "\n",
            encoding="utf-8",
        )


class LoadedDataPack:
    """A loaded DataPack ready for use.

    Provides access to:
    - Metadata (version, sources, etc.)
    - Database path for EntityStore
    - Artifact paths for additional resources
    """

    def __init__(
        self,
        metadata: DataPackMetadata,
        base_path: Path,
    ):
        self._metadata = metadata
        self._base_path = base_path

    @property
    def metadata(self) -> DataPackMetadata:
        return self._metadata

    @property
    def base_path(self) -> Path:
        """Path to the datapack directory."""
        return self._base_path

    @property
    def pack_id(self) -> str:
        return self._metadata.domain_pack_id

    @property
    def module_id(self) -> str:
        return self._metadata.module_id

    @property
    def version(self) -> str:
        return self._metadata.datapack_id

    @property
    def db_path(self) -> Path:
        """Path to SQLite database."""
        if self._metadata.artifacts and "sqlite" in self._metadata.artifacts:
            return self._base_path / self._metadata.artifacts["sqlite"]
        return self._base_path / self._metadata.store_file

    def artifact_path(self, artifact_type: str) -> Path | None:
        """Get path to a specific artifact."""
        if self._metadata.artifacts:
            filename = self._metadata.artifacts.get(artifact_type)
            if filename:
                return self._base_path / filename
        return None


class DataPackLoader:
    """Loads DataPacks from filesystem.

    DataPack directory structure:
        datapack/
        ├── metadata.json      # Metadata
        ├── entities.sqlite    # SQLite with entity data
        ├── entities_fts.db    # FTS5 index (optional)
        └── symspell.txt       # SymSpell dictionary (optional)
    """

    def __init__(self, validate_checksums: bool = True):
        self._validate_checksums = validate_checksums

    def load(self, path: Path | str) -> LoadedDataPack:
        """Load a DataPack from a directory.

        For remote packs, resolves the effective path via the cache system.
        The sqlite may live in a cache directory rather than the package dir.

        Args:
            path: Path to datapack directory

        Returns:
            LoadedDataPack instance

        Raises:
            FileNotFoundError: If directory or required files missing
            ValueError: If metadata invalid
            DataPackNotAvailableError: If remote pack not cached and
                auto-download disabled
        """
        path = Path(path)

        if not path.is_dir():
            raise FileNotFoundError(f"DataPack directory not found: {path}")

        meta_path = path / "metadata.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"Metadata not found: {meta_path}")

        # Apply manifest-authoritative overrides for distribution-state fields
        # when the path matches a canonical manifest location, so packs whose
        # on-disk metadata.json lags the manifest still behave correctly.
        # Ad-hoc paths (fixtures, third-party clones) keep their on-disk
        # distribution verbatim.
        metadata = DataPackMetadata.from_file(meta_path)
        metadata = _overlay_manifest_if_canonical(metadata, path)

        # Version gate: raise early if pack requires a newer runtime
        if metadata.min_resolvekit_version is not None:
            try:
                installed = importlib.metadata.version("resolvekit")
            except importlib.metadata.PackageNotFoundError:
                installed = "0.0.0"
            if _is_version_below(installed, metadata.min_resolvekit_version):
                raise DataPackRuntimeVersionError(
                    required_version=metadata.min_resolvekit_version,
                    installed_version=installed,
                    module_id=metadata.module_id,
                )

        # Normalizer-version gate: reject packs built under a different code-normalizer
        if metadata.normalizer_version != NORMALIZER_VERSION:
            raise DataPackNormalizerVersionError(
                expected=NORMALIZER_VERSION,
                found=metadata.normalizer_version,
                module_id=metadata.module_id,
            )

        # For remote packs, resolve to cache path if needed
        if metadata.distribution == "remote":
            from resolvekit.core.remote import ensure_datapack_ready

            effective_path = ensure_datapack_ready(metadata, path)
        else:
            effective_path = path

        # Validate required SQLite DB exists at effective path
        if metadata.artifacts and "sqlite" in metadata.artifacts:
            db_path = effective_path / metadata.artifacts["sqlite"]
        else:
            db_path = effective_path / metadata.store_file

        if not db_path.exists():
            raise FileNotFoundError(f"SQLite database not found: {db_path}")

        # Validate optional artifacts
        if metadata.artifacts:
            for artifact_type, filename in metadata.artifacts.items():
                artifact_path = effective_path / filename
                if not artifact_path.exists():
                    raise FileNotFoundError(
                        f"Artifact '{artifact_type}' not found: {artifact_path}"
                    )

        # Optional: validate checksums
        if self._validate_checksums and metadata.checksums:
            self._validate_artifact_checksums(effective_path, metadata)

        return LoadedDataPack(metadata=metadata, base_path=effective_path)

    def _validate_artifact_checksums(
        self, base_path: Path, metadata: DataPackMetadata
    ) -> None:
        """Validate artifact checksums match metadata.

        For remote packs, expected checksums come from
        ``remote_artifacts[*].sha256``; for bundled packs they come from
        the flat ``checksums`` dict. Both sources reference the same on-disk
        filenames (sqlite at ``store_file``, others at ``artifacts[type]``).
        """
        expected: dict[str, str] = {}
        if metadata.remote_artifacts:
            expected.update(
                {
                    atype: spec.sha256
                    for atype, spec in metadata.remote_artifacts.items()
                }
            )
        if metadata.checksums:
            for atype, csum in metadata.checksums.items():
                expected.setdefault(atype, csum)

        if not expected:
            return

        checksum_targets: dict[str, Path] = {
            "sqlite": base_path / metadata.store_file,
        }
        if metadata.artifacts:
            checksum_targets.update(
                {
                    artifact_type: base_path / filename
                    for artifact_type, filename in metadata.artifacts.items()
                }
            )

        from resolvekit.core.remote import _chunked_sha256

        for artifact_type, expected_hash in expected.items():
            path = checksum_targets.get(artifact_type)
            if path is None or not path.exists():
                continue

            actual_hash = _chunked_sha256(path)
            if actual_hash != expected_hash:
                raise ValueError(
                    f"Checksum mismatch for {artifact_type}: "
                    f"expected {expected_hash}, got {actual_hash}"
                )


def _normalize_string_list(values: list[str]) -> list[str]:
    normalized = [value.strip() for value in values if value.strip()]
    return list(dict.fromkeys(normalized))


def _overlay_manifest_if_canonical(
    metadata: DataPackMetadata,
    path: Path,
) -> DataPackMetadata:
    """Overlay manifest overrides onto *metadata* when *path* is canonical.

    Canonical = the pack directory matches the manifest's expected on-disk
    location for this ``module_id``.  Ad-hoc paths (tmp fixtures, third-
    party clones, one-off directories) return *metadata* unchanged so they
    don't inherit unrelated manifest flags.

    Imported lazily to avoid a circular dependency with ``module_registry``
    (the registry imports :class:`DataPackMetadata` from this module).
    """
    from resolvekit.core.module_registry import (
        get_canonical_manifest_paths,
        get_manifest_overrides,
    )

    canonical = get_canonical_manifest_paths().get(metadata.module_id)
    if canonical is None:
        return metadata
    try:
        same_location = canonical.resolve() == path.resolve()
    except (OSError, RuntimeError):
        return metadata
    if not same_location:
        return metadata

    overrides = get_manifest_overrides().get(metadata.module_id)
    if not overrides:
        return metadata
    # Re-validate the merged dict so structural override values (e.g.
    # remote_artifacts: dict[str, dict]) get coerced into their Pydantic
    # model types — model_copy(update=...) skips validation.
    return DataPackMetadata.model_validate({**metadata.model_dump(), **overrides})
