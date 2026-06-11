"""Tests for ResolveKit module and datapack error types."""

from resolvekit.core import (
    AmbiguousLinkError,
    AmbiguousResolutionError,
    DataModuleNotFoundError,
    DataPackError,
    IncompatibleVersionError,
    InvalidKeyError,
    LinkError,
    MissingModuleDependencyError,
    ModuleConflictError,
    NoModulesInstalledError,
    RegistryError,
    ResolutionError,
    UnknownDomainError,
    UnsupportedStoreError,
)
from resolvekit.core.model import CandidateSummary, ResolutionStatus


def test_base_error_is_exception() -> None:
    assert issubclass(DataPackError, Exception)
    assert str(DataPackError("test message")) == "test message"


def test_missing_module_dependency_error() -> None:
    error = MissingModuleDependencyError("geo.cities", ["geo.admin1", "geo.countries"])
    assert error.module_id == "geo.cities"
    assert error.missing_module_ids == ["geo.admin1", "geo.countries"]
    assert "geo.cities" in str(error)
    assert "geo.admin1" in str(error)


def test_module_not_found_error_lists_available_modules() -> None:
    error = DataModuleNotFoundError("geo.cities", ["geo.countries"])
    assert error.module_id == "geo.cities"
    assert error.searched == ["geo.countries"]
    assert "geo.cities" in str(error)
    assert "geo.countries" in str(error)


def test_no_modules_installed_error() -> None:
    error = NoModulesInstalledError()
    assert isinstance(error, DataPackError)
    assert error.hint is not None
    assert "pip install" in error.hint
    assert "resolvekit[geo]" in error.hint


def test_module_conflict_error_captures_overlap() -> None:
    error = ModuleConflictError(
        domain="geo",
        left_module_id="geo.countries",
        right_module_id="geo.cities",
        overlapping_entity_ids=["country/FRA"],
    )
    assert error.domain == "geo"
    assert error.left_module_id == "geo.countries"
    assert error.right_module_id == "geo.cities"
    assert error.overlapping_entity_ids == ["country/FRA"]


def test_link_errors_are_typed() -> None:
    assert issubclass(LinkError, DataPackError)
    assert issubclass(AmbiguousLinkError, LinkError)
    assert issubclass(InvalidKeyError, LinkError)


def test_ambiguous_link_error_message_contains_context() -> None:
    error = AmbiguousLinkError(
        overlay_row={"iso3": "USA"},
        candidates=("geo/USA", "geo/USA-historical"),
        link_key="iso3",
    )
    assert "geo/USA" in str(error)
    assert "iso3" in str(error)


def test_incompatible_version_error_stores_versions() -> None:
    error = IncompatibleVersionError(
        base_version="1.0.0",
        overlay_version="2.0.0",
        field="entity_schema_version",
    )
    assert error.base_version == "1.0.0"
    assert error.overlay_version == "2.0.0"
    assert error.field == "entity_schema_version"


def test_unsupported_store_and_registry_errors() -> None:
    assert issubclass(UnsupportedStoreError, DataPackError)
    assert issubclass(RegistryError, DataPackError)
    assert "postgres" in str(UnsupportedStoreError("postgres"))
    assert "geo.countries" in str(RegistryError("geo.countries"))


def test_resolution_error() -> None:
    error = ResolutionError(status=ResolutionStatus.NO_MATCH)
    assert error.status == ResolutionStatus.NO_MATCH
    assert error.candidates == []
    assert "no_match" in str(error)


def test_ambiguous_resolution_error() -> None:
    candidates = [
        CandidateSummary(entity_id="country/USA", confidence=0.9),
        CandidateSummary(entity_id="org/USA", confidence=0.85),
    ]
    error = AmbiguousResolutionError(candidates=candidates)
    assert isinstance(error, ResolutionError)
    assert error.status == ResolutionStatus.AMBIGUOUS
    assert len(error.candidates) == 2
    assert "2 candidates" in str(error)


def test_unknown_domain_error_with_suggestion() -> None:
    error = UnknownDomainError(["goe"], ["geo", "org"])
    assert isinstance(error, ValueError)
    assert error.unknown == ["goe"]
    assert error.available == ["geo", "org"]
    assert error.hint is not None
    assert "did you mean" in error.hint
    assert "geo" in error.hint


def test_unknown_domain_error_without_suggestion() -> None:
    error = UnknownDomainError(["xyz"], ["geo", "org"])
    assert "'xyz'" in str(error)
