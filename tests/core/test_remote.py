"""Tests for remote data pack download infrastructure."""

from __future__ import annotations

import gzip
import hashlib
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from resolvekit.core.config import _reset_config, configure
from resolvekit.core.datapack import DataPackMetadata, RemoteArtifactSpec
from resolvekit.core.errors import DataPackNotAvailableError
from resolvekit.core.remote import (
    _make_fetcher,
    _module_cache_dir,
    clear_module_cache,
    download_module_data,
    ensure_datapack_ready,
    is_cached,
)


@pytest.fixture()
def remote_metadata(tmp_path: Path) -> DataPackMetadata:
    """Create a remote metadata instance with one sqlite artifact."""
    sqlite_content = b"fake sqlite content for testing"
    sqlite_sha256 = hashlib.sha256(sqlite_content).hexdigest()
    gz_content = gzip.compress(sqlite_content)
    gz_sha256 = hashlib.sha256(gz_content).hexdigest()

    return DataPackMetadata(
        datapack_id="geo.cities-v2026.1",
        module_id="geo.cities",
        domain_pack_id="geo",
        entity_schema_version="1.0",
        feature_schema_version="geo.features.v1",
        build_timestamp="2026-01-01T00:00:00Z",
        distribution="remote",
        remote_artifacts={
            "sqlite": RemoteArtifactSpec(
                url="https://github.com/jm-rivera/resolvekit/releases/download/data-v2026.1/geo-cities-entities.sqlite.gz",
                sha256=sqlite_sha256,
                gz_sha256=gz_sha256,
                size_mb=117.0,
            ),
        },
    )


@pytest.fixture()
def remote_metadata_multi(tmp_path: Path) -> DataPackMetadata:
    """Create a remote metadata instance with sqlite + symspell artifacts."""
    sqlite_content = b"fake sqlite content for testing"
    sqlite_sha256 = hashlib.sha256(sqlite_content).hexdigest()
    sqlite_gz_sha256 = hashlib.sha256(gzip.compress(sqlite_content)).hexdigest()

    symspell_content = b"fake symspell dictionary bytes"
    symspell_sha256 = hashlib.sha256(symspell_content).hexdigest()
    symspell_gz_sha256 = hashlib.sha256(gzip.compress(symspell_content)).hexdigest()

    return DataPackMetadata(
        datapack_id="geo.cities-v2026.1",
        module_id="geo.cities",
        domain_pack_id="geo",
        entity_schema_version="1.0",
        feature_schema_version="geo.features.v1",
        build_timestamp="2026-01-01T00:00:00Z",
        distribution="remote",
        artifacts={"symspell": "symspell.dict"},
        remote_artifacts={
            "sqlite": RemoteArtifactSpec(
                url="https://example.com/data-v2026.1/geo-cities-entities.sqlite.gz",
                sha256=sqlite_sha256,
                gz_sha256=sqlite_gz_sha256,
                size_mb=117.0,
            ),
            "symspell": RemoteArtifactSpec(
                url="https://example.com/data-v2026.1/geo-cities-symspell.dict.gz",
                sha256=symspell_sha256,
                gz_sha256=symspell_gz_sha256,
                size_mb=2.6,
            ),
        },
    )


@pytest.fixture()
def bundled_metadata() -> DataPackMetadata:
    return DataPackMetadata(
        datapack_id="geo.countries-v2026.1",
        module_id="geo.countries",
        domain_pack_id="geo",
        entity_schema_version="1.0",
        feature_schema_version="geo.features.v1",
        build_timestamp="2026-01-01T00:00:00Z",
        distribution="bundled",
    )


@pytest.fixture()
def package_dir(tmp_path: Path, remote_metadata: DataPackMetadata) -> Path:
    """Create a mock package datapack dir with metadata.json."""
    pkg = tmp_path / "package_datapack"
    pkg.mkdir()
    remote_metadata.to_file(pkg / "metadata.json")
    return pkg


