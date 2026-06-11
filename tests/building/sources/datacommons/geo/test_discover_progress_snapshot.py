"""Verify the typed accumulator's JSON dump matches today's dict-shape verbatim."""

from __future__ import annotations

from resolvekit.builder.pipeline.discover import _merge_discover_progress_event
from resolvekit.builder.sources.discovery_events import (
    DiscoverProgress,
    DomainProgress,
    DomainStart,
    UnitComplete,
    UnitStart,
)


def test_typed_accumulator_matches_legacy_dict_shape() -> None:
    # Build up the accumulator via the typed path:
    progress = DiscoverProgress()
    domain_progress = progress.domains.setdefault("geo", DomainProgress())
    _merge_discover_progress_event(
        domain_progress,
        DomainStart(
            unit="geo",
            requested_entity_types=["geo.admin1"],
            include_relation_targets=False,
        ),
    )
    _merge_discover_progress_event(
        domain_progress,
        UnitStart(
            unit="admin1",
            raw_type="AdministrativeArea1",
            level=1,
            source_unit="countries",
            batch_count=1,
        ),
    )
    _merge_discover_progress_event(
        domain_progress,
        UnitComplete(
            unit="admin1",
            raw_type="AdministrativeArea1",
            level=1,
            source_unit="countries",
            batch_count=1,
            completed_batches=1,
            discovered_entities=2,
        ),
    )
    # Dump with exclude_none=True:
    dumped = progress.model_dump(mode="json", exclude_none=True)
    # Snapshot the expected dict-shape (matches today's accumulator output):
    expected = {
        "domains": {
            "geo": {
                "mode": "pending",
                "status": "running",
                "requested_entity_types": ["geo.admin1"],
                "include_relation_targets": False,
                "discovered_entities": 0,
                "chunk_count": 0,
                "last_event": "unit_complete",
                "current_unit": "admin1",
                "units": {
                    "admin1": {
                        "status": "complete",
                        "raw_type": "AdministrativeArea1",
                        "level": 1,
                        "source_unit": "countries",
                        "batch_count": 1,
                        "completed_batches": 1,
                        "discovered_entities": 2,
                    },
                },
            },
        },
    }
    assert dumped == expected, (
        f"Typed accumulator JSON dump diverged from expected dict shape.\n"
        f"Got:      {dumped}\n"
        f"Expected: {expected}"
    )
