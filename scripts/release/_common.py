"""Shared constants and factories for release scripts."""

from __future__ import annotations

from pathlib import Path

from resolvekit.builder.models import BuildOptions

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Canonical v1 layout — ``src/resolvekit/_data/<domain>/<subpath>/``.
_DATAPACKS_ROOT = PROJECT_ROOT / "src" / "resolvekit" / "_data"
_BUILD_ROOT = PROJECT_ROOT / "data" / "build"


def build_release_options() -> BuildOptions:
    """BuildOptions pinned to the repo's release roots, for registry access."""
    return BuildOptions(build_root=_BUILD_ROOT, datapacks_root=_DATAPACKS_ROOT)
