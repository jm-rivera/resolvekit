"""Tests for explicit datapack paths and installed-module composition."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from resolvekit.core.api.loading import _resolve_datapack_path
from resolvekit.core.datapack import NORMALIZER_VERSION
from resolvekit.core.errors import (
    DataModuleNotFoundError,
    ModuleConflictError,
    UnknownDomainError,
)
from resolvekit.core.module_registry import (
    _reset_registrations,
    register_module,
)


@pytest.fixture(autouse=True)
def _clean_registrations():
    """Clear explicit registrations around every test.

    Manifest isolation is provided by the shared ``empty_manifest`` autouse
    fixture in ``tests/core/conftest.py`` so ``register_module`` calls here
    aren't shadowed by manifest-first precedence.
    """
    _reset_registrations()
    yield
    _reset_registrations()


def _make_full_datapack(
    base_path: Path,
    *,
    module_id: str,
    domain: str = "geo",
    entity_rows: list[tuple[str, str, str]] | None = None,
    code_rows: list[tuple[str, str, str]] | None = None,
    relation_rows: list[tuple[str, str, str]] | None = None,
    module_dependencies: list[str] | None = None,
) -> Path:
    base_path.mkdir(parents=True, exist_ok=True)
    db_path = base_path / "entities.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE entities (
            entity_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            canonical_name_norm TEXT NOT NULL,
            valid_from TEXT,
            valid_until TEXT
        );
        CREATE TABLE names (
            entity_id TEXT NOT NULL,
            name_kind TEXT NOT NULL,
            value TEXT NOT NULL,
            value_norm TEXT NOT NULL,
            lang TEXT,
            is_preferred INTEGER DEFAULT 0
        );
        CREATE TABLE codes (
            entity_id TEXT NOT NULL,
            system TEXT NOT NULL,
            value TEXT NOT NULL,
            value_norm TEXT NOT NULL,
            PRIMARY KEY (entity_id, system)
        );
        CREATE TABLE relations (
            entity_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            target_id TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE names_fts USING fts5(entity_id, value_norm);
        """
    )

    for entity_id, entity_type, canonical_name in entity_rows or []:
        normalized = canonical_name.casefold()
        conn.execute(
            "INSERT INTO entities VALUES (?, ?, ?, ?, NULL, NULL)",
            (entity_id, entity_type, canonical_name, normalized),
        )
        conn.execute(
            "INSERT INTO names VALUES (?, 'canonical', ?, ?, 'en', 1)",
            (entity_id, canonical_name, normalized),
        )
        conn.execute(
            "INSERT INTO names_fts(entity_id, value_norm) VALUES (?, ?)",
            (entity_id, normalized),
        )

    for entity_id, system, value in code_rows or []:
        conn.execute(
            "INSERT INTO codes VALUES (?, ?, ?, ?)",
            (entity_id, system, value, value.casefold()),
        )

    for entity_id, relation_type, target_id in relation_rows or []:
        conn.execute(
            "INSERT INTO relations VALUES (?, ?, ?)",
            (entity_id, relation_type, target_id),
        )

    conn.commit()
    conn.close()

    (base_path / "metadata.json").write_text(
        json.dumps(
            {
                "datapack_id": f"{module_id}-v1",
                "module_id": module_id,
                "domain_pack_id": domain,
                "module_dependencies": module_dependencies or [],
                "entity_schema_version": "1.0",
                "feature_schema_version": f"{domain}.features.v1",
                "normalizer_version": NORMALIZER_VERSION,
                "index_versions": {"fts": "fts5"},
                "build_timestamp": "2024-01-01T00:00:00Z",
                "source_datasets": ["test"],
            }
        )
    )
    return base_path


class TestResolveDatapackPath:
    def test_existing_directory(self, tmp_path: Path):
        datapack_dir = _make_full_datapack(
            tmp_path / "geo_data",
            module_id="geo.countries",
            entity_rows=[("country/USA", "geo.country", "United States")],
        )

        assert _resolve_datapack_path(datapack_dir) == datapack_dir
        assert _resolve_datapack_path(str(datapack_dir)) == datapack_dir

    def test_module_id_string_is_not_treated_as_datapack_path(self):
        with pytest.raises(FileNotFoundError, match=r"Resolver\.from_modules"):
            _resolve_datapack_path("geo.countries")


