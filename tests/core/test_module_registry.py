"""Tests for installed module discovery."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Snapshot the real manifest iterators at import time so individual tests
# can opt back into them (see :func:`restore_real_manifest_iterators`).
import resolvekit.core.module_registry as _registry_mod
from resolvekit.core.errors import DataModuleNotFoundError
from resolvekit.core.module_registry import (
    _reset_registrations,
    get_module_path,
    list_available_modules,
    register_module,
    unregister_module,
)

_REAL_ITER_MANIFEST_MODULES = _registry_mod._iter_manifest_modules
_REAL_ITER_MANIFEST_ENTRIES = _registry_mod.iter_manifest_entries


@pytest.fixture(autouse=True)
def _clean_registrations():
    """Clear explicit registrations and manifest cache around every test.

    Manifest-iterator stubbing lives in the shared ``empty_manifest``
    autouse fixture in ``tests/core/conftest.py``; tests that opt back into
    the real iterators request :func:`restore_real_manifest_iterators`.
    """
    _reset_registrations()
    _registry_mod._reset_manifest_cache()
    yield
    _reset_registrations()
    _registry_mod._reset_manifest_cache()


@pytest.fixture
def restore_real_manifest_iterators(monkeypatch: pytest.MonkeyPatch) -> None:
    """Undo the autouse stubs so tests can exercise the real manifest parser.

    Also clears the manifest LRU cache so tests that point
    ``_locate_data_root`` at a custom path actually see their fake payload.
    """
    monkeypatch.setattr(
        "resolvekit.core.module_registry._iter_manifest_modules",
        _REAL_ITER_MANIFEST_MODULES,
    )
    monkeypatch.setattr(
        "resolvekit.core.module_registry.iter_manifest_entries",
        _REAL_ITER_MANIFEST_ENTRIES,
    )
    _registry_mod._reset_manifest_cache()


def _make_module_dir(path: Path, *, module_id: str, domain: str = "geo") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "metadata.json").write_text(
        json.dumps(
            {
                "datapack_id": f"{module_id}-v1",
                "module_id": module_id,
                "domain_pack_id": domain,
                "module_dependencies": [],
                "entity_schema_version": "1.0",
                "feature_schema_version": f"{domain}.features.v1",
                "build_timestamp": "2024-01-01T00:00:00Z",
                "store_file": "entities.sqlite",
            }
        )
    )
    return path


class TestModuleRegistry:
    def test_register_and_get(self, tmp_path: Path) -> None:
        module_dir = _make_module_dir(
            tmp_path / "geo_countries",
            module_id="geo.countries",
        )
        register_module("geo.countries", module_dir)

        assert get_module_path("geo.countries") == module_dir

    def test_unregister(self, tmp_path: Path) -> None:
        module_dir = _make_module_dir(
            tmp_path / "geo_countries",
            module_id="geo.countries",
        )
        register_module("geo.countries", module_dir)

        unregister_module("geo.countries")

        with pytest.raises(DataModuleNotFoundError):
            get_module_path("geo.countries")

    def test_invalid_registered_directory_is_skipped(self, tmp_path: Path) -> None:
        invalid_dir = tmp_path / "invalid"
        invalid_dir.mkdir()
        register_module("geo.countries", invalid_dir)

        with pytest.raises(DataModuleNotFoundError):
            get_module_path("geo.countries")

    def test_list_available_modules_includes_entry_points(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        module_dir = _make_module_dir(
            tmp_path / "geo_admin1",
            module_id="geo.admin1",
        )

        class FakeEntryPoint:
            def __init__(self, name: str, path: Path) -> None:
                self.name = name
                self._path = path

            def load(self):
                return lambda: self._path

        monkeypatch.setattr(
            "resolvekit.core.module_registry._iter_module_entry_points",
            lambda: [FakeEntryPoint("geo.admin1", module_dir)],
        )

        assert list_available_modules() == {"geo.admin1": module_dir}

    def test_entry_point_name_must_match_metadata(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        module_dir = _make_module_dir(
            tmp_path / "geo_admin1",
            module_id="geo.actual",
        )

        class FakeEntryPoint:
            name = "geo.admin1"

            def load(self):
                return lambda: module_dir

        monkeypatch.setattr(
            "resolvekit.core.module_registry._iter_module_entry_points",
            lambda: [FakeEntryPoint()],
        )

        assert list_available_modules() == {}

    def test_not_found_error_lists_available_modules(self, tmp_path: Path) -> None:
        register_module(
            "geo.countries",
            _make_module_dir(tmp_path / "geo_countries", module_id="geo.countries"),
        )

        with pytest.raises(DataModuleNotFoundError) as exc_info:
            get_module_path("geo.cities")

        assert exc_info.value.module_id == "geo.cities"
        assert exc_info.value.searched == ["geo.countries"]


class TestManifestDiscovery:
    """Coverage for manifest-first discovery precedence."""

    def test_manifest_entries_are_discovered(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        module_dir = _make_module_dir(
            tmp_path / "geo_countries",
            module_id="geo.countries",
        )

        monkeypatch.setattr(
            "resolvekit.core.module_registry._iter_manifest_modules",
            lambda: iter([("geo.countries", module_dir)]),
        )

        assert list_available_modules() == {"geo.countries": module_dir}
        assert get_module_path("geo.countries") == module_dir

    def test_manifest_wins_over_registered(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        manifest_dir = _make_module_dir(
            tmp_path / "manifest_countries",
            module_id="geo.countries",
        )
        registered_dir = _make_module_dir(
            tmp_path / "registered_countries",
            module_id="geo.countries",
        )

        monkeypatch.setattr(
            "resolvekit.core.module_registry._iter_manifest_modules",
            lambda: iter([("geo.countries", manifest_dir)]),
        )
        register_module("geo.countries", registered_dir)

        assert list_available_modules() == {"geo.countries": manifest_dir}

    def test_registered_additive_when_manifest_lacks_module(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        manifest_dir = _make_module_dir(
            tmp_path / "manifest_countries",
            module_id="geo.countries",
        )
        registered_dir = _make_module_dir(
            tmp_path / "registered_regions",
            module_id="geo.regions",
        )

        monkeypatch.setattr(
            "resolvekit.core.module_registry._iter_manifest_modules",
            lambda: iter([("geo.countries", manifest_dir)]),
        )
        register_module("geo.regions", registered_dir)

        assert list_available_modules() == {
            "geo.countries": manifest_dir,
            "geo.regions": registered_dir,
        }

    def test_missing_manifest_is_tolerated(
        self,
        tmp_path: Path,
        restore_real_manifest_iterators: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A missing manifest file must not raise; registered modules still win."""
        # Point the manifest locator at a directory with no manifest.json.
        empty_root = tmp_path / "no_such_dir"
        empty_root.mkdir()
        monkeypatch.setattr(
            "resolvekit.core.module_registry._locate_data_root",
            lambda: empty_root,
        )

        registered_dir = _make_module_dir(
            tmp_path / "registered_countries",
            module_id="geo.countries",
        )
        register_module("geo.countries", registered_dir)

        assert list_available_modules() == {"geo.countries": registered_dir}

    def test_manifest_invalid_entries_are_skipped(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        restore_real_manifest_iterators: None,
    ) -> None:
        """Parser logs and skips bad entries, yields the good one."""
        data_root = tmp_path / "data_root"
        data_root.mkdir()
        good_dir = _make_module_dir(
            data_root / "geo" / "countries",
            module_id="geo.countries",
        )
        manifest = {
            "schema_version": 1,
            "modules": [
                {"module_id": "bad_no_domain"},  # missing domain -> skipped
                {"domain": "geo"},  # missing module_id -> skipped
                {"module_id": "no_dot", "domain": "geo"},  # no '.' -> skipped
                {"module_id": "geo.countries", "domain": "geo"},
            ],
        }
        (data_root / "manifest.json").write_text(json.dumps(manifest))

        monkeypatch.setattr(
            "resolvekit.core.module_registry._locate_data_root",
            lambda: data_root,
        )

        assert list_available_modules() == {"geo.countries": good_dir}

    def test_missing_manifest_file_returns_empty(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        restore_real_manifest_iterators: None,
    ) -> None:
        """``_iter_manifest_modules`` tolerates an absent manifest.json."""
        empty_root = tmp_path / "empty"
        empty_root.mkdir()
        monkeypatch.setattr(
            "resolvekit.core.module_registry._locate_data_root",
            lambda: empty_root,
        )

        # No manifest file in empty_root => no modules discovered, no error.
        assert list_available_modules() == {}


