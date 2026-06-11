"""Tests for resolvekit.builder.geo_shared — focused on read_manifest."""

from __future__ import annotations

import json
from pathlib import Path

import pydantic
import pytest

from resolvekit.builder.geo_shared import GeoManifest, GeoSharedStore

# ---------------------------------------------------------------------------
# read_manifest — happy path
# ---------------------------------------------------------------------------


def test_read_manifest_returns_default_when_no_file(tmp_path: Path) -> None:
    """read_manifest returns default GeoManifest when manifest.json is absent."""
    store = GeoSharedStore(tmp_path)
    manifest = store.read_manifest()

    assert isinstance(manifest, GeoManifest)
    assert manifest.coverage, "default manifest should populate coverage units"


def test_read_manifest_after_ensure_paths(tmp_path: Path) -> None:
    """read_manifest returns a typed GeoManifest after ensure_paths."""
    store = GeoSharedStore(tmp_path)
    store.ensure_paths()
    manifest = store.read_manifest()

    assert isinstance(manifest, GeoManifest)
    assert manifest.coverage


# ---------------------------------------------------------------------------
# read_manifest — error paths
# ---------------------------------------------------------------------------


def test_read_manifest_raises_validation_error_on_bad_schema(tmp_path: Path) -> None:
    """read_manifest raises pydantic.ValidationError for structurally invalid JSON."""
    store = GeoSharedStore(tmp_path)
    store.ensure_paths()
    store.manifest_path.write_text('{"schema_version": "not-an-int"}')

    with pytest.raises(pydantic.ValidationError):
        store.read_manifest()


def test_read_manifest_raises_json_decode_error_on_garbage(tmp_path: Path) -> None:
    """read_manifest raises json.JSONDecodeError for non-JSON content."""
    store = GeoSharedStore(tmp_path)
    store.ensure_paths()
    store.manifest_path.write_text("{not valid json")

    with pytest.raises(json.JSONDecodeError):
        store.read_manifest()