class TestResolverFromModules:
    def test_from_modules_resolves_registered_module(self, tmp_path: Path):
        from resolvekit import Resolver

        module_dir = _make_full_datapack(
            tmp_path / "geo_countries",
            module_id="geo.countries",
            entity_rows=[("country/USA", "geo.country", "United States")],
            code_rows=[("country/USA", "iso2", "US")],
        )
        register_module("geo.countries", module_dir)

        with Resolver.from_modules(module_ids=["geo.countries"]) as resolver:
            assert resolver.resolve("United States").entity_id == "country/USA"

    def test_from_modules_loads_all_registered_modules_when_none(self, tmp_path: Path):
        from resolvekit import Resolver
        from resolvekit.types import RoutingMode

        geo_dir = _make_full_datapack(
            tmp_path / "geo_countries",
            module_id="geo.countries",
            entity_rows=[("country/USA", "geo.country", "United States")],
        )
        org_dir = _make_full_datapack(
            tmp_path / "org_igos",
            module_id="org.igos",
            domain="org",
            entity_rows=[("org/EU", "org.igo", "European Union")],
        )
        register_module("geo.countries", geo_dir)
        register_module("org.igos", org_dir)

        with Resolver.from_modules(
            module_ids=None, routing_mode=RoutingMode.EXPLICIT
        ) as resolver:
            assert (
                resolver.resolve("United States", domain="geo").entity_id
                == "country/USA"
            )
            assert (
                resolver.resolve("European Union", domain="org").entity_id == "org/EU"
            )

    def test_from_modules_does_not_auto_load_declared_dependencies(
        self, tmp_path: Path
    ):
        # Authoritative selection: naming geo.admin1 loads exactly geo.admin1.
        # geo.countries is a declared dependency but was not named, so it is NOT
        # auto-loaded — the load set is a pure function of module_ids, never of
        # which sibling packs happen to be present.
        from resolvekit import Resolver

        countries_dir = _make_full_datapack(
            tmp_path / "geo_countries",
            module_id="geo.countries",
            entity_rows=[("country/USA", "geo.country", "United States")],
        )
        admin1_dir = _make_full_datapack(
            tmp_path / "geo_admin1",
            module_id="geo.admin1",
            entity_rows=[("admin1/US-CA", "geo.admin1", "California")],
            relation_rows=[("admin1/US-CA", "contained_in", "country/USA")],
            module_dependencies=["geo.countries"],
        )
        register_module("geo.countries", countries_dir)
        register_module("geo.admin1", admin1_dir)

        with Resolver.from_modules(module_ids=["geo.admin1"]) as resolver:
            assert resolver.resolve("California").entity_id == "admin1/US-CA"
            assert resolver.resolve("United States").entity_id is None

    def test_from_modules_loads_exactly_the_named_modules(self, tmp_path: Path):
        # Naming both modules opts in to both — the caller controls the load set
        # explicitly. (Contrast with the test above, where the unnamed dependency
        # stays out.)
        from resolvekit import Resolver

        regions_dir = _make_full_datapack(
            tmp_path / "geo_regions",
            module_id="geo.regions",
            entity_rows=[("region/NAM", "geo.region", "North America")],
        )
        countries_dir = _make_full_datapack(
            tmp_path / "geo_countries",
            module_id="geo.countries",
            entity_rows=[("country/USA", "geo.country", "United States")],
            relation_rows=[("country/USA", "contained_in", "region/NAM")],
            module_dependencies=["geo.regions"],
        )
        register_module("geo.regions", regions_dir)
        register_module("geo.countries", countries_dir)

        # countries alone: regions (a declared dependency) is not auto-loaded.
        with Resolver.from_modules(module_ids=["geo.countries"]) as resolver:
            assert resolver.resolve("United States").entity_id == "country/USA"
            assert resolver.resolve("North America").entity_id is None

        # Naming both loads both.
        with Resolver.from_modules(
            module_ids=["geo.countries", "geo.regions"]
        ) as resolver:
            assert resolver.resolve("United States").entity_id == "country/USA"
            assert resolver.resolve("North America").entity_id == "region/NAM"

    def test_unnamed_dependency_does_not_raise_module_not_found(self, tmp_path: Path):
        # A declared dependency that is not installed at all is fine when it was
        # not requested: the dependency is advisory, so the named module loads
        # alone rather than raising DataModuleNotFoundError.
        from resolvekit import Resolver

        admin1_dir = _make_full_datapack(
            tmp_path / "geo_admin1",
            module_id="geo.admin1",
            entity_rows=[("admin1/US-CA", "geo.admin1", "California")],
            module_dependencies=["geo.countries"],
        )
        register_module("geo.admin1", admin1_dir)

        with Resolver.from_modules(module_ids=["geo.admin1"]) as resolver:
            assert resolver.resolve("California").entity_id == "admin1/US-CA"

    def test_requesting_unknown_module_raises_module_not_found(self, tmp_path: Path):
        # Authoritative selection is literal about what it CAN'T provide too:
        # naming a module the registry doesn't know is a hard error (distinct
        # from an unnamed advisory dependency, which is silently honored).
        from resolvekit import Resolver

        admin1_dir = _make_full_datapack(
            tmp_path / "geo_admin1",
            module_id="geo.admin1",
            entity_rows=[("admin1/US-CA", "geo.admin1", "California")],
        )
        register_module("geo.admin1", admin1_dir)

        with pytest.raises(DataModuleNotFoundError) as exc_info:
            Resolver.from_modules(module_ids=["geo.admin1", "geo.bogus"])

        assert exc_info.value.module_id == "geo.bogus"

    def test_same_domain_modules_compose_when_both_named(self, tmp_path: Path):
        from resolvekit import Resolver

        countries_dir = _make_full_datapack(
            tmp_path / "geo_countries",
            module_id="geo.countries",
            entity_rows=[("country/FRA", "geo.country", "France")],
        )
        cities_dir = _make_full_datapack(
            tmp_path / "geo_cities",
            module_id="geo.cities",
            entity_rows=[("city/PAR", "geo.city", "Paris")],
            relation_rows=[("city/PAR", "contained_in", "country/FRA")],
            module_dependencies=["geo.countries"],
        )
        register_module("geo.countries", countries_dir)
        register_module("geo.cities", cities_dir)

        with Resolver.from_modules(
            module_ids=["geo.cities", "geo.countries"]
        ) as resolver:
            assert resolver.resolve("Paris").entity_id == "city/PAR"
            assert resolver.resolve("France").entity_id == "country/FRA"

    def test_overlapping_same_domain_modules_are_rejected(self, tmp_path: Path):
        from resolvekit import Resolver

        left_dir = _make_full_datapack(
            tmp_path / "geo_one",
            module_id="geo.one",
            entity_rows=[("country/USA", "geo.country", "United States")],
        )
        right_dir = _make_full_datapack(
            tmp_path / "geo_two",
            module_id="geo.two",
            entity_rows=[("country/USA", "geo.country", "United States of America")],
        )
        register_module("geo.one", left_dir)
        register_module("geo.two", right_dir)

        with pytest.raises(ModuleConflictError):
            Resolver.from_modules(module_ids=["geo.one", "geo.two"])


