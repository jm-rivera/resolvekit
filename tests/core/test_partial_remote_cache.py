"""Partial remote caches are first-class: a module whose declared dependency
is a remote pack the user hasn't downloaded must load without error, and an
explicit request for one module must not transitively queue (or download) its
remote siblings.

Regression tests for the 0.1.0 failure where ``download("geo.admin1")``
followed by ``Resolver.auto()`` raised ``MissingModuleDependencyError``
demanding geo.admin2/geo.admin3/geo.cities.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from resolvekit.core.api.loading import module_catalog
from resolvekit.core.datapack import DataPackMetadata, LoadedDataPack
from resolvekit.core.errors import MissingModuleDependencyError


def _metadata(
    module_id: str,
    *,
    distribution: str = "bundled",
    module_dependencies: list[str] | None = None,
) -> DataPackMetadata:
    kwargs: dict = {
        "datapack_id": f"{module_id}-v2026.1",
        "module_id": module_id,
        "domain_pack_id": module_id.split(".", maxsplit=1)[0],
        "entity_schema_version": "1.0",
        "feature_schema_version": f"{module_id.split('.', maxsplit=1)[0]}.features.v1",
        "build_timestamp": "2026-01-01T00:00:00Z",
        "distribution": distribution,
        "module_dependencies": module_dependencies or [],
    }
    if distribution == "remote":
        from resolvekit.core.datapack import RemoteArtifactSpec

        kwargs["remote_artifacts"] = {
            "sqlite": RemoteArtifactSpec(
                url=f"https://example.com/{module_id}.sqlite.gz",
                sha256="0" * 64,
                gz_sha256="0" * 64,
                size_mb=1.0,
            ),
        }
    return DataPackMetadata(**kwargs)


@pytest.fixture()
def fake_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A synthetic module registry with controllable metadata and cache state.

    Returns a helper to register modules; patches list_available_modules,
    load_module_metadata, and is_cached accordingly.
    """
    paths: dict[str, Path] = {}
    metadatas: dict[str, DataPackMetadata] = {}
    cached: set[str] = set()

    def register(
        module_id: str,
        *,
        distribution: str = "bundled",
        module_dependencies: list[str] | None = None,
        is_cached: bool = False,
        data_present: bool = True,
    ) -> DataPackMetadata:
        path = tmp_path / module_id.replace(".", "_")
        path.mkdir(exist_ok=True)
        (path / "metadata.json").touch()
        meta = _metadata(
            module_id,
            distribution=distribution,
            module_dependencies=module_dependencies,
        )
        if distribution == "bundled" and data_present:
            (path / meta.store_file).touch()
        if is_cached:
            cached.add(module_id)
        paths[module_id] = path
        metadatas[module_id] = meta
        return meta

    def fake_list_available_modules() -> dict[str, Path]:
        return dict(paths)

    def fake_load_module_metadata(
        module_id: str, path: Path, *, overrides=None
    ) -> DataPackMetadata:
        return metadatas[module_id]

    def fake_is_cached(metadata: DataPackMetadata) -> bool:
        return metadata.module_id in cached

    monkeypatch.setattr(
        module_catalog, "list_available_modules", fake_list_available_modules
    )
    monkeypatch.setattr(
        "resolvekit.core.module_registry.list_available_modules",
        fake_list_available_modules,
    )
    monkeypatch.setattr(
        "resolvekit.core.module_registry.load_module_metadata",
        fake_load_module_metadata,
    )
    monkeypatch.setattr(
        "resolvekit.core.module_registry.get_manifest_overrides", lambda: {}
    )
    monkeypatch.setattr("resolvekit.core.remote.is_cached", fake_is_cached)
    return register


def _loaded_pack(meta: DataPackMetadata, path: Path) -> LoadedDataPack:
    return LoadedDataPack(meta, path)


