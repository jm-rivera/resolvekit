"""Tests for Resolver.__repr__ data_version field."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from resolvekit.core.api.resolver import Resolver


@pytest.fixture
def resolver_from_fixture(geo_test_datapack: Path) -> Resolver:
    """Resolver built from the conftest geo_test_datapack fixture.

    The fixture's metadata.json has no 'data_version' field, so
    info.data_version returns None for this resolver.
    """
    return Resolver.from_datapacks(datapack_paths=[geo_test_datapack])


def test_resolver_repr_contains_data_version_field_for_default_auto() -> None:
    """Resolver.auto() repr includes data_version= after the existing fields."""
    r = Resolver.auto()
    r_repr = repr(r)
    pattern = (
        r"Resolver\(domains=\[.*\], routing='auto', state='open', data_version=.*\)$"
    )
    assert re.match(pattern, r_repr), f"repr did not match expected pattern: {r_repr!r}"
    assert "data_version=" in r_repr


def test_resolver_repr_data_version_matches_info() -> None:
    """The data_version in repr equals repr(r.info.data_version)."""
    r = Resolver.auto()
    info_dv = r.info.data_version
    r_repr = repr(r)
    assert f"data_version={info_dv!r}" in r_repr


def test_resolver_repr_after_close_still_includes_data_version(
    resolver_from_fixture: Resolver,
) -> None:
    """Closed resolver repr still contains data_version= and state='closed'.

    The try/except in __repr__ must not raise even after close(); the
    repr must show state='closed' with a data_version segment present.
    """
    resolver_from_fixture.close()
    r_repr = repr(resolver_from_fixture)
    assert "data_version=" in r_repr
    assert "state='closed'" in r_repr


def test_resolver_repr_preserves_existing_fields_unchanged(
    resolver_from_fixture: Resolver,
) -> None:
    """Existing grep patterns continue to match after the repr change."""
    r_repr = repr(resolver_from_fixture)
    assert r_repr.startswith("Resolver(domains=")
    assert "routing='auto'" in r_repr
    assert "state='open'" in r_repr
