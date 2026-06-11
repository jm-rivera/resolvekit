"""Shared fixtures for ``tests/core/``.

The ``empty_manifest`` autouse fixture isolates tests from the bundled
``_data/manifest.json`` so registry / download / resolver tests behave the
same whether or not the wheel manifest happens to be present in the
checkout.  Tests that need the real manifest monkeypatch the iterators
back to their real implementations.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from resolvekit.core.module_registry import _reset_manifest_cache


@pytest.fixture(autouse=True)
def empty_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    """Make manifest discovery return no entries for every test.

    Tests that exercise the real manifest restore the iterators explicitly
    (see ``TestManifestDiscovery`` in ``test_module_registry``).  The LRU
    cache is cleared at fixture teardown so the next test starts with a
    fresh parser state regardless of how the current one mutated it.
    """
    monkeypatch.setattr(
        "resolvekit.core.module_registry._iter_manifest_modules",
        lambda: iter(()),
    )
    monkeypatch.setattr(
        "resolvekit.core.module_registry.iter_manifest_entries",
        lambda: iter(()),
    )
    yield
    _reset_manifest_cache()
