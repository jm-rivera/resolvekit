"""Characterization tests for discover_entities*, discover_entities_filtered*,
and discover_entities_filtered_incremental in geo/discovery.py.

Tests pin the current observable behavior to enable safe refactoring.
"""

from __future__ import annotations

from resolvekit.builder.sources.datacommons.geo.discovery import (
    discover_entities,
    discover_entities_filtered,
    discover_entities_filtered_incremental,
)
from resolvekit.builder.sources.datacommons.geo.mappings import UN_REGION_DCID
from resolvekit.builder.sources.discovery_events import (
    BatchComplete,
    DomainComplete,
    DomainStart,
    UnitBatch,
    UnitComplete,
    UnitStart,
)

from ._stubs import (
    EventCapture,
    make_geo_fixture,
    make_geo_fixture_no_callback,
    noop_with_retries,
)

# ---------------------------------------------------------------------------
# Fixture entity ID sets for inline assertions
# ---------------------------------------------------------------------------

_ALL_COUNTRIES = {"country/USA"}
_ALL_REGIONS = {"region/Americas", UN_REGION_DCID}
_ALL_ADMIN1 = {"admin1/CA", "admin1/NY"}
_ALL_ADMIN2 = {"admin2/SF", "admin2/LA", "admin2/NYC"}
_ALL_CITIES = {"city/SanFrancisco", "city/NewYork", "city/DistrictOfColumbia"}
_CUSTOM_CHILD_TYPES = {"borough/Manhattan"}

_FULL_UNIVERSE = (
    _ALL_COUNTRIES
    | _ALL_REGIONS
    | _ALL_ADMIN1
    | _ALL_ADMIN2
    | _ALL_CITIES
    | _CUSTOM_CHILD_TYPES
)


# ---------------------------------------------------------------------------
# discover_entities* integration tests
# ---------------------------------------------------------------------------


def test_discover_entities_returns_full_unfiltered_universe() -> None:
    """discover_entities returns sorted, deduplicated entity IDs covering all
    geo regions + UN_REGION_DCID + countries + full admin hierarchy + cities +
    custom child types (BoroughNYCType).
    """
    dc_api = make_geo_fixture()

    result = discover_entities(
        dc_api=dc_api,
        with_retries=noop_with_retries,
    )

    assert isinstance(result, list)
    assert result == sorted(result), "result must be globally sorted"
    assert len(result) == len(set(result)), "result must be deduplicated"
    assert set(result) == _FULL_UNIVERSE


def test_discover_entities_includes_custom_child_types_under_countries() -> None:
    """discover_entities includes entities of custom DC types (BoroughNYCType)
    that are children of countries but not admin/city/region types.

    Locks the sweep at discover_entities:85-100 that must be preserved inside
    _discover_all_geo_entities.
    """
    dc_api = make_geo_fixture()

    result = discover_entities(
        dc_api=dc_api,
        with_retries=noop_with_retries,
    )

    assert _CUSTOM_CHILD_TYPES.issubset(set(result)), (
        f"Expected custom child entities {_CUSTOM_CHILD_TYPES} in result, got {result}"
    )


def test_discover_entities_filtered_returns_same_as_collected_incremental() -> None:
    """discover_entities_filtered returns the same sorted set as collecting
    emit_entities calls from discover_entities_filtered_incremental.

    Locks the legacy-shim contract: both must return identical entity sets for
    the same include_entity_types filter.
    """
    dc_api_a = make_geo_fixture()
    dc_api_b = make_geo_fixture()

    filtered_result = discover_entities_filtered(
        dc_api=dc_api_a,
        with_retries=noop_with_retries,
        include_entity_types=["geo.admin1"],
        include_relation_targets=False,
    )

    collected: list[str] = []
    discover_entities_filtered_incremental(
        dc_api=dc_api_b,
        with_retries=noop_with_retries,
        include_entity_types=["geo.admin1"],
        include_relation_targets=False,
        emit_entities=lambda _unit, ids, _meta: collected.extend(ids),
        emit_progress=lambda _payload: None,
    )
    incremental_result = sorted(set(collected))

    assert filtered_result == incremental_result


def test_discover_entities_filtered_empty_types_falls_back_to_unfiltered() -> None:
    """discover_entities_filtered with include_entity_types=[] returns the same
    set as discover_entities (the full unfiltered universe).

    Locks the fallback semantics at discovery.py:148-174.
    """
    dc_api_a = make_geo_fixture()
    dc_api_b = make_geo_fixture()

    full = discover_entities(
        dc_api=dc_api_a,
        with_retries=noop_with_retries,
    )
    filtered_empty = discover_entities_filtered(
        dc_api=dc_api_b,
        with_retries=noop_with_retries,
        include_entity_types=[],
        include_relation_targets=False,
    )

    assert set(filtered_empty) == set(full)


