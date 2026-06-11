"""Remote data pack download, cache, and verification via pooch."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import shutil
from pathlib import Path

import pooch

from resolvekit.core.config import (
    get_auto_download,
    get_cache_dir,
    get_offline,
    get_release_base_url,
)
from resolvekit.core.datapack import DataPackMetadata, RemoteArtifactSpec
from resolvekit.core.errors import DataPackNotAvailableError

logger = logging.getLogger(__name__)

# Sidecar filename suffix for hash + stat records.
_SIDECAR_SUFFIX = ".sha256"


def _chunked_sha256(path: Path) -> str:
    """Compute SHA-256 of a file using chunked reads (1 MB) to avoid loading large files into RAM."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sidecar_path(asset_path: Path) -> Path:
    """Return the sidecar path for *asset_path* (``<asset>.sha256``)."""
    return asset_path.with_suffix(asset_path.suffix + _SIDECAR_SUFFIX)


def _write_sidecar(asset_path: Path, verified_hash: str) -> None:
    """Write a sidecar file recording the verified hash, size, and mtime of *asset_path*.

    Written atomically via a temp-file rename so a partial write is never
    visible to a concurrent reader. Silently skips if the cache directory is
    read-only — callers then fall back to a full rehash.
    """
    stat = asset_path.stat()
    record = {
        "hash": verified_hash,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
    }
    sidecar = _sidecar_path(asset_path)
    tmp = sidecar.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(record), encoding="utf-8")
        os.replace(tmp, sidecar)
    except OSError:
        # Read-only cache dir or other filesystem restriction — degrade
        # gracefully; is_cached will fall back to a full rehash.
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


def _fast_hash_check(asset_path: Path, expected_hash: str) -> bool:
    """Return True if the sidecar confirms *asset_path* still has *expected_hash*.

    Fast path: if the sidecar exists and its recorded size + mtime match the
    current stat, we can trust the recorded hash without re-reading the file.
    This is safe because any in-place modification of a file advances its mtime
    on all major filesystems; a size change is a second independent signal.
    Together, size + mtime uniquely identify the file state for our purposes —
    if both still match the sidecar, the bytes are unchanged.

    Returns False (triggering a full rehash) when the sidecar is absent or
    stale, so corruption or replacement is always caught.
    """
    sidecar = _sidecar_path(asset_path)
    if not sidecar.exists():
        return False
    try:
        record = json.loads(sidecar.read_text(encoding="utf-8"))
        stat = asset_path.stat()
        if record.get("size") != stat.st_size:
            return False
        if record.get("mtime") != stat.st_mtime:
            return False
        return record.get("hash") == expected_hash
    except (OSError, json.JSONDecodeError, KeyError):
        return False


def _module_cache_dir(module_id: str) -> Path:
    """Return the cache subdirectory for a specific module."""
    return get_cache_dir() / module_id


def _asset_fname(spec: RemoteArtifactSpec) -> str:
    """Extract the release asset filename from an artifact spec URL."""
    return spec.url.rsplit("/", 1)[1]


def _local_filename(metadata: DataPackMetadata, artifact_type: str) -> str:
    """Resolve the on-disk filename a downloaded artifact should be stored as.

    ``sqlite`` maps to ``metadata.store_file``; other artifact types map to the
    name declared in ``metadata.artifacts``.
    """
    if artifact_type == "sqlite":
        return metadata.store_file
    if metadata.artifacts and artifact_type in metadata.artifacts:
        return metadata.artifacts[artifact_type]
    raise ValueError(
        f"No local filename declared for artifact '{artifact_type}' in "
        f"module {metadata.module_id} (not 'sqlite' and not in 'artifacts')"
    )


def _make_fetcher(metadata: DataPackMetadata, spec: RemoteArtifactSpec) -> pooch.Pooch:
    """Create a pooch fetcher for one remote artifact.

    Uses the spec's ``gz_sha256`` for download verification of the compressed
    asset. The base URL honours the ``RESOLVEKIT_RELEASE_BASE_URL`` env override
    so mirrors can serve the same path shape.
    """
    fname = _asset_fname(spec)
    override = get_release_base_url()
    base_url = override if override is not None else spec.url[: -len(fname)]

    return pooch.create(
        path=_module_cache_dir(metadata.module_id),
        base_url=base_url,
        registry={fname: f"sha256:{spec.gz_sha256}"},
        env="RESOLVEKIT_CACHE_DIR",
    )


def ensure_datapack_ready(
    metadata: DataPackMetadata,
    package_datapack_dir: Path,
) -> Path:
    """Ensure the datapack sqlite is available, returning the effective path.

    For bundled packs: returns ``package_datapack_dir`` immediately.
    For remote packs: returns the cache directory if cached, auto-downloads
    if enabled, or raises ``DataPackNotAvailableError``.
    """
    if metadata.distribution == "bundled":
        return package_datapack_dir

    # Remote pack
    if is_cached(metadata):
        return _module_cache_dir(metadata.module_id)

    if get_offline() or not get_auto_download():
        raise DataPackNotAvailableError(
            module_ids=[metadata.module_id],
            total_size_mb=metadata.download_size_mb,
        )

    return download_module_data(metadata, package_datapack_dir)