class TestResolverAuto:
    def test_auto_filters_registered_modules_by_domain(self, tmp_path: Path):
        from resolvekit import Resolver
        from resolvekit.types import RoutingMode

        geo_dir = _make_full_datapack(
            tmp_path / "geo_countries",
            module_id="geo.countries",
            entity_rows=[("country/USA", "geo.country", "United States")],
        )
        org_dir = _make_full_datapack(
            tmp_path / "org_igos",
            module_id="org.igos",
            domain="org",
            entity_rows=[("org/EU", "org.igo", "European Union")],
        )
        register_module("geo.countries", geo_dir)
        register_module("org.igos", org_dir)

        with Resolver.auto(
            domains=["geo"], routing_mode=RoutingMode.EXPLICIT
        ) as resolver:
            assert resolver.domains == ["geo"]
            assert (
                resolver.resolve("United States", domain="geo").entity_id
                == "country/USA"
            )

    def test_auto_raises_when_requested_domain_is_unavailable(self, tmp_path: Path):
        from resolvekit import Resolver

        geo_dir = _make_full_datapack(
            tmp_path / "geo_countries",
            module_id="geo.countries",
            entity_rows=[("country/USA", "geo.country", "United States")],
        )
        register_module("geo.countries", geo_dir)

        with pytest.raises(UnknownDomainError) as exc_info:
            Resolver.auto(domains=["org"])

        assert exc_info.value.unknown == ["org"]
        assert exc_info.value.available == ["geo"]

    def test_auto_domains_skips_uncached_remote_modules(self, tmp_path: Path):
        """auto(domains=["geo"]) must silently skip geo modules whose data is
        not locally available (mirrors bare auto() behaviour) instead of raising
        DataPackNotAvailableError.

        The "uncached" module is simulated by creating a datapack directory with
        only metadata.json — no entities.sqlite — so that
        _module_data_locally_available returns False for it.
        """
        from resolvekit import Resolver

        # Bundled geo module with sqlite present (locally available).
        available_dir = _make_full_datapack(
            tmp_path / "geo_countries",
            module_id="geo.countries",
            entity_rows=[("country/USA", "geo.country", "United States")],
        )

        # Simulated "uncached" geo module: metadata.json only, no sqlite.
        uncached_dir = tmp_path / "geo_cities"
        uncached_dir.mkdir(parents=True, exist_ok=True)
        (uncached_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "datapack_id": "geo.cities-v1",
                    "module_id": "geo.cities",
                    "domain_pack_id": "geo",
                    "module_dependencies": [],
                    "entity_schema_version": "1.0",
                    "feature_schema_version": "geo.features.v1",
                    "normalizer_version": NORMALIZER_VERSION,
                    "index_versions": {"fts": "fts5"},
                    "build_timestamp": "2024-01-01T00:00:00Z",
                    "source_datasets": ["test"],
                    # bundled but sqlite is intentionally absent, so
                    # _module_data_locally_available returns False
                }
            )
        )

        register_module("geo.countries", available_dir)
        register_module("geo.cities", uncached_dir)

        # Must not raise DataPackNotAvailableError — the uncached module is
        # silently skipped, mirroring bare Resolver.auto() behaviour.
        with Resolver.auto(domains=["geo"]) as resolver:
            assert resolver.domains == ["geo"]


