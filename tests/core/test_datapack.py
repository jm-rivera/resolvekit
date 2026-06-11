"""Tests for module datapack metadata and loading."""

from __future__ import annotations

import json
import sqlite3
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from resolvekit.core.datapack import (
    NORMALIZER_VERSION,
    DataPackLoader,
    DataPackMetadata,
    LoadedDataPack,
    _is_version_below,
)
from resolvekit.core.errors import DataPackRuntimeVersionError


def _base_metadata(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "datapack_id": "geo.countries-v1",
        "module_id": "geo.countries",
        "domain_pack_id": "geo",
        "entity_schema_version": "1.0",
        "feature_schema_version": "geo.features.v1",
        "normalizer_version": NORMALIZER_VERSION,
        "build_timestamp": "2024-01-15T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def _write_sqlite(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE entities (entity_id TEXT PRIMARY KEY)")
    conn.close()


class TestDataPackMetadata:
    def test_from_json(self, tmp_path: Path) -> None:
        meta_path = tmp_path / "metadata.json"
        meta_path.write_text(json.dumps(_base_metadata(source_datasets=["geonames"])))

        metadata = DataPackMetadata.from_file(meta_path)

        assert metadata.module_id == "geo.countries"
        assert metadata.domain_pack_id == "geo"
        assert metadata.datapack_id == "geo.countries-v1"

    def test_pack_type_defaults_to_base(self) -> None:
        metadata = DataPackMetadata(**_base_metadata())
        assert metadata.pack_type == "base"

    def test_overlay_requires_base_modules(self) -> None:
        with pytest.raises(ValueError, match="base_module_ids"):
            DataPackMetadata(
                **_base_metadata(
                    datapack_id="geo.overlay-v1",
                    module_id="geo.overlay",
                    pack_type="overlay",
                    link_keys=["iso3"],
                )
            )

    def test_overlay_requires_link_keys(self) -> None:
        with pytest.raises(ValueError, match="link_keys"):
            DataPackMetadata(
                **_base_metadata(
                    datapack_id="geo.overlay-v1",
                    module_id="geo.overlay",
                    pack_type="overlay",
                    base_module_ids=["geo.countries"],
                )
            )

    def test_overlay_roundtrip(self, tmp_path: Path) -> None:
        metadata = DataPackMetadata(
            **_base_metadata(
                datapack_id="geo.overlay-v1",
                module_id="geo.overlay",
                pack_type="overlay",
                base_module_ids=["geo.countries", "geo.admin1"],
                link_keys=["iso3", "dcid"],
                allow_new_entities=True,
                store_file="overlay.sqlite",
            )
        )

        out_path = tmp_path / "metadata.json"
        metadata.to_file(out_path)
        loaded = DataPackMetadata.from_file(out_path)

        assert loaded.pack_type == "overlay"
        assert loaded.base_module_ids == ["geo.countries", "geo.admin1"]
        assert loaded.link_keys == ["iso3", "dcid"]
        assert loaded.allow_new_entities is True
        assert loaded.store_file == "overlay.sqlite"

    def test_base_rejects_base_module_ids(self) -> None:
        with pytest.raises(ValueError, match="base datapacks must not declare"):
            DataPackMetadata(**_base_metadata(base_module_ids=["geo.countries"]))

    def test_missing_required_fields_raise(self, tmp_path: Path) -> None:
        meta_path = tmp_path / "metadata.json"
        meta_path.write_text(json.dumps({"domain_pack_id": "geo"}))

        with pytest.raises(ValidationError):
            DataPackMetadata.from_file(meta_path)


class TestLoadedDataPack:
    def test_db_path_default(self, tmp_path: Path) -> None:
        pack = LoadedDataPack(
            metadata=DataPackMetadata(**_base_metadata()),
            base_path=tmp_path,
        )
        assert pack.db_path == tmp_path / "entities.sqlite"

    def test_db_path_from_artifacts(self, tmp_path: Path) -> None:
        pack = LoadedDataPack(
            metadata=DataPackMetadata(
                **_base_metadata(artifacts={"sqlite": "custom.sqlite"})
            ),
            base_path=tmp_path,
        )
        assert pack.db_path == tmp_path / "custom.sqlite"

    def test_artifact_path(self, tmp_path: Path) -> None:
        pack = LoadedDataPack(
            metadata=DataPackMetadata(
                **_base_metadata(artifacts={"symspell": "symspell.txt"})
            ),
            base_path=tmp_path,
        )
        assert pack.artifact_path("symspell") == tmp_path / "symspell.txt"
        assert pack.artifact_path("missing") is None


