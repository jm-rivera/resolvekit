"""Tests for the shared geo staging store."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from resolvekit.builder.geo_shared import (
    COVERAGE_UNITS,
    SCHEMA_VERSION,
    UNIT_STATE_INVALID,
    UNIT_STATE_READY,
    UNIT_STATE_REFRESHING,
    CoverageUnit,
    GeoSharedStore,
)
from resolvekit.builder.sqlite.write import (
    ensure_sqlite_schema,
    insert_normalized_payload,
)
from resolvekit.builder.utils import json_read


@pytest.fixture()
def shared_root(tmp_path: Path) -> Path:
    root = tmp_path / "shared" / "geo"
    return root


@pytest.fixture()
def store(shared_root: Path) -> GeoSharedStore:
    s = GeoSharedStore(shared_root)
    s.ensure_paths()
    return s


# ------------------------------------------------------------------
# Initialization
# ------------------------------------------------------------------


class TestInitialization:
    def test_ensure_paths_creates_directory_and_files(self, store: GeoSharedStore):
        assert store.root.exists()
        assert store.db_path.exists()
        assert store.manifest_path.exists()

    def test_default_manifest_structure(self, store: GeoSharedStore):
        manifest = json_read(store.manifest_path)
        assert manifest["schema_version"] == SCHEMA_VERSION
        assert manifest["source_instance"] is None
        assert set(manifest["coverage"].keys()) == set(COVERAGE_UNITS)
        for unit_data in manifest["coverage"].values():
            assert unit_data["state"] == UNIT_STATE_INVALID

    def test_ensure_paths_is_idempotent(self, store: GeoSharedStore):
        store.ensure_paths()
        store.ensure_paths()
        manifest = json_read(store.manifest_path)
        assert manifest["schema_version"] == SCHEMA_VERSION


# ------------------------------------------------------------------
# Coverage queries
# ------------------------------------------------------------------


class TestCoverageQueries:
    def test_all_units_initially_invalid(self, store: GeoSharedStore):
        units = store.coverage_units()
        assert len(units) == len(COVERAGE_UNITS)
        for unit in units.values():
            assert unit.state == UNIT_STATE_INVALID

    def test_ready_units_initially_empty(self, store: GeoSharedStore):
        assert store.ready_units() == set()

    def test_missing_units_returns_all_when_none_ready(self, store: GeoSharedStore):
        required = {"countries", "admin1", "admin2"}
        assert store.missing_units(required) == required

    def test_missing_units_excludes_ready(self, store: GeoSharedStore):
        store.mark_ready("countries", "run-1", entity_count=200)
        required = {"countries", "admin1"}
        assert store.missing_units(required) == {"admin1"}


# ------------------------------------------------------------------
# Coverage-unit type mapping
# ------------------------------------------------------------------


class TestTypeMapping:
    def test_entity_types_to_units(self):
        types = {"geo.country", "geo.admin1", "geo.city"}
        units = GeoSharedStore.entity_types_to_units(types)
        assert units == {"countries", "admin1", "cities"}

    def test_units_to_entity_types(self):
        units = {"countries", "admin1", "cities"}
        types = GeoSharedStore.units_to_entity_types(units)
        assert types == {"geo.country", "geo.admin1", "geo.city"}

    def test_unknown_entity_type_ignored(self):
        assert GeoSharedStore.entity_types_to_units({"geo.unknown"}) == set()

    def test_round_trip(self):
        units = {"countries", "regions", "admin3"}
        types = GeoSharedStore.units_to_entity_types(units)
        back = GeoSharedStore.entity_types_to_units(types)
        assert back == units


# ------------------------------------------------------------------
# Refresh lifecycle
# ------------------------------------------------------------------


class TestRefreshLifecycle:
    def test_mark_refreshing(self, store: GeoSharedStore):
        store.mark_refreshing("admin1", "run-1")
        assert store.unit_state("admin1") == UNIT_STATE_REFRESHING
        units = store.coverage_units()
        assert units["admin1"].run_id == "run-1"

    def test_mark_ready(self, store: GeoSharedStore):
        store.mark_refreshing("admin1", "run-1")
        store.mark_ready("admin1", "run-1", entity_count=5000)
        assert store.unit_state("admin1") == UNIT_STATE_READY
        units = store.coverage_units()
        assert units["admin1"].entity_count == 5000
        assert units["admin1"].refreshed_at is not None

    def test_mark_invalid(self, store: GeoSharedStore):
        store.mark_ready("countries", "run-1", entity_count=200)
        store.mark_invalid("countries")
        assert store.unit_state("countries") == UNIT_STATE_INVALID

    def test_can_claim_refresh_when_invalid(self, store: GeoSharedStore):
        assert store.can_claim_refresh("admin1", "run-1") is True

    def test_cannot_claim_refresh_when_ready(self, store: GeoSharedStore):
        store.mark_ready("admin1", "run-1")
        assert store.can_claim_refresh("admin1", "run-2") is False

    def test_can_claim_stale_refreshing(self, store: GeoSharedStore):
        store.mark_refreshing("admin1", "run-1")
        # Different run can claim stale ownership
        assert store.can_claim_refresh("admin1", "run-2") is True

    def test_can_claim_own_refreshing(self, store: GeoSharedStore):
        store.mark_refreshing("admin1", "run-1")
        assert store.can_claim_refresh("admin1", "run-1") is True


# ------------------------------------------------------------------
# Source instance tracking
# ------------------------------------------------------------------


class TestSourceInstance:
    def test_set_source_instance(self, store: GeoSharedStore):
        store.set_source_instance("datacommons.example.org")
        manifest = json_read(store.manifest_path)
        assert manifest["source_instance"] == "datacommons.example.org"

    def test_change_source_instance_invalidates_coverage(self, store: GeoSharedStore):
        store.set_source_instance("instance-a")
        store.mark_ready("countries", "run-1", entity_count=200)
        assert store.unit_state("countries") == UNIT_STATE_READY

        # Switching instance invalidates all coverage.
        store.set_source_instance("instance-b")
        assert store.unit_state("countries") == UNIT_STATE_INVALID

    def test_same_source_instance_preserves_coverage(self, store: GeoSharedStore):
        store.set_source_instance("instance-a")
        store.mark_ready("countries", "run-1", entity_count=200)
        store.set_source_instance("instance-a")
        assert store.unit_state("countries") == UNIT_STATE_READY


# ------------------------------------------------------------------
# Interruption-safe merge
# ------------------------------------------------------------------


def _make_payload(entity_id: str, entity_type: str) -> dict[str, list[dict[str, Any]]]:
    return {
        "entities": [
            {
                "entity_id": entity_id,
                "entity_type": entity_type,
                "canonical_name": entity_id,
                "canonical_name_norm": entity_id.lower(),
            }
        ],
        "names": [
            {
                "entity_id": entity_id,
                "name_kind": "canonical",
                "value": entity_id,
                "value_norm": entity_id.lower(),
                "lang": "",
                "script": "",
                "is_preferred": 1,
            }
        ],
        "codes": [],
        "relations": [],
    }


class TestMergeTempDb:
    def test_merge_copies_matching_entity_type(
        self, store: GeoSharedStore, tmp_path: Path
    ):
        temp_db = tmp_path / "temp.sqlite"
        ensure_sqlite_schema(temp_db)
        insert_normalized_payload(temp_db, _make_payload("country/USA", "geo.country"))
        insert_normalized_payload(temp_db, _make_payload("admin1/CA", "geo.admin1"))

        count = store.merge_temp_db(temp_db, "countries")
        assert count == 1
        assert store.entity_count_for_unit("countries") == 1
        # admin1 should not have been merged.
        assert store.entity_count_for_unit("admin1") == 0

    def test_merge_replaces_existing_data(self, store: GeoSharedStore, tmp_path: Path):
        # First merge
        temp1 = tmp_path / "temp1.sqlite"
        ensure_sqlite_schema(temp1)
        insert_normalized_payload(temp1, _make_payload("country/USA", "geo.country"))
        store.merge_temp_db(temp1, "countries")
        assert store.entity_count_for_unit("countries") == 1

        # Second merge replaces
        temp2 = tmp_path / "temp2.sqlite"
        ensure_sqlite_schema(temp2)
        insert_normalized_payload(temp2, _make_payload("country/USA", "geo.country"))
        insert_normalized_payload(temp2, _make_payload("country/GBR", "geo.country"))
        count = store.merge_temp_db(temp2, "countries")
        assert count == 2
        assert store.entity_count_for_unit("countries") == 2

    def test_merge_replacement_removes_orphaned_auxiliary_rows(
        self, store: GeoSharedStore, tmp_path: Path
    ):
        temp1 = tmp_path / "temp1.sqlite"
        ensure_sqlite_schema(temp1)
        insert_normalized_payload(
            temp1,
            {
                "entities": [
                    {
                        "entity_id": "country/USA",
                        "entity_type": "geo.country",
                        "canonical_name": "United States",
                        "canonical_name_norm": "united states",
                    },
                    {
                        "entity_id": "country/CAN",
                        "entity_type": "geo.country",
                        "canonical_name": "Canada",
                        "canonical_name_norm": "canada",
                    },
                ],
                "names": [
                    {
                        "entity_id": "country/USA",
                        "name_kind": "canonical",
                        "value": "United States",
                        "value_norm": "united states",
                        "lang": "",
                        "script": "",
                        "is_preferred": 1,
                    },
                    {
                        "entity_id": "country/CAN",
                        "name_kind": "canonical",
                        "value": "Canada",
                        "value_norm": "canada",
                        "lang": "",
                        "script": "",
                        "is_preferred": 1,
                    },
                ],
                "codes": [
                    {
                        "entity_id": "country/USA",
                        "system": "iso2",
                        "value": "US",
                        "value_norm": "us",
                    }
                ],
                "relations": [
                    {
                        "entity_id": "country/USA",
                        "relation_type": "contained_in",
                        "target_id": "region/NAM",
                    }
                ],
            },
        )
        store.merge_temp_db(temp1, "countries")

        temp2 = tmp_path / "temp2.sqlite"
        ensure_sqlite_schema(temp2)
        insert_normalized_payload(
            temp2,
            {
                "entities": [
                    {
                        "entity_id": "country/CAN",
                        "entity_type": "geo.country",
                        "canonical_name": "Canada",
                        "canonical_name_norm": "canada",
                    }
                ],
                "names": [
                    {
                        "entity_id": "country/CAN",
                        "name_kind": "canonical",
                        "value": "Canada",
                        "value_norm": "canada",
                        "lang": "",
                        "script": "",
                        "is_preferred": 1,
                    }
                ],
                "codes": [],
                "relations": [],
            },
        )
        store.merge_temp_db(temp2, "countries")

        with sqlite3.connect(store.db_path) as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM entities WHERE entity_id = 'country/USA'"
                ).fetchone()[0]
                == 0
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM names WHERE entity_id = 'country/USA'"
                ).fetchone()[0]
                == 0
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM codes WHERE entity_id = 'country/USA'"
                ).fetchone()[0]
                == 0
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM relations WHERE entity_id = 'country/USA'"
                ).fetchone()[0]
                == 0
            )

    def test_merge_removes_cross_unit_dangling_relations(
        self, store: GeoSharedStore, tmp_path: Path
    ):
        # Merge admin1 with a relation targeting country/USA.
        admin_db = tmp_path / "admin.sqlite"
        ensure_sqlite_schema(admin_db)
        insert_normalized_payload(
            admin_db,
            {
                "entities": [
                    {
                        "entity_id": "admin1/US-CA",
                        "entity_type": "geo.admin1",
                        "canonical_name": "California",
                        "canonical_name_norm": "california",
                    }
                ],
                "names": [
                    {
                        "entity_id": "admin1/US-CA",
                        "name_kind": "canonical",
                        "value": "California",
                        "value_norm": "california",
                        "lang": "",
                        "script": "",
                        "is_preferred": 1,
                    }
                ],
                "codes": [],
                "relations": [
                    {
                        "entity_id": "admin1/US-CA",
                        "relation_type": "contained_in",
                        "target_id": "country/USA",
                    }
                ],
            },
        )
        # Merge country/USA so the target exists.
        country_db = tmp_path / "country.sqlite"
        ensure_sqlite_schema(country_db)
        insert_normalized_payload(
            country_db, _make_payload("country/USA", "geo.country")
        )
        store.merge_temp_db(country_db, "countries")
        store.merge_temp_db(admin_db, "admin1")

        # Verify the relation exists.
        with sqlite3.connect(store.db_path) as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM relations WHERE target_id = 'country/USA'"
                ).fetchone()[0]
                == 1
            )

        # Refresh countries WITHOUT country/USA — the target is dropped.
        country_db2 = tmp_path / "country2.sqlite"
        ensure_sqlite_schema(country_db2)
        insert_normalized_payload(
            country_db2, _make_payload("country/GBR", "geo.country")
        )
        store.merge_temp_db(country_db2, "countries")

        # The dangling relation in admin1 should have been cleaned up.
        with sqlite3.connect(store.db_path) as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM relations WHERE target_id = 'country/USA'"
                ).fetchone()[0]
                == 0
            )

    def test_merge_unknown_unit_returns_zero(
        self, store: GeoSharedStore, tmp_path: Path
    ):
        temp = tmp_path / "temp.sqlite"
        ensure_sqlite_schema(temp)
        assert store.merge_temp_db(temp, "unknown_unit") == 0


class TestTempStagingDb:
    def test_temp_db_created_and_cleaned_up(self, store: GeoSharedStore):
        with store.temp_staging_db() as temp_path:
            # Caller is responsible for populating the temp file.
            temp_path.touch()
            assert temp_path.exists()
            temp_name = temp_path.name
        # After context exit, temp files should be cleaned up.
        assert not (store.root / temp_name).exists()


# ------------------------------------------------------------------
# CoverageUnit model
# ------------------------------------------------------------------


class TestCoverageUnitModel:
    def test_round_trip(self):
        unit = CoverageUnit(
            name="admin1",
            state=UNIT_STATE_READY,
            run_id="run-1",
            refreshed_at="2026-01-01T00:00:00Z",
            entity_count=1234,
        )
        data = unit.model_dump(mode="json")
        restored = CoverageUnit.model_validate(data)
        assert restored.name == unit.name
        assert restored.state == unit.state
        assert restored.run_id == unit.run_id
        assert restored.refreshed_at == unit.refreshed_at
        assert restored.entity_count == unit.entity_count
