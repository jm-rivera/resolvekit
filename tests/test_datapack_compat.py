"""Back-compat: old-format datapacks (no data_version) must still load."""

from __future__ import annotations

from pathlib import Path

from resolvekit.core.datapack import DataPackLoader

_GOLDEN_V0 = Path(__file__).parent / "fixtures" / "golden_datapack_v0"


def test_old_format_loads_without_data_version() -> None:
    """Datapacks lacking data_version and min_resolvekit_version must load fine."""
    pack = DataPackLoader(validate_checksums=True).load(_GOLDEN_V0)
    assert pack.metadata.data_version is None
    assert pack.metadata.min_resolvekit_version is None
    assert pack.metadata.module_id == "geo.countries"