@pytest.fixture(autouse=True)
def _reset_config_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None, None, None]:
    """Reset config and use tmp_path as cache dir for all tests."""
    _reset_config()
    monkeypatch.setenv("RESOLVEKIT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("RESOLVEKIT_AUTO_DOWNLOAD", raising=False)
    monkeypatch.delenv("RESOLVEKIT_OFFLINE", raising=False)
    yield
    _reset_config()


class TestEnsureDatapackReady:
    def test_bundled_returns_package_dir(
        self, bundled_metadata: DataPackMetadata, tmp_path: Path
    ) -> None:
        pkg_dir = tmp_path / "pkg"
        pkg_dir.mkdir()
        result = ensure_datapack_ready(bundled_metadata, pkg_dir)
        assert result == pkg_dir

    def test_remote_not_cached_auto_download_disabled_raises(
        self,
        remote_metadata: DataPackMetadata,
        package_dir: Path,
    ) -> None:
        with pytest.raises(DataPackNotAvailableError) as exc_info:
            ensure_datapack_ready(remote_metadata, package_dir)
        assert "geo.cities" in str(exc_info.value)
        assert "resolvekit.download" in str(exc_info.value)

    def test_remote_cached_returns_cache_dir(
        self,
        remote_metadata: DataPackMetadata,
        package_dir: Path,
    ) -> None:
        # Pre-populate cache with correct hash
        cache_dir = _module_cache_dir(remote_metadata.module_id)
        cache_dir.mkdir(parents=True)
        sqlite_content = b"fake sqlite content for testing"
        (cache_dir / "entities.sqlite").write_bytes(sqlite_content)

        result = ensure_datapack_ready(remote_metadata, package_dir)
        assert result == cache_dir

    def test_remote_auto_download_calls_download(
        self,
        remote_metadata: DataPackMetadata,
        package_dir: Path,
    ) -> None:
        configure(auto_download=True)
        with patch("resolvekit.core.remote.download_module_data") as mock_download:
            cache = _module_cache_dir(remote_metadata.module_id)
            mock_download.return_value = cache
            result = ensure_datapack_ready(remote_metadata, package_dir)
            mock_download.assert_called_once_with(remote_metadata, package_dir)
            assert result == cache

    def test_offline_mode_raises(
        self,
        remote_metadata: DataPackMetadata,
        package_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("RESOLVEKIT_OFFLINE", "1")
        with pytest.raises(DataPackNotAvailableError):
            ensure_datapack_ready(remote_metadata, package_dir)


class TestIsCached:
    def test_remote_not_cached(self, remote_metadata: DataPackMetadata) -> None:
        assert is_cached(remote_metadata) is False

    def test_remote_cached_correct_hash(
        self, remote_metadata: DataPackMetadata
    ) -> None:
        cache_dir = _module_cache_dir(remote_metadata.module_id)
        cache_dir.mkdir(parents=True)
        (cache_dir / "entities.sqlite").write_bytes(b"fake sqlite content for testing")
        assert is_cached(remote_metadata) is True

    def test_remote_cached_wrong_hash(self, remote_metadata: DataPackMetadata) -> None:
        cache_dir = _module_cache_dir(remote_metadata.module_id)
        cache_dir.mkdir(parents=True)
        (cache_dir / "entities.sqlite").write_bytes(b"wrong content")
        assert is_cached(remote_metadata) is False


class TestClearModuleCache:
    def test_clears_existing(self, remote_metadata: DataPackMetadata) -> None:
        cache_dir = _module_cache_dir(remote_metadata.module_id)
        cache_dir.mkdir(parents=True)
        (cache_dir / "entities.sqlite").write_bytes(b"data")
        clear_module_cache(remote_metadata.module_id)
        assert not cache_dir.exists()

    def test_noop_if_not_exists(self) -> None:
        clear_module_cache("nonexistent.module")


class TestDownloadModuleData:
    def test_offline_raises(
        self,
        remote_metadata: DataPackMetadata,
        package_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("RESOLVEKIT_OFFLINE", "1")
        with pytest.raises(DataPackNotAvailableError):
            download_module_data(remote_metadata, package_dir)

    def test_copies_metadata_and_downloads_sqlite(
        self,
        remote_metadata: DataPackMetadata,
        package_dir: Path,
    ) -> None:
        """metadata.json is copied from the wheel; sqlite is fetched + renamed."""
        sqlite_content = b"fake sqlite content for testing"

        def fake_fetch(
            fname: str, progressbar: bool = False, processor: object = None
        ) -> str:
            cache_dir = _module_cache_dir(remote_metadata.module_id)
            cache_dir.mkdir(parents=True, exist_ok=True)
            decompressed_name = (
                fname.removesuffix(".gz") if fname.endswith(".gz") else fname
            )
            sqlite_path = cache_dir / decompressed_name
            sqlite_path.write_bytes(sqlite_content)
            return str(sqlite_path)

        with patch("resolvekit.core.remote._make_fetcher") as mock_fetcher:
            fetcher = MagicMock()
            fetcher.fetch.side_effect = fake_fetch
            mock_fetcher.return_value = fetcher

            result = download_module_data(remote_metadata, package_dir)

            assert (result / "metadata.json").exists()
            assert (result / "entities.sqlite").exists()
            assert (result / "entities.sqlite").read_bytes() == sqlite_content

    def test_downloads_every_remote_artifact(
        self,
        remote_metadata_multi: DataPackMetadata,
        tmp_path: Path,
    ) -> None:
        """sqlite AND symspell.dict are both fetched + renamed to local filenames."""
        pkg = tmp_path / "package_datapack"
        pkg.mkdir()
        remote_metadata_multi.to_file(pkg / "metadata.json")

        sqlite_content = b"fake sqlite content for testing"
        symspell_content = b"fake symspell dictionary bytes"
        payloads = {
            "geo-cities-entities.sqlite.gz": sqlite_content,
            "geo-cities-symspell.dict.gz": symspell_content,
        }

        def fake_fetch(
            fname: str, progressbar: bool = False, processor: object = None
        ) -> str:
            cache_dir = _module_cache_dir(remote_metadata_multi.module_id)
            cache_dir.mkdir(parents=True, exist_ok=True)
            decompressed_name = fname.removesuffix(".gz")
            out = cache_dir / decompressed_name
            out.write_bytes(payloads[fname])
            return str(out)

        with patch("resolvekit.core.remote._make_fetcher") as mock_fetcher:
            fetcher = MagicMock()
            fetcher.fetch.side_effect = fake_fetch
            mock_fetcher.return_value = fetcher

            result = download_module_data(remote_metadata_multi, pkg)

        assert (result / "metadata.json").exists()
        assert (result / "entities.sqlite").read_bytes() == sqlite_content
        assert (result / "symspell.dict").read_bytes() == symspell_content
        # And the originally-named decompressed files were renamed away
        assert not (result / "geo-cities-entities.sqlite").exists()
        assert not (result / "geo-cities-symspell.dict").exists()

    def test_mid_download_failure_clears_cache(
        self,
        remote_metadata_multi: DataPackMetadata,
        tmp_path: Path,
    ) -> None:
        """If artifact N fails after N-1 succeeded, cache must be cleared, not
        left half-populated — otherwise is_cached sees the sqlite and blocks
        any retry."""
        pkg = tmp_path / "package_datapack"
        pkg.mkdir()
        remote_metadata_multi.to_file(pkg / "metadata.json")

        sqlite_content = b"fake sqlite content for testing"
        first_call = {"done": False}

        def flaky_fetch(
            fname: str, progressbar: bool = False, processor: object = None
        ) -> str:
            cache_dir = _module_cache_dir(remote_metadata_multi.module_id)
            cache_dir.mkdir(parents=True, exist_ok=True)
            if not first_call["done"]:
                first_call["done"] = True
                out = cache_dir / fname.removesuffix(".gz")
                out.write_bytes(sqlite_content)
                return str(out)
            raise RuntimeError("simulated mid-download failure")

        with patch("resolvekit.core.remote._make_fetcher") as mock_fetcher:
            fetcher = MagicMock()
            fetcher.fetch.side_effect = flaky_fetch
            mock_fetcher.return_value = fetcher

            with pytest.raises(RuntimeError, match="simulated"):
                download_module_data(remote_metadata_multi, pkg)

        # Cache dir must be gone, not half-populated
        cache_dir = _module_cache_dir(remote_metadata_multi.module_id)
        assert not cache_dir.exists()

    def test_partial_cache_is_not_cached(
        self,
        remote_metadata_multi: DataPackMetadata,
    ) -> None:
        """is_cached returns False when sqlite is present but a declared
        artifact (symspell.dict) is missing — defends against a half-cache
        that slipped past the atomic-download guarantee."""
        cache_dir = _module_cache_dir(remote_metadata_multi.module_id)
        cache_dir.mkdir(parents=True)
        # Only sqlite, no symspell.dict
        (cache_dir / "entities.sqlite").write_bytes(b"fake sqlite content for testing")
        assert is_cached(remote_metadata_multi) is False


class TestDataPackMetadataValidation:
    def test_remote_requires_remote_artifacts_sqlite(self) -> None:
        with pytest.raises(ValueError, match="remote_artifacts\\['sqlite'\\]"):
            DataPackMetadata(
                datapack_id="test",
                module_id="geo.cities",
                domain_pack_id="geo",
                entity_schema_version="1.0",
                feature_schema_version="geo.features.v1",
                build_timestamp="2026-01-01T00:00:00Z",
                distribution="remote",
            )

    def test_remote_artifact_keys_must_match_artifacts(self) -> None:
        """remote_artifacts may only contain 'sqlite' + keys declared in artifacts."""
        with pytest.raises(ValueError, match="undeclared artifacts"):
            DataPackMetadata(
                datapack_id="test",
                module_id="geo.cities",
                domain_pack_id="geo",
                entity_schema_version="1.0",
                feature_schema_version="geo.features.v1",
                build_timestamp="2026-01-01T00:00:00Z",
                distribution="remote",
                remote_artifacts={
                    "sqlite": RemoteArtifactSpec(
                        url="https://x", sha256="a", gz_sha256="b"
                    ),
                    "symspell": RemoteArtifactSpec(
                        url="https://x", sha256="a", gz_sha256="b"
                    ),
                },
            )

    def test_remote_missing_spec_for_declared_artifact(self) -> None:
        """Every key in artifacts must have a matching remote_artifacts spec."""
        with pytest.raises(ValueError, match="missing specs for declared artifacts"):
            DataPackMetadata(
                datapack_id="test",
                module_id="geo.cities",
                domain_pack_id="geo",
                entity_schema_version="1.0",
                feature_schema_version="geo.features.v1",
                build_timestamp="2026-01-01T00:00:00Z",
                distribution="remote",
                artifacts={"symspell": "symspell.dict"},
                remote_artifacts={
                    "sqlite": RemoteArtifactSpec(
                        url="https://x", sha256="a", gz_sha256="b"
                    ),
                },
            )

    def test_bundled_rejects_remote_artifacts(self) -> None:
        with pytest.raises(ValueError, match="bundled datapacks must not"):
            DataPackMetadata(
                datapack_id="test",
                module_id="geo.countries",
                domain_pack_id="geo",
                entity_schema_version="1.0",
                feature_schema_version="geo.features.v1",
                build_timestamp="2026-01-01T00:00:00Z",
                distribution="bundled",
                remote_artifacts={
                    "sqlite": RemoteArtifactSpec(
                        url="https://x", sha256="a", gz_sha256="b"
                    ),
                },
            )

    def test_bundled_no_remote_url_ok(self) -> None:
        meta = DataPackMetadata(
            datapack_id="test",
            module_id="geo.countries",
            domain_pack_id="geo",
            entity_schema_version="1.0",
            feature_schema_version="geo.features.v1",
            build_timestamp="2026-01-01T00:00:00Z",
            distribution="bundled",
        )
        assert meta.distribution == "bundled"
        assert meta.remote_url is None
        assert meta.download_size_mb is None


def _sqlite_spec(metadata: DataPackMetadata) -> RemoteArtifactSpec:
    assert metadata.remote_artifacts is not None
    return metadata.remote_artifacts["sqlite"]


class TestReleaseBaseUrlOverride:
    def test_make_fetcher_uses_env_override(
        self,
        remote_metadata: DataPackMetadata,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        custom_base = "https://my-mirror.example.com/releases/"
        monkeypatch.setenv("RESOLVEKIT_RELEASE_BASE_URL", custom_base)
        fetcher = _make_fetcher(remote_metadata, _sqlite_spec(remote_metadata))
        assert fetcher.base_url.startswith(custom_base)

    def test_make_fetcher_without_override_uses_metadata_url(
        self,
        remote_metadata: DataPackMetadata,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("RESOLVEKIT_RELEASE_BASE_URL", raising=False)
        spec = _sqlite_spec(remote_metadata)
        fetcher = _make_fetcher(remote_metadata, spec)
        assert fetcher.base_url in spec.url

    def test_make_fetcher_adds_trailing_slash_to_override(
        self,
        remote_metadata: DataPackMetadata,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(
            "RESOLVEKIT_RELEASE_BASE_URL",
            "https://my-mirror.example.com/releases",
        )
        fetcher = _make_fetcher(remote_metadata, _sqlite_spec(remote_metadata))
        assert fetcher.base_url.endswith("/")
