"""Tests for public download API."""

from __future__ import annotations

import hashlib
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

from resolvekit.core.config import _reset_config
from resolvekit.core.datapack import DataPackMetadata, RemoteArtifactSpec
from resolvekit.core.download_api import (
    clear_cache,
    download,
    download_all,
)


def _make_metadata(
    module_id: str,
    distribution: str = "bundled",
    remote_url: str | None = None,
    download_size_mb: float | None = None,
) -> DataPackMetadata:
    sha = hashlib.sha256(b"test").hexdigest()
    gz_sha = hashlib.sha256(b"test-gz").hexdigest()
    kwargs: dict = {
        "datapack_id": f"{module_id}-v2026.1",
        "module_id": module_id,
        "domain_pack_id": module_id.split(".", maxsplit=1)[0],
        "entity_schema_version": "1.0",
        "feature_schema_version": f"{module_id.split('.', maxsplit=1)[0]}.features.v1",
        "build_timestamp": "2026-01-01T00:00:00Z",
        "distribution": distribution,
    }
    if distribution == "remote":
        kwargs["remote_artifacts"] = {
            "sqlite": RemoteArtifactSpec(
                url=remote_url or f"https://example.com/{module_id}.sqlite.gz",
                sha256=sha,
                gz_sha256=gz_sha,
                size_mb=download_size_mb,
            ),
        }
    return DataPackMetadata(**kwargs)


@pytest.fixture(autouse=True)
def _clean_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None, None, None]:
    _reset_config()
    monkeypatch.setenv("RESOLVEKIT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("RESOLVEKIT_AUTO_DOWNLOAD", raising=False)
    monkeypatch.delenv("RESOLVEKIT_OFFLINE", raising=False)
    yield
    _reset_config()


class TestDownload:
    def test_download_single_module(self, tmp_path: Path) -> None:
        meta = _make_metadata("geo.cities", "remote")
        pkg_dir = tmp_path / "geo.cities"
        pkg_dir.mkdir()
        meta.to_file(pkg_dir / "metadata.json")

        available = {"geo.cities": pkg_dir}
        cache_path = tmp_path / "cache" / "geo.cities"

        with (
            patch(
                "resolvekit.core.download_api.list_available_modules",
                return_value=available,
            ),
            patch("resolvekit.core.download_api.is_cached", return_value=False),
            patch(
                "resolvekit.core.download_api.download_module_data",
                return_value=cache_path,
            ) as mock_dl,
        ):
            result = download("geo.cities")
            assert "geo.cities" in result
            mock_dl.assert_called_once()

    def test_download_domain(self, tmp_path: Path) -> None:
        cities_meta = _make_metadata("geo.cities", "remote")
        countries_meta = _make_metadata("geo.countries", "bundled")

        cities_dir = tmp_path / "geo.cities"
        cities_dir.mkdir()
        cities_meta.to_file(cities_dir / "metadata.json")

        countries_dir = tmp_path / "geo.countries"
        countries_dir.mkdir()
        countries_meta.to_file(countries_dir / "metadata.json")

        available = {"geo.cities": cities_dir, "geo.countries": countries_dir}

        with (
            patch(
                "resolvekit.core.download_api.list_available_modules",
                return_value=available,
            ),
            patch("resolvekit.core.download_api.is_cached", return_value=False),
            patch(
                "resolvekit.core.download_api.download_module_data",
                return_value=tmp_path / "cache" / "geo.cities",
            ),
        ):
            result = download("geo")
            # Only remote modules get downloaded
            assert "geo.cities" in result
            assert "geo.countries" not in result

    def test_download_skips_cached(self, tmp_path: Path) -> None:
        meta = _make_metadata("geo.cities", "remote")
        pkg_dir = tmp_path / "geo.cities"
        pkg_dir.mkdir()
        meta.to_file(pkg_dir / "metadata.json")

        available = {"geo.cities": pkg_dir}

        with (
            patch(
                "resolvekit.core.download_api.list_available_modules",
                return_value=available,
            ),
            patch("resolvekit.core.download_api.is_cached", return_value=True),
            patch("resolvekit.core.download_api.download_module_data") as mock_dl,
        ):
            result = download("geo.cities")
            assert "geo.cities" in result
            mock_dl.assert_not_called()


class TestDownloadAll:
    def test_download_all_remote(self, tmp_path: Path) -> None:
        meta = _make_metadata("geo.cities", "remote")
        pkg_dir = tmp_path / "geo.cities"
        pkg_dir.mkdir()
        meta.to_file(pkg_dir / "metadata.json")

        available = {"geo.cities": pkg_dir}

        with (
            patch(
                "resolvekit.core.download_api.list_available_modules",
                return_value=available,
            ),
            patch("resolvekit.core.download_api.is_cached", return_value=False),
            patch(
                "resolvekit.core.download_api.download_module_data",
                return_value=tmp_path / "cache" / "geo.cities",
            ),
        ):
            result = download_all()
            assert "geo.cities" in result


class TestManifestPropagation:
    """download/cache_status must respect manifest authority (not on-disk only)."""

    def test_download_triggers_when_manifest_flips_bundled_to_remote(
        self, tmp_path: Path
    ) -> None:
        """``resolvekit.download('geo.cities')`` must NOT no-op when the
        on-disk metadata.json still records ``"distribution": "bundled"`` but
        the manifest lists it as ``"remote"``.
        """
        # On-disk metadata says bundled
        on_disk = _make_metadata("geo.cities", distribution="bundled")
        pkg_dir = tmp_path / "geo.cities"
        pkg_dir.mkdir()
        on_disk.to_file(pkg_dir / "metadata.json")

        # Manifest says remote
        remote_overrides = {
            "geo.cities": {
                "distribution": "remote",
                "remote_artifacts": {
                    "sqlite": {
                        "url": ("https://example.com/geo-cities-entities.sqlite.gz"),
                        "sha256": "a" * 64,
                        "gz_sha256": "b" * 64,
                        "size_mb": 100.0,
                    },
                },
                "checksums": None,
            }
        }

        available = {"geo.cities": pkg_dir}
        cache_path = tmp_path / "cache" / "geo.cities"

        with (
            patch(
                "resolvekit.core.download_api.list_available_modules",
                return_value=available,
            ),
            patch(
                "resolvekit.core.download_api.get_manifest_overrides",
                return_value=remote_overrides,
            ),
            patch("resolvekit.core.download_api.is_cached", return_value=False),
            patch(
                "resolvekit.core.download_api.download_module_data",
                return_value=cache_path,
            ) as mock_dl,
        ):
            result = download("geo.cities")

            # MUST have invoked the download path (no-op would skip this)
            mock_dl.assert_called_once()
            assert "geo.cities" in result


class TestCacheClear:
    def test_clear_specific_module(self, tmp_path: Path) -> None:
        with patch("resolvekit.core.download_api.clear_module_cache") as mock_clear:
            clear_cache("geo.cities")
            mock_clear.assert_called_once_with("geo.cities")

    def test_clear_all(self) -> None:
        with patch("resolvekit.core.download_api.clear_all_cache") as mock_clear:
            clear_cache(None)
            mock_clear.assert_called_once()
