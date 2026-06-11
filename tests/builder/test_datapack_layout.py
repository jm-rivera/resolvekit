"""Tests for resolvekit.builder.datapack_layout."""

from __future__ import annotations

from pathlib import Path

import pytest

from resolvekit.builder.datapack_layout import (
    find_latest_datapack_dir,
    iter_datapack_dirs,
    module_pack_dir,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _touch_metadata(directory: Path) -> None:
    """Create a minimal ``metadata.json`` inside *directory*."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "metadata.json").write_text("{}")


# ---------------------------------------------------------------------------
# find_latest_datapack_dir
# ---------------------------------------------------------------------------


def test_flat_layout_returns_module_dir(tmp_path: Path) -> None:
    """v1 flat: module dir containing metadata.json is returned directly."""
    pack = tmp_path / "geo" / "countries"
    _touch_metadata(pack)

    result = find_latest_datapack_dir(module_dir=pack)

    assert result == pack


def test_no_datapack_returns_none(tmp_path: Path) -> None:
    """Module dir with no metadata.json and no versioned subdirs → None."""
    module_dir = tmp_path / "empty_module"
    module_dir.mkdir()

    result = find_latest_datapack_dir(module_dir=module_dir)

    assert result is None


def test_digit_only_flat_dir_name_is_returned(tmp_path: Path) -> None:
    """D5 rule: a dir named with only digits is still flat if metadata.json present."""
    # A module subpath that happens to be digit-only
    pack = tmp_path / "geo" / "2"
    _touch_metadata(pack)

    result = find_latest_datapack_dir(module_dir=pack)

    assert result == pack


# ---------------------------------------------------------------------------
# iter_datapack_dirs
# ---------------------------------------------------------------------------


def test_iter_flat_layout(tmp_path: Path) -> None:
    """v1 flat layout: all metadata.json parents are returned."""
    _touch_metadata(tmp_path / "geo" / "countries")
    _touch_metadata(tmp_path / "geo" / "admin1")

    result = iter_datapack_dirs(datapacks_root=tmp_path)

    assert set(result) == {
        tmp_path / "geo" / "countries",
        tmp_path / "geo" / "admin1",
    }


def test_iter_multiple_flat_dirs(tmp_path: Path) -> None:
    """Multiple flat packs across domains are all returned."""
    flat_geo = tmp_path / "geo" / "countries"
    flat_org = tmp_path / "org" / "ngo"
    _touch_metadata(flat_geo)
    _touch_metadata(flat_org)

    result = iter_datapack_dirs(datapacks_root=tmp_path)

    assert set(result) == {flat_geo, flat_org}


def test_iter_skips_dot_prefixed_staging_dirs(tmp_path: Path) -> None:
    """Transient publish staging dirs (.<name>.incoming/.prev) are not packs."""
    real = tmp_path / "geo" / "countries"
    _touch_metadata(real)
    # Simulate in-flight / crash-leftover publish staging dirs, which are full
    # packs (they contain metadata.json) but must be ignored by scanners.
    _touch_metadata(tmp_path / "geo" / ".countries.incoming")
    _touch_metadata(tmp_path / "geo" / ".countries.prev")

    result = iter_datapack_dirs(datapacks_root=tmp_path)

    assert result == [real]


def test_iter_root_not_exists_raises(tmp_path: Path) -> None:
    """Missing datapacks_root raises FileNotFoundError."""
    missing = tmp_path / "nonexistent"

    with pytest.raises(FileNotFoundError, match="nonexistent"):
        iter_datapack_dirs(datapacks_root=missing)


def test_iter_empty_root_returns_empty(tmp_path: Path) -> None:
    """An existing but empty datapacks_root returns an empty list."""
    result = iter_datapack_dirs(datapacks_root=tmp_path)

    assert result == []


# ---------------------------------------------------------------------------
# module_pack_dir
# ---------------------------------------------------------------------------


def test_module_pack_dir_simple(tmp_path: Path) -> None:
    """``geo.countries`` maps to ``<root>/geo/countries``."""
    result = module_pack_dir(module_id="geo.countries", datapacks_root=tmp_path)

    assert result == tmp_path / "geo" / "countries"


def test_module_pack_dir_multi_dot_subpath(tmp_path: Path) -> None:
    """Dots in subpath are replaced with underscores."""
    result = module_pack_dir(module_id="geo.sub.pack", datapacks_root=tmp_path)

    assert result == tmp_path / "geo" / "sub_pack"


def test_module_pack_dir_no_dot_raises(tmp_path: Path) -> None:
    """Module ID without any dot raises ValueError."""
    with pytest.raises(ValueError, match=r"'countries'"):
        module_pack_dir(module_id="countries", datapacks_root=tmp_path)


def test_module_pack_dir_empty_domain_raises(tmp_path: Path) -> None:
    """Leading dot (empty domain) raises ValueError."""
    with pytest.raises(ValueError, match=r"'\.countries'"):
        module_pack_dir(module_id=".countries", datapacks_root=tmp_path)


def test_module_pack_dir_empty_subpath_raises(tmp_path: Path) -> None:
    """Trailing dot (empty subpath) raises ValueError."""
    with pytest.raises(ValueError, match=r"'geo\.'"):
        module_pack_dir(module_id="geo.", datapacks_root=tmp_path)