class TestValidateModuleDependencies:
    def test_remote_uncached_dependency_is_soft(self, fake_registry, tmp_path):
        meta = fake_registry(
            "geo.admin1",
            distribution="remote",
            module_dependencies=["geo.admin2", "geo.countries"],
            is_cached=True,
        )
        fake_registry("geo.admin2", distribution="remote", is_cached=False)
        countries = fake_registry("geo.countries")

        base_packs = {
            "geo.admin1": _loaded_pack(meta, tmp_path / "geo_admin1"),
            "geo.countries": _loaded_pack(countries, tmp_path / "geo_countries"),
        }
        # geo.admin2 is declared but remote-and-uncached: no error.
        module_catalog._validate_module_dependencies(base_packs, {}, set())

    def test_remote_cached_dependency_still_hard(self, fake_registry, tmp_path):
        meta = fake_registry(
            "geo.admin1",
            distribution="remote",
            module_dependencies=["geo.admin2"],
            is_cached=True,
        )
        fake_registry("geo.admin2", distribution="remote", is_cached=True)

        base_packs = {"geo.admin1": _loaded_pack(meta, tmp_path / "geo_admin1")}
        # geo.admin2 is cached, so its absence from the load set is a real
        # loading bug and must still raise.
        with pytest.raises(MissingModuleDependencyError):
            module_catalog._validate_module_dependencies(base_packs, {}, set())

    def test_bundled_missing_dependency_still_hard(self, fake_registry, tmp_path):
        meta = fake_registry(
            "org.governments",
            module_dependencies=["org.providers"],
        )
        fake_registry("org.providers")

        base_packs = {
            "org.governments": _loaded_pack(meta, tmp_path / "org_governments")
        }
        with pytest.raises(MissingModuleDependencyError):
            module_catalog._validate_module_dependencies(base_packs, {}, set())

    def test_unknown_dependency_still_hard(self, fake_registry, tmp_path):
        meta = fake_registry(
            "geo.admin1",
            distribution="remote",
            module_dependencies=["geo.nonexistent"],
            is_cached=True,
        )
        base_packs = {"geo.admin1": _loaded_pack(meta, tmp_path / "geo_admin1")}
        with pytest.raises(MissingModuleDependencyError):
            module_catalog._validate_module_dependencies(base_packs, {}, set())


class TestResolveRequestedModulePaths:
    def test_explicit_request_skips_remote_uncached_deps(self, fake_registry):
        fake_registry(
            "geo.admin1",
            distribution="remote",
            module_dependencies=["geo.admin2", "geo.cities", "geo.countries"],
            is_cached=True,
        )
        fake_registry("geo.admin2", distribution="remote", is_cached=False)
        fake_registry("geo.cities", distribution="remote", is_cached=False)
        fake_registry("geo.countries")

        resolved = module_catalog._resolve_requested_module_paths(["geo.admin1"])
        assert set(resolved) == {"geo.admin1", "geo.countries"}

    def test_explicit_request_queues_cached_remote_deps(self, fake_registry):
        fake_registry(
            "geo.admin2",
            distribution="remote",
            module_dependencies=["geo.admin1"],
            is_cached=True,
        )
        fake_registry("geo.admin1", distribution="remote", is_cached=True)

        resolved = module_catalog._resolve_requested_module_paths(["geo.admin2"])
        assert set(resolved) == {"geo.admin2", "geo.admin1"}

    def test_auto_mode_skips_uncached_remote_modules(self, fake_registry):
        fake_registry(
            "geo.admin1",
            distribution="remote",
            module_dependencies=["geo.admin2", "geo.countries"],
            is_cached=True,
        )
        fake_registry("geo.admin2", distribution="remote", is_cached=False)
        fake_registry("geo.countries")

        resolved = module_catalog._resolve_requested_module_paths(None)
        assert set(resolved) == {"geo.admin1", "geo.countries"}


@pytest.mark.requires_remote_data
def test_auto_resolver_with_only_admin1_downloaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end repro of the 0.1.0 bug: download exactly one remote tier
    into a fresh cache, then Resolver.auto() must work and resolve through it.
    """
    import resolvekit
    from resolvekit.core.config import _reset_config

    _reset_config()
    monkeypatch.setenv("RESOLVEKIT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("RESOLVEKIT_AUTO_DOWNLOAD", "1")
    try:
        resolvekit.download("geo.admin1")
        result = resolvekit.resolve("Bavaria", as_result=True)
        assert result.entity_id is not None
    finally:
        _reset_config()
