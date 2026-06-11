"""Tests for resolvekit.modules() and ModuleInfo."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from resolvekit.core.api.modules import ModuleInfo, modules


def test_modules_returns_non_empty_list_with_bundled_geo_modules() -> None:
    result = modules()

    assert isinstance(result, list)
    assert len(result) > 0

    bundled_ids = {m.module_id for m in result if m.distribution == "bundled"}
    assert "geo.countries" in bundled_ids
    assert "geo.continental_unions" in bundled_ids
    assert "geo.regions" in bundled_ids

    for m in result:
        if m.distribution == "bundled":
            assert m.is_available is True


def test_modules_includes_remote_modules_with_is_available_flag() -> None:
    result = modules()

    remote = {m.module_id: m for m in result if m.distribution == "remote"}
    # geo.admin1 and geo.cities are remote in the manifest
    assert "geo.admin1" in remote or "geo.cities" in remote

    for m in remote.values():
        assert isinstance(m.is_available, bool)
        assert m.remote_url is not None
        assert m.download_size_mb is not None


def test_modules_returns_sorted_by_module_id() -> None:
    result = modules()
    ids = [m.module_id for m in result]
    assert ids == sorted(ids)


def test_module_info_is_frozen() -> None:
    assert ModuleInfo.model_config.get("frozen") is True

    info = modules()[0]
    with pytest.raises(ValidationError):
        info.module_id = "x"  # type: ignore[misc]


def test_modules_no_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    import resolvekit.core.remote as remote_mod

    def _sentinel(*args: object, **kwargs: object) -> object:
        raise AssertionError("modules() must not trigger a download")

    monkeypatch.setattr(remote_mod, "download_module_data", _sentinel)

    # Should complete without raising
    result = modules()
    assert isinstance(result, list)


def test_modules_entity_types_is_tuple() -> None:
    result = modules()
    assert len(result) > 0
    for m in result:
        assert isinstance(m.entity_types, tuple)