def test_discover_entities_filtered_incremental_event_sequence() -> None:
    """Pin the full progress event sequence and field vocabulary for a multi-
    batch admin1 run using StubGeoDcApiWithCallback (parallel-callback path).

    With discovery_parent_batch_size=1 and 2 admin1 entities under country/USA,
    the admin1 step produces 2 parent batches, exercising the ordered-emit path.

    Asserts:
    - domain_start comes first.
    - unit_start + batch_complete* + unit_batch* + unit_complete per unit.
    - batch_complete events arrive before unit_batch events for the same index
      (the parallel-callback ordering guarantee).
    - domain_complete comes last.
    - Every progress payload has the expected field set.
    """
    dc_api = make_geo_fixture()
    cap = EventCapture()

    discover_entities_filtered_incremental(
        dc_api=dc_api,
        with_retries=noop_with_retries,
        include_entity_types=["geo.admin1"],
        include_relation_targets=False,
        emit_entities=cap.emit_entities,
        emit_progress=cap.emit_progress,
        discovery_parent_batch_size=1,
    )

    progress = cap.progress_events()

    # Domain envelope
    assert isinstance(progress[0], DomainStart)
    assert isinstance(progress[-1], DomainComplete)

    # domain_start fields
    domain_start = progress[0]
    assert isinstance(domain_start, DomainStart)
    assert hasattr(domain_start, "requested_entity_types")
    assert hasattr(domain_start, "include_relation_targets")

    # domain_complete fields
    domain_complete = progress[-1]
    assert isinstance(domain_complete, DomainComplete)
    assert hasattr(domain_complete, "requested_entity_types")

    # admin1 unit must be present
    unit_start_events = [p for p in progress if isinstance(p, UnitStart)]
    admin1_start = next((p for p in unit_start_events if p.unit == "admin1"), None)
    assert admin1_start is not None, "Expected unit_start for admin1"
    assert hasattr(admin1_start, "batch_count")
    # With batch_size=1, country/USA (1 item) → 1 batch; batch_count=1

    unit_complete_events = [p for p in progress if isinstance(p, UnitComplete)]
    admin1_complete = next(
        (p for p in unit_complete_events if p.unit == "admin1"), None
    )
    assert admin1_complete is not None, "Expected unit_complete for admin1"
    assert hasattr(admin1_complete, "batch_count")
    assert hasattr(admin1_complete, "completed_batches")
    assert hasattr(admin1_complete, "discovered_entities")

    # batch_complete events must exist for admin1
    batch_complete_events = [
        p for p in progress if isinstance(p, BatchComplete) and p.unit == "admin1"
    ]
    assert len(batch_complete_events) >= 1

    # Each batch_complete must carry batch_index, completed_batches, batch_count
    for bce in batch_complete_events:
        assert hasattr(bce, "batch_index")
        assert hasattr(bce, "completed_batches")
        assert hasattr(bce, "batch_count")

    # unit_batch events (via entity emit) must carry correct field set
    entity_events = cap.entity_events()
    admin1_entity_events = [e for e in entity_events if e[0] == "admin1"]
    assert len(admin1_entity_events) >= 1

    for _unit, _ids, meta in admin1_entity_events:
        assert isinstance(meta, UnitBatch)
        assert hasattr(meta, "batch_index")
        assert hasattr(meta, "batch_count")
        assert hasattr(meta, "discovered_in_batch")
        assert hasattr(meta, "discovered_total")

    # Parallel-callback path: batch_complete for batch_index=N arrives before
    # the corresponding unit_batch event in the combined event stream.
    # Verify by checking the raw event sequence for any admin1 batch.
    all_events_linear = cap.events
    batch_complete_positions = {
        ev[1].batch_index: idx
        for idx, ev in enumerate(all_events_linear)
        if ev[0] == "progress"
        and isinstance(ev[1], BatchComplete)
        and ev[1].unit == "admin1"
    }
    unit_batch_positions = {
        ev[3].batch_index: idx
        for idx, ev in enumerate(all_events_linear)
        if ev[0] == "entities"
        and isinstance(ev[3], UnitBatch)
        and ev[3].unit == "admin1"
    }
    # For each batch index present in both, batch_complete must come before unit_batch
    for batch_idx in set(batch_complete_positions) & set(unit_batch_positions):
        assert batch_complete_positions[batch_idx] < unit_batch_positions[batch_idx], (
            f"batch_complete for batch_index={batch_idx} must precede "
            f"unit_batch for the same index (parallel-callback ordering)"
        )

    # Admin1 entities must be present in emitted ids
    emitted_admin1_ids = {
        entity_id for _unit, ids, _meta in admin1_entity_events for entity_id in ids
    }
    assert emitted_admin1_ids == _ALL_ADMIN1

    # Smoke-check: the sync-fallback path (no on_chunk_complete) produces the
    # same event-type vocabulary and the same entity IDs.
    dc_api_no_cb = make_geo_fixture_no_callback()
    cap_no_cb = EventCapture()
    discover_entities_filtered_incremental(
        dc_api=dc_api_no_cb,
        with_retries=noop_with_retries,
        include_entity_types=["geo.admin1"],
        include_relation_targets=False,
        emit_entities=cap_no_cb.emit_entities,
        emit_progress=cap_no_cb.emit_progress,
        discovery_parent_batch_size=1,
    )
    cb_event_types = {p.event for p in cap.progress_events()}
    no_cb_event_types = {p.event for p in cap_no_cb.progress_events()}
    assert cb_event_types == no_cb_event_types, (
        "sync-fallback path must produce the same event vocabulary"
    )
    no_cb_admin1_ids = {
        eid
        for _u, ids, _m in cap_no_cb.entity_events()
        if _u == "admin1"
        for eid in ids
    }
    assert no_cb_admin1_ids == _ALL_ADMIN1