class TestResolverFromDatapacks:
    def test_from_datapacks_accepts_explicit_paths(self, tmp_path: Path):
        from resolvekit import Resolver

        datapack_dir = _make_full_datapack(
            tmp_path / "geo_data",
            module_id="geo.countries",
            entity_rows=[("country/USA", "geo.country", "United States")],
        )

        with Resolver.from_datapacks(datapack_paths=[datapack_dir]) as resolver:
            assert resolver.resolve("United States").entity_id == "country/USA"

    def test_from_datapacks_loads_multiple_explicit_paths(self, tmp_path: Path):
        from resolvekit import Resolver
        from resolvekit.types import RoutingMode

        _make_full_datapack(
            tmp_path / "geo",
            module_id="geo.countries",
            entity_rows=[("country/USA", "geo.country", "United States")],
        )
        _make_full_datapack(
            tmp_path / "org",
            module_id="org.igos",
            domain="org",
            entity_rows=[("org/EU", "org.igo", "European Union")],
        )

        with Resolver.from_datapacks(
            datapack_paths=[tmp_path / "geo", tmp_path / "org"],
            routing_mode=RoutingMode.EXPLICIT,
        ) as resolver:
            assert (
                resolver.resolve("United States", domain="geo").entity_id
                == "country/USA"
            )
            assert (
                resolver.resolve("European Union", domain="org").entity_id == "org/EU"
            )
