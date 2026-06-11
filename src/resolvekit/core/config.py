"""Runtime configuration for resolvekit."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


class _Unset:
    """Sentinel type distinguishing "parameter not passed" from a valid value."""

    def __repr__(self) -> str:
        return "<unset>"


_UNSET = _Unset()


@dataclass
class _Config:
    auto_download: bool = False
    cache_dir: Path | None = None
    default_to: str | list[str] | None = None
    on_missing: Literal["raise", "null", "auto"] = "auto"


_config = _Config()


def configure(
    *,
    auto_download: bool | None = None,
    cache_dir: str | Path | None | _Unset = _UNSET,
    default_to: str | list[str] | None | _Unset = _UNSET,
    on_missing: Literal["raise", "null", "auto"] | object = _UNSET,
) -> None:
    """Configure resolvekit runtime behavior.

    Omitting a parameter leaves any previously configured value unchanged.

    Args:
        auto_download: If True, remote packs are downloaded automatically
            when needed. ``None`` leaves the current setting unchanged.
        cache_dir: Custom cache directory for remote data packs.
            ``None`` resets to the platform default (removes any custom path).
            Omitting leaves the current setting unchanged.
        default_to: Default output code system or name variant for
            module-level resolve/bulk/snap (e.g. ``"iso3"``,
            ``["iso3", "name"]``, ``"name:fr"``). ``None`` clears the default
            so resolve() returns a raw ResolutionResult. Omitting leaves
            the current setting unchanged.
        on_missing: Miss policy for the default output chain.
            ``"auto"`` (default) = raise for scalar resolve/snap, null +
            ``UserWarning`` for bulk; ``"raise"`` always raises
            ``OutputMissingError``; ``"null"`` always returns ``None``.
            Omitting this argument leaves any previously configured policy
            unchanged.
    """
    if auto_download is not None:
        _config.auto_download = auto_download
    if cache_dir is not _UNSET:
        # None resets to platform default (removes any custom path).
        _config.cache_dir = (
            Path(cache_dir) if cache_dir is not None else None  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        )
    if default_to is not _UNSET:
        _config.default_to = default_to  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
    if on_missing is not _UNSET:
        _config.on_missing = on_missing  # type: ignore[assignment]  # ty: ignore[invalid-assignment]


def get_default_to() -> str | list[str] | None:
    """Return the configured default output spec (``default_to``)."""
    return _config.default_to


def get_on_missing() -> Literal["raise", "null", "auto"]:
    """Return the configured miss policy (``on_missing``)."""
    return _config.on_missing


def get_auto_download() -> bool:
    """Return whether auto-download is enabled."""
    env = os.environ.get("RESOLVEKIT_AUTO_DOWNLOAD", "").strip()
    if env in ("1", "true", "yes"):
        return True
    return _config.auto_download


def get_offline() -> bool:
    """Return whether offline mode is active (never attempt network)."""
    env = os.environ.get("RESOLVEKIT_OFFLINE", "").strip()
    return env in ("1", "true", "yes")


def get_cache_dir() -> Path:
    """Return the cache directory for remote data packs."""
    if _config.cache_dir is not None:
        return _config.cache_dir

    env = os.environ.get("RESOLVEKIT_CACHE_DIR", "").strip()
    if env:
        return Path(env)

    return _default_cache_dir()


def _default_cache_dir() -> Path:
    """Return the platform-appropriate default cache directory."""
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "resolvekit"


def get_release_base_url() -> str | None:
    """Return the custom release base URL override, if set.

    URL shape contract: the returned value always ends with a trailing slash
    and points at the directory that contains release asset files.  Callers
    append the release-tag sub-path and the asset filename verbatim, so the
    resulting URL looks like::

        <RESOLVEKIT_RELEASE_BASE_URL><tag>/<asset_filename>

    A missing trailing slash in ``RESOLVEKIT_RELEASE_BASE_URL`` is added
    automatically.

    Example::

        RESOLVEKIT_RELEASE_BASE_URL=https://my-mirror.example.com/releases/
    """
    raw = os.environ.get("RESOLVEKIT_RELEASE_BASE_URL", "").strip()
    if not raw:
        return None
    return raw if raw.endswith("/") else raw + "/"


def _reset_config() -> None:
    """Reset configuration to defaults (for testing)."""
    _config.auto_download = False
    _config.cache_dir = None
    _config.default_to = None
    _config.on_missing = "auto"