class TestIsModuleRemote:
    """``is_module_remote`` must use the manifest as authoritative."""

    def test_manifest_says_remote_beats_on_disk_bundled(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        restore_real_manifest_iterators: None,
    ) -> None:
        """Manifest ``"remote"`` takes precedence over on-disk ``"bundled"``."""
        from resolvekit.core.module_registry import is_module_remote

        data_root = tmp_path / "data_root"
        data_root.mkdir()
        module_dir = _make_module_dir(
            data_root / "geo" / "cities",
            module_id="geo.cities",
        )
        # On-disk metadata says bundled
        (module_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "datapack_id": "geo.cities-v1",
                    "module_id": "geo.cities",
                    "domain_pack_id": "geo",
                    "entity_schema_version": "1.0",
                    "feature_schema_version": "geo.features.v1",
                    "build_timestamp": "2024-01-01T00:00:00Z",
                    "distribution": "bundled",
                }
            )
        )
        # Manifest says remote
        (data_root / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "modules": [
                        {
                            "module_id": "geo.cities",
                            "domain": "geo",
                            "distribution": "remote",
                            "remote_artifacts": {
                                "sqlite": {
                                    "url": "https://example.com/x.sqlite.gz",
                                    "sha256": "abc",
                                    "gz_sha256": "def",
                                    "size_mb": 100.0,
                                },
                            },
                        },
                    ],
                }
            )
        )
        monkeypatch.setattr(
            "resolvekit.core.module_registry._locate_data_root",
            lambda: data_root,
        )

        assert is_module_remote("geo.cities") is True

    def test_unknown_module_returns_false(self) -> None:
        from resolvekit.core.module_registry import is_module_remote

        assert is_module_remote("nonexistent.module") is False