class TestDataPackLoader:
    def test_loads_directory(self, tmp_path: Path) -> None:
        (tmp_path / "metadata.json").write_text(json.dumps(_base_metadata()))
        _write_sqlite(tmp_path / "entities.sqlite")

        pack = DataPackLoader().load(tmp_path)

        assert pack.module_id == "geo.countries"
        assert pack.pack_id == "geo"
        assert pack.db_path.exists()

    def test_missing_sqlite_raises(self, tmp_path: Path) -> None:
        (tmp_path / "metadata.json").write_text(json.dumps(_base_metadata()))

        with pytest.raises(FileNotFoundError, match=r"entities\.sqlite"):
            DataPackLoader().load(tmp_path)

    def test_validates_declared_artifacts(self, tmp_path: Path) -> None:
        (tmp_path / "metadata.json").write_text(
            json.dumps(
                _base_metadata(
                    artifacts={
                        "sqlite": "entities.sqlite",
                        "symspell": "missing.txt",
                    }
                )
            )
        )
        _write_sqlite(tmp_path / "entities.sqlite")

        with pytest.raises(FileNotFoundError, match="symspell"):
            DataPackLoader().load(tmp_path)

    def test_uses_store_file_for_overlay(self, tmp_path: Path) -> None:
        (tmp_path / "metadata.json").write_text(
            json.dumps(
                _base_metadata(
                    datapack_id="geo.overlay-v1",
                    module_id="geo.overlay",
                    pack_type="overlay",
                    base_module_ids=["geo.countries"],
                    link_keys=["iso3"],
                    store_file="overlay.sqlite",
                )
            )
        )
        _write_sqlite(tmp_path / "overlay.sqlite")

        pack = DataPackLoader().load(tmp_path)
        assert pack.db_path == tmp_path / "overlay.sqlite"

    def test_validates_checksums(self, tmp_path: Path) -> None:
        sqlite_path = tmp_path / "entities.sqlite"
        _write_sqlite(sqlite_path)
        checksum = sha256(sqlite_path.read_bytes()).hexdigest()
        (tmp_path / "metadata.json").write_text(
            json.dumps(_base_metadata(checksums={"sqlite": checksum}))
        )

        pack = DataPackLoader(validate_checksums=True).load(tmp_path)
        assert pack.db_path == sqlite_path

    def test_raises_on_missing_directory(self) -> None:
        with pytest.raises(FileNotFoundError, match="not found"):
            DataPackLoader().load(Path("/nonexistent/path"))

    def test_raises_on_missing_metadata(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="Metadata"):
            DataPackLoader().load(tmp_path)


class TestDataVersionField:
    def test_data_version_defaults_to_none(self) -> None:
        meta = DataPackMetadata(**_base_metadata())
        assert meta.data_version is None

    def test_data_version_populates(self) -> None:
        meta = DataPackMetadata(**_base_metadata(data_version="2026.04"))
        assert meta.data_version == "2026.04"

    def test_data_version_roundtrips_via_json(self, tmp_path: Path) -> None:
        meta = DataPackMetadata(**_base_metadata(data_version="2026.04"))
        path = tmp_path / "metadata.json"
        meta.to_file(path)
        loaded = DataPackMetadata.from_file(path)
        assert loaded.data_version == "2026.04"

    def test_missing_data_version_field_loads_as_none(self, tmp_path: Path) -> None:
        raw = _base_metadata()
        raw.pop("data_version", None)
        path = tmp_path / "metadata.json"
        path.write_text(json.dumps(raw))
        loaded = DataPackMetadata.from_file(path)
        assert loaded.data_version is None