def test_discover_entities_filtered_incremental_with_seed_frontier_skips_cached_levels_specific_types() -> (
    None
):
    """When seed_frontier={"countries": [...], "admin1": [...]} is supplied,
    the specific-types admin walk skips admin1 and emits unit_start/unit_complete
    with source_unit="cache" and batch_count=0. No entity batch for admin1 is
    emitted (unified with the generic-path semantics). City discovery for
    admin2 still runs.

    Uses PLACE_TYPES_SPECIFIC (AdministrativeArea1/2), which routes through
    _discover_admin_hierarchy_by_specific_types_incremental.
    """
    dc_api = make_geo_fixture()  # specific types
    cap = EventCapture()

    seed = {
        "countries": ["country/USA"],
        "admin1": ["admin1/CA", "admin1/NY"],
    }

    discover_entities_filtered_incremental(
        dc_api=dc_api,
        with_retries=noop_with_retries,
        include_entity_types=["geo.admin1", "geo.admin2"],
        include_relation_targets=False,
        emit_entities=cap.emit_entities,
        emit_progress=cap.emit_progress,
        seed_frontier=seed,
        discovery_parent_batch_size=1,
    )

    progress = cap.progress_events()

    # admin1 must have unit_start with source_unit="cache" and batch_count=0
    admin1_start = next(
        (p for p in progress if isinstance(p, UnitStart) and p.unit == "admin1"),
        None,
    )
    assert admin1_start is not None, "Expected unit_start for admin1"
    assert admin1_start.source_unit == "cache", (
        f"Expected source_unit='cache', got {admin1_start.source_unit!r}"
    )
    assert admin1_start.batch_count == 0, (
        f"Expected batch_count=0, got {admin1_start.batch_count!r}"
    )

    # Both specific-types and generic-types paths treat seeded admin levels as
    # true cache hits — no entity batch for admin1 is emitted from the
    # countries→admin1 walk.
    admin1_entity_events = [ev for ev in cap.entity_events() if ev[0] == "admin1"]
    assert admin1_entity_events == []

    # admin2 discovery still runs — entities should be emitted
    admin2_entity_events = [ev for ev in cap.entity_events() if ev[0] == "admin2"]
    emitted_admin2 = {eid for _u, ids, _m in admin2_entity_events for eid in ids}
    assert emitted_admin2 == _ALL_ADMIN2, (
        f"admin2 entities should still be discovered, got {emitted_admin2}"
    )