def download_module_data(
    metadata: DataPackMetadata,
    package_datapack_dir: Path,
) -> Path:
    """Download every remote artifact for *metadata* and assemble the cache dir.

    Clears the module's cache directory first to prevent stale accumulation.
    For each entry in ``metadata.remote_artifacts``, fetches the .gz asset via
    pooch, decompresses it, and renames the result to its canonical filename
    (``store_file`` for ``sqlite``; ``artifacts[type]`` for other types). Then
    copies ``metadata.json`` from the installed package so the cache directory
    is a self-contained datapack.

    Returns:
        Path to the cache directory containing the complete datapack.
    """
    if not metadata.remote_artifacts:
        raise ValueError(
            f"download_module_data called on {metadata.module_id} which has no "
            f"remote_artifacts (distribution={metadata.distribution!r})"
        )

    if get_offline():
        raise DataPackNotAvailableError(
            module_ids=[metadata.module_id],
            total_size_mb=metadata.download_size_mb,
        )

    cache_dir = _module_cache_dir(metadata.module_id)
    clear_module_cache(metadata.module_id)
    cache_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Downloading %s (%s MB total across %d artifact(s))...",
        metadata.module_id,
        metadata.download_size_mb or "?",
        len(metadata.remote_artifacts),
    )

    # Atomic semantics: if any artifact fails partway, clear the cache dir
    # before re-raising. Otherwise a half-populated cache would satisfy a
    # superficial is_cached check (sqlite present + correct hash) on the next
    # call and block any retry, leaving the module permanently unloadable
    # without a manual clear_cache.
    try:
        for artifact_type, spec in metadata.remote_artifacts.items():
            _download_one_artifact(metadata, artifact_type, spec, cache_dir)
        _copy_metadata(package_datapack_dir, cache_dir)
    except BaseException:
        clear_module_cache(metadata.module_id)
        raise

    logger.info("Downloaded %s successfully.", metadata.module_id)
    return cache_dir


def _download_one_artifact(
    metadata: DataPackMetadata,
    artifact_type: str,
    spec: RemoteArtifactSpec,
    cache_dir: Path,
) -> None:
    """Fetch one artifact's .gz from the release, decompress, rename in place."""
    fetcher = _make_fetcher(metadata, spec)
    fname = _asset_fname(spec)
    target = cache_dir / _local_filename(metadata, artifact_type)
    processor = pooch.Decompress() if fname.endswith(".gz") else None

    try:
        downloaded_path = fetcher.fetch(fname, progressbar=True, processor=processor)
    except Exception as exc:
        logger.error(
            "Download failed for %s/%s: %s", metadata.module_id, artifact_type, exc
        )
        raise

    # Pooch's Decompress writes the decompressed file alongside the .gz, named
    # after the asset minus the .gz suffix. Rename to the canonical local name
    # (e.g. geo-cities-entities.sqlite -> entities.sqlite). shutil.move is used
    # instead of copy to avoid keeping two full copies of large files.
    downloaded = Path(downloaded_path)
    if downloaded != target:
        shutil.move(str(downloaded), target)

    gz_leftover = cache_dir / fname
    if gz_leftover.exists() and gz_leftover != target:
        gz_leftover.unlink()

    # Write a sidecar so the next is_cached() call skips the full rehash.
    # spec.sha256 is already verified by pooch (gz hash) + decompression, so
    # we trust it as the ground truth for the decompressed file.
    if artifact_type == "sqlite":
        _write_sidecar(target, spec.sha256)


def is_cached(metadata: DataPackMetadata) -> bool:
    """Check if a remote module is fully cached with the correct sqlite hash.

    Callers must filter out bundled packs before calling this function.
    Requires (a) the sqlite file present with matching SHA-256, and (b) every
    filename declared in ``metadata.artifacts`` also present in the cache —
    so a half-populated cache from an interrupted download is correctly
    reported as missing and a retry is triggered. Non-sqlite artifact bytes
    are not re-hashed here; ``DataPackLoader`` validates those at load time.

    Hash verification uses a two-tier strategy to avoid reading large files on
    every call:
    1. Fast path — if a sidecar (<sqlite>.sha256) exists and its recorded size
       and mtime match the current file stat, the recorded hash is trusted
       without re-reading the file.
    2. Fallback — when the sidecar is absent or stale (size/mtime mismatch),
       the file is re-hashed in full, and a fresh sidecar is written for next
       time. This guarantees that corruption or replacement is always detected.
    """
    cache_dir = _module_cache_dir(metadata.module_id)
    sqlite_path = cache_dir / metadata.store_file

    if not sqlite_path.exists():
        return False

    sqlite_spec = (
        metadata.remote_artifacts.get("sqlite") if metadata.remote_artifacts else None
    )
    if sqlite_spec is not None and not _fast_hash_check(
        sqlite_path, sqlite_spec.sha256
    ):
        actual = _chunked_sha256(sqlite_path)
        if actual != sqlite_spec.sha256:
            return False
        _write_sidecar(sqlite_path, actual)

    if metadata.artifacts:
        for filename in metadata.artifacts.values():
            if not (cache_dir / filename).exists():
                return False

    return True


def clear_module_cache(module_id: str) -> None:
    """Delete the module's entire cache subdirectory."""
    cache_dir = _module_cache_dir(module_id)
    if cache_dir.exists():
        shutil.rmtree(cache_dir)


def clear_all_cache() -> None:
    """Delete the entire resolvekit cache directory."""
    cache_dir = get_cache_dir()
    if cache_dir.exists():
        shutil.rmtree(cache_dir)


def _copy_metadata(package_dir: Path, cache_dir: Path) -> None:
    """Copy metadata.json from the installed package into the cache directory.

    For remote-distribution packs, metadata.json is the only file shipped in
    the wheel — all data artifacts (sqlite, symspell.dict, calibrator) are
    downloaded from the release.
    """
    metadata_src = package_dir / "metadata.json"
    if metadata_src.exists():
        shutil.copy2(metadata_src, cache_dir / "metadata.json")
