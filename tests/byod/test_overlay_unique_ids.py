"""Tests for auto-unique overlay datapack ids.

Verifies that two overlays built in the same namespace produce distinct
module_ids (so neither shadows the other in _load_and_separate_datapacks)
and that both load together without collision.
"""

from __future__ import annotations

import json
from pathlib import Path

from resolvekit.core.api.resolver import Resolver
from resolvekit.core.datapack import NORMALIZER_VERSION
from resolvekit.shared import BaseDataPackBuilder

# ---------------------------------------------------------------------------
# Fixture helpers (copied from test_byod_integration.py pattern)
# ---------------------------------------------------------------------------


def _write_geo_base(path: Path, name: str = "geo.base") -> Path:
    """Build a minimal geo base pack and return the pack dir."""
    pack_dir = path / name
    pack_dir.mkdir(parents=True, exist_ok=True)

    builder = BaseDataPackBuilder(output_dir=pack_dir)
    builder.create_database()
    builder.add_entity(
        entity_id="geo/FRA",
        entity_type="geo.country",
        canonical_name="France",
        canonical_name_norm="france",
        attrs={},
    )
    builder.add_code("geo/FRA", "iso3", "FRA", "fra")
    builder.add_name("geo/FRA", "canonical", "France", "france", lang="en")
    builder.add_entity(
        entity_id="geo/DEU",
        entity_type="geo.country",
        canonical_name="Germany",
        canonical_name_norm="germany",
        attrs={},
    )
    builder.add_code("geo/DEU", "iso3", "DEU", "deu")
    builder.add_name("geo/DEU", "canonical", "Germany", "germany", lang="en")
    builder.finalize()
    builder.close()

    metadata = {
        "datapack_id": "geo.base-byod-fixture-v2",
        "module_id": "geo.base",
        "domain_pack_id": "geo",
        "module_dependencies": [],
        "entity_schema_version": "1.0.0",
        "feature_schema_version": "geo.features.v1",
        "normalizer_version": NORMALIZER_VERSION,
        "build_timestamp": "2024-01-15T10:00:00Z",
        "pack_type": "base",
        "store_type": "sqlite",
        "store_file": "entities.sqlite",
    }
    (pack_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=True) + "\n"
    )
    return pack_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOverlayUniqueIds:
    def test_two_overlays_have_distinct_module_ids(self, tmp_path: Path) -> None:
        """Two overlays with different content in the same namespace get distinct module_ids."""
        base_dir = _write_geo_base(tmp_path)
        r0 = Resolver.from_datapacks(datapack_paths=[base_dir], domains=["geo"])

        # Build ov1: adds alias for FRA; build ov2: adds alias for DEU.
        # Both use the default namespace ("geo"), so without unique-id suffix
        # they would both produce module_id="geo-byod" and the second would
        # overwrite the first in overlay_packs.
        r1 = r0.augment(
            [{"iso3": "FRA", "local": "Frankreich"}],
            link_on=["iso3"],
            add_aliases=["local"],
            cache=False,
        )
        r2 = r0.augment(
            [{"iso3": "DEU", "local": "Allemagne"}],
            link_on=["iso3"],
            add_aliases=["local"],
            cache=False,
        )

        # Extract the overlay module_id from each resolver's _loaded_overlays.
        assert len(r1._loaded_overlays) == 1
        assert len(r2._loaded_overlays) == 1
        id1 = r1._loaded_overlays[0].module_id
        id2 = r2._loaded_overlays[0].module_id

        assert id1 != id2, (
            f"Expected distinct overlay module_ids, got id1={id1!r} == id2={id2!r}"
        )
        # Both should start with "geo-byod-" (namespace-byod-<hash>).
        assert id1.startswith("geo-byod-"), f"Unexpected overlay id format: {id1!r}"
        assert id2.startswith("geo-byod-"), f"Unexpected overlay id format: {id2!r}"

    def test_same_content_same_module_id(self, tmp_path: Path) -> None:
        """Identical-content overlays produce the same module_id (cache stability)."""
        base_dir = _write_geo_base(tmp_path)
        r0 = Resolver.from_datapacks(datapack_paths=[base_dir], domains=["geo"])

        data = [{"iso3": "FRA", "local": "Frankreich"}]
        r1 = r0.augment(data, link_on=["iso3"], add_aliases=["local"], cache=False)
        r2 = r0.augment(data, link_on=["iso3"], add_aliases=["local"], cache=False)

        id1 = r1._loaded_overlays[0].module_id
        id2 = r2._loaded_overlays[0].module_id
        assert id1 == id2, (
            f"Same-content overlays should produce the same module_id; "
            f"got {id1!r} != {id2!r}"
        )

    def test_two_overlays_coexist_via_from_datapacks(self, tmp_path: Path) -> None:
        """Two overlays loaded together via from_datapacks don't shadow each other."""
        base_dir = _write_geo_base(tmp_path)
        r0 = Resolver.from_datapacks(datapack_paths=[base_dir], domains=["geo"])

        # Build the two overlay packs independently so we can pass their dirs
        # directly to from_datapacks.
        from resolvekit.core.api._byod import prepare_augment_pack

        prep_a = prepare_augment_pack(
            data=[{"iso3": "FRA", "local": "Frankreich"}],
            link_on=["iso3"],
            columns=None,
            add_codes=None,
            add_aliases="local",
            add_attrs=None,
            on_miss="skip",
            namespace=None,
            cache=False,
            loaded_modules=r0._loaded_modules,
            loaded_overlays=r0._loaded_overlays,
            available_systems=r0.code_systems(),
        )
        prep_b = prepare_augment_pack(
            data=[{"iso3": "DEU", "local": "Allemagne"}],
            link_on=["iso3"],
            columns=None,
            add_codes=None,
            add_aliases="local",
            add_attrs=None,
            on_miss="skip",
            namespace=None,
            cache=False,
            loaded_modules=r0._loaded_modules,
            loaded_overlays=r0._loaded_overlays,
            available_systems=r0.code_systems(),
        )

        combined = Resolver.from_datapacks(
            datapack_paths=[
                base_dir,
                prep_a.outcome.pack_dir,
                prep_b.outcome.pack_dir,
            ],
            domains=["geo"],
        )

        # Both aliases must resolve — neither overlay should shadow the other.
        result_fra = combined.resolve("Frankreich")
        assert result_fra.entity_id == "geo/FRA", (
            f"Expected geo/FRA for 'Frankreich', got {result_fra.entity_id!r}"
        )

        result_deu = combined.resolve("Allemagne")
        assert result_deu.entity_id == "geo/DEU", (
            f"Expected geo/DEU for 'Allemagne', got {result_deu.entity_id!r}"
        )
