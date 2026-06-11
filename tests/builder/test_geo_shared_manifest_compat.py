"""Backward-compatibility tests for GeoManifest / CoverageUnit pydantic models.

Verifies that v1 manifest.json files on user disks round-trip cleanly, and
that extra keys from future schema versions are silently ignored.
"""

from __future__ import annotations

from resolvekit.builder.geo_shared import GeoManifest


def test_v1_manifest_roundtrips_cleanly() -> None:
    v1_dict = {
        "schema_version": 1,
        "source_instance": "datacommons.one.org",
        "last_refresh": "2026-01-01T00:00:00+00:00",
        "coverage": {
            "countries": {
                "name": "countries",
                "state": "ready",
                "run_id": "abc",
                "refreshed_at": "2026-01-01T00:00:00+00:00",
                "entity_count": 195,
            },
        },
    }
    manifest = GeoManifest.model_validate(v1_dict)
    assert manifest.coverage["countries"].state == "ready"
    assert manifest.coverage["countries"].entity_count == 195
    dumped = manifest.model_dump(mode="json")
    assert dumped["schema_version"] == 1
    assert dumped["source_instance"] == "datacommons.one.org"
    assert dumped["coverage"]["countries"] == v1_dict["coverage"]["countries"]


def test_extra_keys_ignored_for_forward_compat() -> None:
    future = {
        "schema_version": 2,
        "future_field": "ignore_me",
        "coverage": {"foo": {"name": "foo", "future_unit_field": True}},
    }
    manifest = GeoManifest.model_validate(future)
    assert "future_field" not in manifest.model_dump(mode="json")
    assert manifest.coverage["foo"].name == "foo"
