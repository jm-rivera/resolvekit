"""Integration tests for overlay composition and resolver precedence."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from resolvekit.core.datapack import NORMALIZER_VERSION
from resolvekit.core.model.entity import CodeRecord, EntityRecord, NameRecord
from resolvekit.shared import BaseDataPackBuilder


def _write_simple_metadata(
    path: Path,
    *,
    datapack_id: str,
    module_id: str,
    domain_pack_id: str,
    pack_type: str = "base",
    base_module_ids: list[str] | None = None,
) -> None:
    payload = {
        "datapack_id": datapack_id,
        "module_id": module_id,
        "domain_pack_id": domain_pack_id,
        "module_dependencies": [],
        "entity_schema_version": "1.0.0",
        "feature_schema_version": f"{domain_pack_id}.features.v1",
        "normalizer_version": NORMALIZER_VERSION,
        "build_timestamp": "2024-01-15T10:00:00Z",
        "pack_type": pack_type,
        "store_type": "sqlite",
        "store_file": "entities.sqlite",
    }
    if base_module_ids is not None:
        payload["base_module_ids"] = base_module_ids
        payload["link_keys"] = ["iso3"]
    (path / "metadata.json").write_text(json.dumps(payload))


class TestOverlayIntegration:
    def test_full_overlay_workflow(self, tmp_path: Path) -> None:
        from resolvekit.core.overlay_loader import OverlayLoader
        from resolvekit.core.store.merging import MergingCompositeStore
        from resolvekit.packs.geo.normalizer import GeoNormalizer

        base_dir = tmp_path / "geo.base"
        base_dir.mkdir()
        _write_simple_metadata(
            base_dir,
            datapack_id="geo.base-v1",
            module_id="geo.base",
            domain_pack_id="geo",
        )
        builder = BaseDataPackBuilder(output_dir=base_dir)
        builder.create_database()
        builder.add_entity(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            attrs={"population": 65000000},
        )
        builder.add_code("geo/FRA", "iso3", "FRA", "FRA")
        builder.add_name("geo/FRA", "canonical", "France", "france", lang="en")
        builder.finalize()
        builder.close()

        overlay_dir = tmp_path / "geo.overlay"
        overlay_dir.mkdir()
        _write_simple_metadata(
            overlay_dir,
            datapack_id="geo.overlay-v1",
            module_id="geo.overlay",
            domain_pack_id="geo",
            pack_type="overlay",
            base_module_ids=["geo.base"],
        )
        overlay_builder = BaseDataPackBuilder(output_dir=overlay_dir)
        overlay_builder.create_database()
        overlay_builder.add_entity(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="French Republic",
            canonical_name_norm="french republic",
            attrs={"gdp_usd": 2700000000000},
        )
        overlay_builder.add_code("geo/FRA", "geonameid", "3017382", "3017382")
        overlay_builder.add_name(
            "geo/FRA",
            "official",
            "Republique francaise",
            "republique francaise",
            lang="fr",
        )
        overlay_builder.finalize()
        overlay_builder.close()

        loader = OverlayLoader()
        base_loaded = loader.load(base_dir)
        overlay_loaded = loader.load(
            overlay_dir,
            base_modules={"geo.base": base_loaded},
        )

        class MockStore:
            def __init__(self, entities: dict[str, EntityRecord]) -> None:
                self._entities = entities

            def get_entity(self, entity_id: str) -> EntityRecord | None:
                return self._entities.get(entity_id)

            def lookup_code(self, system: str, value_norm: str) -> list[str]:
                return []

            def lookup_name_exact(
                self, value_norm: str, name_kinds: set[str] | None = None
            ) -> list[str]:
                return []

            def search_fulltext(
                self, query_norm: str, fields: set[str] | None = None, limit: int = 10
            ) -> list[tuple[str, float, int]]:
                return []

            def bulk_get_entities(
                self, entity_ids: list[str]
            ) -> dict[str, EntityRecord]:
                return {
                    entity_id: entity
                    for entity_id, entity in self._entities.items()
                    if entity_id in entity_ids
                }

        base_entity = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            codes=[CodeRecord(system="iso3", value="FRA", value_norm="FRA")],
            names=[NameRecord(value="France", value_norm="france", kind="canonical")],
            attributes={"population": 65000000},
        )
        overlay_entity = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="French Republic",
            canonical_name_norm="french republic",
            codes=[
                CodeRecord(system="geonameid", value="3017382", value_norm="3017382")
            ],
            names=[
                NameRecord(
                    value="Republique francaise",
                    value_norm="republique francaise",
                    kind="official",
                    lang="fr",
                )
            ],
            attributes={"gdp_usd": 2700000000000},
        )

        merged = MergingCompositeStore(
            stores=[
                MockStore({"geo/FRA": base_entity}),
                MockStore({"geo/FRA": overlay_entity}),
            ],
            normalizer=GeoNormalizer(),
        ).get_entity("geo/FRA")

        assert overlay_loaded.base_modules["geo.base"].module_id == "geo.base"
        assert merged is not None
        assert merged.canonical_name == "French Republic"
        assert merged.attributes["population"] == 65000000
        assert merged.attributes["gdp_usd"] == 2700000000000
        assert len(merged.codes) == 2
        assert len(merged.names) == 2

    def test_version_compatibility_enforced(self, tmp_path: Path) -> None:
        from resolvekit.core import IncompatibleVersionError
        from resolvekit.core.overlay_loader import OverlayLoader

        base_dir = tmp_path / "geo.base"
        base_dir.mkdir()
        _write_simple_metadata(
            base_dir,
            datapack_id="geo.base-v1",
            module_id="geo.base",
            domain_pack_id="geo",
        )
        conn = sqlite3.connect(base_dir / "entities.sqlite")
        conn.execute("CREATE TABLE entities (entity_id TEXT PRIMARY KEY)")
        conn.close()

        overlay_dir = tmp_path / "geo.overlay"
        overlay_dir.mkdir()
        _write_simple_metadata(
            overlay_dir,
            datapack_id="geo.overlay-v1",
            module_id="geo.overlay",
            domain_pack_id="geo",
            pack_type="overlay",
            base_module_ids=["geo.base"],
        )
        metadata = json.loads((overlay_dir / "metadata.json").read_text())
        metadata["entity_schema_version"] = "2.0.0"
        (overlay_dir / "metadata.json").write_text(json.dumps(metadata))
        conn = sqlite3.connect(overlay_dir / "entities.sqlite")
        conn.execute("CREATE TABLE entities (entity_id TEXT PRIMARY KEY)")
        conn.close()

        loader = OverlayLoader()
        base_loaded = loader.load(base_dir)

        with pytest.raises(IncompatibleVersionError):
            loader.load(overlay_dir, base_modules={"geo.base": base_loaded})

    def test_multiple_overlays_precedence(self) -> None:
        from resolvekit.core.store.merging import MergingCompositeStore
        from resolvekit.packs.geo.normalizer import GeoNormalizer

        class MockStore:
            def __init__(self, entity: EntityRecord) -> None:
                self._entity = entity

            def get_entity(self, entity_id: str) -> EntityRecord | None:
                return self._entity if entity_id == self._entity.entity_id else None

            def lookup_code(self, system: str, value_norm: str) -> list[str]:
                return []

            def lookup_name_exact(
                self, value_norm: str, name_kinds: set[str] | None = None
            ) -> list[str]:
                return []

            def search_fulltext(
                self, query_norm: str, fields: set[str] | None = None, limit: int = 10
            ) -> list[tuple[str, float, int]]:
                return []

            def bulk_get_entities(
                self, entity_ids: list[str]
            ) -> dict[str, EntityRecord]:
                if self._entity.entity_id in entity_ids:
                    return {self._entity.entity_id: self._entity}
                return {}

        merged = MergingCompositeStore(
            stores=[
                MockStore(
                    EntityRecord(
                        entity_id="geo/FRA",
                        entity_type="geo.country",
                        canonical_name="France",
                        canonical_name_norm="france",
                        attributes={"population": 60, "source": "base"},
                    )
                ),
                MockStore(
                    EntityRecord(
                        entity_id="geo/FRA",
                        entity_type="geo.country",
                        canonical_name="France",
                        canonical_name_norm="france",
                        attributes={"population": 65, "source": "overlay1"},
                    )
                ),
                MockStore(
                    EntityRecord(
                        entity_id="geo/FRA",
                        entity_type="geo.country",
                        canonical_name="French Republic",
                        canonical_name_norm="french republic",
                        attributes={"population": 68, "source": "overlay2"},
                    )
                ),
            ],
            normalizer=GeoNormalizer(),
        ).get_entity("geo/FRA")

        assert merged is not None
        assert merged.canonical_name == "French Republic"
        assert merged.attributes["population"] == 68
        assert merged.attributes["source"] == "overlay2"


class TestResolverOverlayPrecedence:
    def _create_datapack(
        self,
        *,
        path: Path,
        datapack_id: str,
        module_id: str,
        domain_pack_id: str,
        entity_id: str,
        canonical_name: str,
        attrs: dict[str, object],
        pack_type: str = "base",
        base_module_ids: list[str] | None = None,
        store_type: str = "sqlite",
    ) -> None:
        path.mkdir(parents=True, exist_ok=True)
        with BaseDataPackBuilder(output_dir=path) as builder:
            builder.create_database()
            builder.add_entity(
                entity_id=entity_id,
                entity_type=f"{domain_pack_id}.country",
                canonical_name=canonical_name,
                canonical_name_norm=canonical_name.lower(),
                attrs=attrs,
            )
            builder.add_code(
                entity_id=entity_id,
                system="iso3",
                value=entity_id.rsplit("/", maxsplit=1)[-1],
                value_norm=entity_id.rsplit("/", maxsplit=1)[-1].lower(),
            )
            builder.finalize()

        metadata = {
            "datapack_id": datapack_id,
            "module_id": module_id,
            "domain_pack_id": domain_pack_id,
            "module_dependencies": [],
            "entity_schema_version": "1.0.0",
            "feature_schema_version": f"{domain_pack_id}.features.v1",
            "normalizer_version": NORMALIZER_VERSION,
            "build_timestamp": "2024-01-15T10:00:00Z",
            "pack_type": pack_type,
            "store_type": store_type,
            "store_file": "entities.sqlite",
        }
        if base_module_ids is not None:
            metadata["base_module_ids"] = base_module_ids
            metadata["link_keys"] = ["iso3"]
        (path / "metadata.json").write_text(json.dumps(metadata))

    def test_resolver_from_datapacks_overlay_wins(self, tmp_path: Path) -> None:
        from resolvekit.core.api.resolver import Resolver
        from resolvekit.core.store import SQLiteEntityStore
        from resolvekit.core.store.merging import MergingCompositeStore
        from resolvekit.packs.geo.normalizer import GeoNormalizer

        base_dir = tmp_path / "geo.base"
        self._create_datapack(
            path=base_dir,
            datapack_id="geo.base-v1",
            module_id="geo.base",
            domain_pack_id="geo",
            entity_id="geo/FRA",
            canonical_name="France",
            attrs={"population": 60000000, "source": "base"},
        )

        overlay_dir = tmp_path / "geo.overlay"
        self._create_datapack(
            path=overlay_dir,
            datapack_id="geo.overlay-v1",
            module_id="geo.overlay",
            domain_pack_id="geo",
            entity_id="geo/FRA",
            canonical_name="French Republic",
            attrs={"population": 68000000, "source": "overlay"},
            pack_type="overlay",
            base_module_ids=["geo.base"],
        )

        merged = MergingCompositeStore(
            stores=[
                SQLiteEntityStore(base_dir / "entities.sqlite"),
                SQLiteEntityStore(overlay_dir / "entities.sqlite"),
            ],
            normalizer=GeoNormalizer(),
        ).get_entity("geo/FRA")
        assert merged is not None
        assert merged.canonical_name == "French Republic"
        assert merged.attributes["source"] == "overlay"
        assert merged.attributes["population"] == 68000000

        resolver = Resolver.from_datapacks(
            datapack_paths=[base_dir, overlay_dir], domains=["geo"]
        )
        assert resolver.resolve("France").entity_id == "geo/FRA"

    def test_resolver_rejects_unsupported_store_type(self, tmp_path: Path) -> None:
        from resolvekit.core import UnsupportedStoreError
        from resolvekit.core.api.resolver import Resolver

        pack_dir = tmp_path / "bad_pack"
        self._create_datapack(
            path=pack_dir,
            datapack_id="bad-pack-v1",
            module_id="geo.bad",
            domain_pack_id="geo",
            entity_id="geo/FRA",
            canonical_name="France",
            attrs={},
            store_type="postgres",
        )

        with pytest.raises(UnsupportedStoreError) as exc_info:
            Resolver.from_datapacks(datapack_paths=[pack_dir])

        assert exc_info.value.store_type == "postgres"

    def test_pack_filter_skips_unrequested_domains(self, tmp_path: Path) -> None:
        from resolvekit.core.api.resolver import Resolver

        geo_dir = tmp_path / "geo.base"
        self._create_datapack(
            path=geo_dir,
            datapack_id="geo.base-v1",
            module_id="geo.base",
            domain_pack_id="geo",
            entity_id="geo/FRA",
            canonical_name="France",
            attrs={"source": "geo"},
        )

        org_dir = tmp_path / "org.bad"
        self._create_datapack(
            path=org_dir,
            datapack_id="org.bad-v1",
            module_id="org.bad",
            domain_pack_id="org",
            entity_id="org/EU",
            canonical_name="European Union",
            attrs={},
            store_type="postgres",
        )

        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_dir, org_dir], domains=["geo"]
        )
        assert resolver.resolve("France").entity_id == "geo/FRA"
