"""Characterization tests for the loading/ subpackage split.

Verifies that:
1. Each loading/ module is importable independently.
2. The public symbols in each module are present and callable.
3. Key functions (_normalize_domain, _resolve_datapack_path) behave correctly.
"""

from __future__ import annotations

import pytest


class TestModuleImports:
    """Each loading/ module must be independently importable."""

    def test_import_pack_loader(self):
        from resolvekit.core.api.loading import pack_loader

        assert hasattr(pack_loader, "_create_pack_instance")
        assert hasattr(pack_loader, "_create_pack_instances")
        assert hasattr(pack_loader, "_validate_feature_schema")

    def test_import_store_builder(self):
        from resolvekit.core.api.loading import store_builder

        assert hasattr(store_builder, "_build_domain_stores")
        assert hasattr(store_builder, "_build_final_stores")

    def test_import_module_catalog(self):
        from resolvekit.core.api.loading import module_catalog

        assert hasattr(module_catalog, "_resolve_requested_module_paths")
        assert hasattr(module_catalog, "_module_data_locally_available")
        assert hasattr(module_catalog, "_load_and_separate_datapacks")
        assert hasattr(module_catalog, "_ensure_remote_data_available")
        assert hasattr(module_catalog, "_validate_module_dependencies")
        assert hasattr(module_catalog, "_validate_overlay_relationships")

    def test_import_paths(self):
        from resolvekit.core.api.loading import paths

        assert hasattr(paths, "_resolve_datapack_path")
        assert hasattr(paths, "_expand_datapack_input")
        assert hasattr(paths, "_normalize_domain")
        assert hasattr(paths, "_resolution_error")
        assert hasattr(paths, "_build_router")
        assert hasattr(paths, "_build_resolver_from_paths")

    def test_import_loading_package(self):
        """loading/__init__.py re-exports all symbols."""
        from resolvekit.core.api import loading

        expected = [
            "_build_domain_stores",
            "_build_final_stores",
            "_build_resolver_from_paths",
            "_build_router",
            "_create_pack_instance",
            "_create_pack_instances",
            "_ensure_remote_data_available",
            "_expand_datapack_input",
            "_load_and_separate_datapacks",
            "_module_data_locally_available",
            "_normalize_domain",
            "_resolution_error",
            "_resolve_datapack_path",
            "_resolve_requested_module_paths",
            "_validate_feature_schema",
            "_validate_module_dependencies",
            "_validate_overlay_relationships",
        ]
        for name in expected:
            assert hasattr(loading, name), f"loading.{name} missing"


class TestNormalizeDomain:
    """Tests for _normalize_domain behaviour."""

    def test_none_returns_none(self):
        from resolvekit.core.api.loading.paths import _normalize_domain

        assert _normalize_domain(None) is None

    def test_string_returns_frozenset(self):
        from resolvekit.core.api.loading.paths import _normalize_domain

        result = _normalize_domain("geo")
        assert result == frozenset({"geo"})

    def test_list_returns_frozenset(self):
        from resolvekit.core.api.loading.paths import _normalize_domain

        result = _normalize_domain(["geo", "org"])
        assert result == frozenset({"geo", "org"})

    def test_dotted_domain_raises(self):
        from resolvekit.core.api.loading.paths import _normalize_domain

        with pytest.raises(ValueError, match="dotted"):
            _normalize_domain("geo.admin1")

    def test_result_is_hashable(self):
        from resolvekit.core.api.loading.paths import _normalize_domain

        result = _normalize_domain("geo")
        # frozenset is hashable; this would raise if it were a plain set
        assert hash(result) is not None


class TestResolveDatapackPath:
    """_resolve_datapack_path raises on missing directory."""

    def test_missing_path_raises(self, tmp_path):
        from resolvekit.core.api.loading.paths import _resolve_datapack_path

        with pytest.raises(FileNotFoundError):
            _resolve_datapack_path(str(tmp_path / "nonexistent"))

    def test_directory_without_metadata_raises(self, tmp_path):
        from resolvekit.core.api.loading.paths import _resolve_datapack_path

        with pytest.raises(FileNotFoundError):
            _resolve_datapack_path(str(tmp_path))

    def test_path_object_returned_as_is(self, tmp_path):
        from resolvekit.core.api.loading.paths import _resolve_datapack_path

        # Path objects are returned as-is even without metadata.json
        result = _resolve_datapack_path(tmp_path)
        assert result == tmp_path
