"""Shared, dependency-free helpers for tool adapters.

Lives outside ``__init__`` so adapters and ``jsoncache`` can import these at
module top without a circular import through the package ``__init__``.
"""

from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _metadata_version
from pathlib import Path


def _pkg_version(dist_name: str) -> str | None:
    """Return installed package version, or None if not installed."""
    try:
        return _metadata_version(dist_name)
    except PackageNotFoundError:
        return None


def _cache_path(directory: Path, key: str) -> Path:
    """Compute the canonical cache file path for an online-adapter query key."""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return directory / f"{digest}.json"