def test_discover_entities_filtered_incremental_with_seed_frontier_skips_cached_levels_generic_type() -> (
    None
):
    """Same seed_frontier contract for the generic-type code path.

    Uses PLACE_TYPES_GENERIC (AdministrativeArea), routing through
    _discover_admin_hierarchy_by_generic_type_incremental. Both paths share
    the canonical cache-hit semantics: no entity batch for admin1 when admin1
    is in seed_frontier.
    """
    dc_api = make_geo_fixture(use_generic_types=True)
    cap = EventCapture()

    seed = {
        "countries": ["country/USA"],
        "admin1": ["admin1/CA", "admin1/NY"],
    }

    discover_entities_filtered_incremental(
        dc_api=dc_api,
        with_retries=noop_with_retries,
        include_entity_types=["geo.admin1", "geo.admin2"],
        include_relation_targets=False,
        emit_entities=cap.emit_entities,
        emit_progress=cap.emit_progress,
        seed_frontier=seed,
        discovery_parent_batch_size=1,
    )

    progress = cap.progress_events()

    # admin1 must have unit_start with source_unit="cache" and batch_count=0
    admin1_start = next(
        (p for p in progress if isinstance(p, UnitStart) and p.unit == "admin1"),
        None,
    )
    assert admin1_start is not None, "Expected unit_start for admin1"
    assert admin1_start.source_unit == "cache", (
        f"Expected source_unit='cache', got {admin1_start.source_unit!r}"
    )
    assert admin1_start.batch_count == 0

    # No entity batches for admin1 (cache hit)
    admin1_entity_events = [ev for ev in cap.entity_events() if ev[0] == "admin1"]
    assert admin1_entity_events == []

    # admin2 still discovered from cached admin1 frontier
    admin2_entity_events = [ev for ev in cap.entity_events() if ev[0] == "admin2"]
    emitted_admin2 = {eid for _u, ids, _m in admin2_entity_events for eid in ids}
    assert emitted_admin2 == _ALL_ADMIN2


def test_discover_entities_filtered_incremental_emit_discovered_flag() -> None:
    """When include_entity_types=["geo.admin2"], admin1 is walked to populate
    the frontier but its entities are NOT emitted. Admin2 entities ARE emitted.

    Locks the emit_discovered=False path used at discovery.py:796.
    """
    dc_api = make_geo_fixture()
    cap = EventCapture()

    discover_entities_filtered_incremental(
        dc_api=dc_api,
        with_retries=noop_with_retries,
        include_entity_types=["geo.admin2"],
        include_relation_targets=False,
        emit_entities=cap.emit_entities,
        emit_progress=cap.emit_progress,
        discovery_parent_batch_size=1,
    )

    # admin1 must NOT appear in emitted entity events
    admin1_entity_events = [ev for ev in cap.entity_events() if ev[0] == "admin1"]
    assert admin1_entity_events == [], (
        "admin1 entities must not be emitted when only geo.admin2 is requested"
    )

    # admin2 MUST appear in emitted entity events
    admin2_entity_events = [ev for ev in cap.entity_events() if ev[0] == "admin2"]
    emitted_admin2 = {eid for _u, ids, _m in admin2_entity_events for eid in ids}
    assert emitted_admin2 == _ALL_ADMIN2, (
        f"Expected admin2 entities {_ALL_ADMIN2}, got {emitted_admin2}"
    )

    # admin1 unit_start should still exist (it was walked, just not emitted)
    progress = cap.progress_events()
    admin1_start = next(
        (p for p in progress if isinstance(p, UnitStart) and p.unit == "admin1"),
        None,
    )
    assert admin1_start is not None, (
        "admin1 unit_start should exist even when emit_discovered=False"
    )


def test_discover_entities_filtered_incremental_admin_specific_vs_generic_parity() -> (
    None
):
    """The specific-types path (AdministrativeArea1/2) and the generic-type path
    (AdministrativeArea) produce identical emitted entity ID sets for the same
    recipe.

    Locks the parity invariant between _discover_admin_hierarchy_by_specific_types
    and _discover_admin_hierarchy_by_generic_type: currently held by code
    structure alone, no prior test.
    """
    dc_api_specific = make_geo_fixture(use_generic_types=False)
    dc_api_generic = make_geo_fixture(use_generic_types=True)

    types = ["geo.admin1", "geo.admin2", "geo.city"]

    collected_specific: list[str] = []
    collected_generic: list[str] = []

    discover_entities_filtered_incremental(
        dc_api=dc_api_specific,
        with_retries=noop_with_retries,
        include_entity_types=types,
        include_relation_targets=False,
        emit_entities=lambda _u, ids, _m: collected_specific.extend(ids),
        emit_progress=lambda _p: None,
        discovery_parent_batch_size=1,
    )
    discover_entities_filtered_incremental(
        dc_api=dc_api_generic,
        with_retries=noop_with_retries,
        include_entity_types=types,
        include_relation_targets=False,
        emit_entities=lambda _u, ids, _m: collected_generic.extend(ids),
        emit_progress=lambda _p: None,
        discovery_parent_batch_size=1,
    )

    specific_set = set(collected_specific)
    generic_set = set(collected_generic)

    assert specific_set == generic_set, (
        f"Specific-types path and generic-type path must emit identical entity "
        f"sets.\n  Specific only: {specific_set - generic_set}\n"
        f"  Generic only: {generic_set - specific_set}"
    )
    # Both must contain admin1, admin2, and city entities
    assert _ALL_ADMIN1.issubset(specific_set)
    assert _ALL_ADMIN2.issubset(specific_set)
    assert _ALL_CITIES.issubset(specific_set)