class TestMinResolveKitVersionField:
    def _make_pack(self, tmp_path: Path, *, min_version: str | None = None) -> Path:
        meta = _base_metadata()
        if min_version is not None:
            meta["min_resolvekit_version"] = min_version
        (tmp_path / "metadata.json").write_text(json.dumps(meta))
        _write_sqlite(tmp_path / "entities.sqlite")
        return tmp_path

    def test_unset_min_version_loads_fine(self, tmp_path: Path) -> None:
        path = self._make_pack(tmp_path)
        pack = DataPackLoader(validate_checksums=False).load(path)
        assert pack.metadata.min_resolvekit_version is None

    def test_current_version_satisfies_min(self, tmp_path: Path) -> None:
        path = self._make_pack(tmp_path, min_version="0.0.1")
        pack = DataPackLoader(validate_checksums=False).load(path)
        assert pack.metadata.module_id == "geo.countries"

    def test_future_min_version_raises(self, tmp_path: Path) -> None:
        path = self._make_pack(tmp_path, min_version="999.0.0")
        with pytest.raises(DataPackRuntimeVersionError, match=r"999\.0\.0"):
            DataPackLoader(validate_checksums=False).load(path)

    def test_error_message_contains_upgrade_hint(self, tmp_path: Path) -> None:
        path = self._make_pack(tmp_path, min_version="999.0.0")
        with pytest.raises(DataPackRuntimeVersionError) as exc_info:
            DataPackLoader(validate_checksums=False).load(path)
        assert "pip install" in str(exc_info.value)


class TestPep440VersionCompare:
    """``_is_version_below`` must honor PEP 440 ordering for pre-releases."""

    def test_equal_versions_not_below(self) -> None:
        assert _is_version_below("1.0b1", "1.0b1") is False

    def test_beta1_below_beta2(self) -> None:
        assert _is_version_below("1.0b1", "1.0b2") is True

    def test_beta2_above_beta1(self) -> None:
        assert _is_version_below("1.0b2", "1.0b1") is False

    def test_prerelease_ordering(self) -> None:
        # PEP 440 order: b1 < b2 < rc1 < 1.0
        assert _is_version_below("1.0b1", "1.0b2") is True
        assert _is_version_below("1.0b2", "1.0rc1") is True
        assert _is_version_below("1.0rc1", "1.0") is True

    def test_rc_above_beta(self) -> None:
        assert _is_version_below("1.0rc1", "1.0b2") is False

    def test_post_release_above_release(self) -> None:
        assert _is_version_below("1.0", "1.0.post1") is True

    def test_invalid_version_falls_back_to_lex(self) -> None:
        # Garbage still compares lexicographically so the gate still fires
        assert _is_version_below("not-a-version-a", "not-a-version-b") is True
        assert _is_version_below("not-a-version-b", "not-a-version-a") is False

    def test_loader_gate_uses_pep440(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """End-to-end: a pack that needs 1.0b2 blocks a 1.0b1 runtime."""
        import importlib.metadata as _ilm

        # Pretend the runtime is 1.0b1
        original_version = _ilm.version

        def fake_version(name: str) -> str:
            if name == "resolvekit":
                return "1.0b1"
            return original_version(name)

        monkeypatch.setattr(_ilm, "version", fake_version)

        meta = _base_metadata()
        meta["min_resolvekit_version"] = "1.0b2"
        (tmp_path / "metadata.json").write_text(json.dumps(meta))
        _write_sqlite(tmp_path / "entities.sqlite")

        with pytest.raises(DataPackRuntimeVersionError, match=r"1\.0b2"):
            DataPackLoader(validate_checksums=False).load(tmp_path)

    def test_loader_gate_allows_equal_prerelease(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Pack requiring 1.0b1 loads on a 1.0b1 runtime (equal)."""
        import importlib.metadata as _ilm

        original_version = _ilm.version

        def fake_version(name: str) -> str:
            if name == "resolvekit":
                return "1.0b1"
            return original_version(name)

        monkeypatch.setattr(_ilm, "version", fake_version)

        meta = _base_metadata()
        meta["min_resolvekit_version"] = "1.0b1"
        (tmp_path / "metadata.json").write_text(json.dumps(meta))
        _write_sqlite(tmp_path / "entities.sqlite")

        pack = DataPackLoader(validate_checksums=False).load(tmp_path)
        assert pack.metadata.min_resolvekit_version == "1.0b1"