class TestLoadModuleMetadata:
    """``load_module_metadata`` applies manifest overrides to the loaded metadata."""

    def test_override_promotes_bundled_to_remote(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        restore_real_manifest_iterators: None,
    ) -> None:
        from resolvekit.core.module_registry import load_module_metadata

        data_root = tmp_path / "data_root"
        data_root.mkdir()
        module_dir = data_root / "geo" / "cities"
        module_dir.mkdir(parents=True)
        (module_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "datapack_id": "geo.cities-v1",
                    "module_id": "geo.cities",
                    "domain_pack_id": "geo",
                    "entity_schema_version": "1.0",
                    "feature_schema_version": "geo.features.v1",
                    "build_timestamp": "2024-01-01T00:00:00Z",
                    "distribution": "bundled",
                }
            )
        )
        (data_root / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "modules": [
                        {
                            "module_id": "geo.cities",
                            "domain": "geo",
                            "distribution": "remote",
                            "remote_artifacts": {
                                "sqlite": {
                                    "url": (
                                        "https://example.com/geo-cities-entities.sqlite.gz"
                                    ),
                                    "sha256": "abc",
                                    "gz_sha256": "def",
                                    "size_mb": 100.0,
                                },
                            },
                        },
                    ],
                }
            )
        )
        monkeypatch.setattr(
            "resolvekit.core.module_registry._locate_data_root",
            lambda: data_root,
        )

        metadata = load_module_metadata("geo.cities", module_dir)
        assert metadata.distribution == "remote"
        assert metadata.remote_url == (
            "https://example.com/geo-cities-entities.sqlite.gz"
        )
        assert metadata.download_size_mb == 100.0
        assert metadata.remote_artifacts is not None
        sqlite_spec = metadata.remote_artifacts["sqlite"]
        assert sqlite_spec.sha256 == "abc"
        assert sqlite_spec.gz_sha256 == "def"
