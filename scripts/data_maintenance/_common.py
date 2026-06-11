"""Shared helpers for data_maintenance scripts."""

from __future__ import annotations

import difflib
import sys


def emit_yaml_diff(original: str, proposed: str, *, fromfile: str, tofile: str) -> None:
    """Write a unified diff of *original* vs *proposed* to stdout."""
    sys.stdout.writelines(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            proposed.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
        )
    )
