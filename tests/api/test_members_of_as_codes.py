"""Tests for members_of as_codes multi-store aggregation and validation."""

from __future__ import annotations

from datetime import date

import pytest

from resolvekit.core.api.resolver import Resolver
from resolvekit.core.errors import UnknownCodeSystemError
from resolvekit.core.model.entity import CodeRecord, EntityRecord
from resolvekit.core.model.result import (
    ReasonCode,
    ResolutionResult,
    ResolutionStatus,
)

# ---------------------------------------------------------------------------
# Stub infrastructure
# ---------------------------------------------------------------------------


def _make_entity(
    entity_id: str,
    entity_type: str,
    canonical_name: str,
    codes: list[tuple[str, str]],
) -> EntityRecord:
    return EntityRecord(
        entity_id=entity_id,
        entity_type=entity_type,
        canonical_name=canonical_name,
        canonical_name_norm=canonical_name.casefold(),
        codes=[
            CodeRecord(system=system, value=value, value_norm=value.casefold())
            for system, value in codes
        ],
    )


class _StubStore:
    """Minimal store stub with member-related methods."""

    def __init__(
        self,
        entities: dict[str, EntityRecord],
        reverse_relations: dict[str, list[str]] | None = None,
    ) -> None:
        self._entities = entities
        # Maps group_entity_id -> list[member_entity_id]
        self._reverse_relations = reverse_relations or {}

    def get_entity(self, entity_id: str) -> EntityRecord | None:
        return self._entities.get(entity_id)

    def bulk_get_entities(self, entity_ids: list[str]) -> dict[str, EntityRecord]:
        return {eid: self._entities[eid] for eid in entity_ids if eid in self._entities}

    def get_reverse_relations(
        self, group_id: str, relation_type: str, *, as_of: date
    ) -> list[str]:
        return self._reverse_relations.get(group_id, [])

    def code_systems(self) -> list[str]:
        systems: set[str] = set()
        for entity in self._entities.values():
            for code in entity.codes:
                systems.add(code.system)
        return sorted(systems)

    def close(self) -> None:
        pass


class _StubBackend:
    """Two-store backend for multi-store tests.

    Implements the ResolverBackend surface so the Resolver facade can call
    backend methods instead of getattr reach-ins.
    """

    def __init__(
        self,
        stores: dict[str, _StubStore],
        resolve_result: ResolutionResult | None = None,
    ) -> None:
        self._stores = stores
        self._resolve_result = resolve_result
        self.available_packs: frozenset[str] = frozenset(stores)

    # ------------------------------------------------------------------
    # Core ResolverBackend methods
    # ------------------------------------------------------------------

    def close(self) -> None:
        pass

    def get_entity(self, entity_id: str) -> EntityRecord | None:
        for store in self._stores.values():
            entity = store.get_entity(entity_id)
            if entity is not None:
                return entity
        return None

    def lookup_code(
        self,
        system: str,
        value_norm: str,
        *,
        pack_filter: frozenset[str] | None = None,
    ) -> list[str]:
        return []

    def resolve(
        self, _query: object, _context: object, **_kwargs: object
    ) -> ResolutionResult:
        if self._resolve_result is not None:
            return self._resolve_result
        raise NotImplementedError

    def resolve_detailed(  # type: ignore[override]
        self, _query: object, _context: object, **_kwargs: object
    ) -> object:
        raise NotImplementedError("resolve_detailed not used in these tests")

    # ------------------------------------------------------------------
    # Introspection methods
    # ------------------------------------------------------------------

    @property
    def available_entity_types(self) -> frozenset[str]:
        return frozenset()

    @property
    def available_code_systems(self) -> frozenset[str]:
        systems: set[str] = set()
        for store in self._stores.values():
            systems.update(store.code_systems())
        return frozenset(systems)

    @property
    def available_group_types(self) -> frozenset[str]:
        return frozenset()

    def get_pack_group_types(self, *, pack_id: str) -> frozenset[str]:
        return frozenset()

    def get_reverse_relations(
        self,
        *,
        entity_id: str,
        relation_type: str,
        as_of: date | None = None,
    ) -> list[str]:
        seen: set[str] = set()
        for store in self._stores.values():
            for eid in store.get_reverse_relations(
                entity_id, relation_type, as_of=as_of or date.today()
            ):
                seen.add(eid)
        return sorted(seen)

    def get_relations_as_of(
        self,
        *,
        entity_id: str,
        relation_type: str,
        as_of: date,
    ) -> frozenset[str]:
        result: set[str] = set()
        for store in self._stores.values():
            result.update(
                store.get_reverse_relations(entity_id, relation_type, as_of=as_of)
            )
        return frozenset(result)

    def list_entities_by_type(self, *, entity_type: str) -> list[EntityRecord]:
        return []

    def is_snapshot_entity(self, *, entity_id: str) -> bool:
        return False

    def lookup_pack_id(self) -> str | None:
        return None

    def lookup_name_exact(
        self,
        *,
        value: str,
        pack_filter: frozenset[str] | None = None,
    ) -> list[tuple[str, str]]:
        return []


# ---------------------------------------------------------------------------
# Fixtures / helper data
# ---------------------------------------------------------------------------

# G7 entity in geo store
G7_ENTITY = _make_entity("groups/G7", "geo.organization", "G7", [])

# Members split across two stores:
# store "geo" has USA and DEU
USA = _make_entity(
    "country/USA", "geo.country", "United States", [("iso3", "USA"), ("iso2", "US")]
)
DEU = _make_entity(
    "country/DEU", "geo.country", "Germany", [("iso3", "DEU"), ("iso2", "DE")]
)
# store "extra" has FRA (simulates a second pack's entity)
FRA = _make_entity(
    "country/FRA", "geo.country", "France", [("iso3", "FRA"), ("iso2", "FR")]
)


def _resolved_g7() -> ResolutionResult:
    return ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        entity_id="groups/G7",
        confidence=0.99,
        reasons=[ReasonCode.EXACT_CODE_MATCH],
    )


def _multi_store_resolver() -> Resolver:
    """Resolver with G7 members split across two stores."""
    store_geo = _StubStore(
        entities={"groups/G7": G7_ENTITY, "country/USA": USA, "country/DEU": DEU},
        reverse_relations={"groups/G7": ["country/USA", "country/DEU"]},
    )
    store_extra = _StubStore(
        entities={"country/FRA": FRA},
        reverse_relations={"groups/G7": ["country/FRA"]},
    )
    backend = _StubBackend(
        stores={"geo": store_geo, "extra": store_extra},
        resolve_result=_resolved_g7(),
    )
    return Resolver(runner=backend)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_members_of_as_codes_aggregates_across_stores() -> None:
    """as_codes union includes members from all stores, not just the first."""
    resolver = _multi_store_resolver()
    iso3_codes = resolver.members_of("G7", as_codes="iso3")
    # All three iso3 codes must be present — the union must include members from every store, not just the first
    assert sorted(iso3_codes) == ["DEU", "FRA", "USA"]


def test_members_of_as_codes_iso3_unchanged_post_f19() -> None:
    """The existing iso3 path still works correctly."""
    resolver = _multi_store_resolver()
    result = resolver.members_of("G7", as_codes="iso3")
    assert "USA" in result
    assert "DEU" in result
    assert "FRA" in result


def test_members_of_as_codes_unknown_system_raises() -> None:
    """Passing an unrecognized code system raises UnknownCodeSystemError."""
    resolver = _multi_store_resolver()
    with pytest.raises(UnknownCodeSystemError) as exc_info:
        resolver.members_of("G7", as_codes="wikidata")
    assert exc_info.value.system == "wikidata"
    assert "iso3" in exc_info.value.available or "iso2" in exc_info.value.available


def test_members_of_none_as_codes_returns_entity_ids() -> None:
    """Default (as_codes=None) returns sorted entity_ids unchanged."""
    resolver = _multi_store_resolver()
    members = resolver.members_of("G7")
    assert sorted(members) == ["country/DEU", "country/FRA", "country/USA"]


def test_members_of_as_codes_iso2() -> None:
    """iso2 code path works end-to-end across multiple stores."""
    resolver = _multi_store_resolver()
    iso2_codes = resolver.members_of("G7", as_codes="iso2")
    assert sorted(iso2_codes) == ["DE", "FR", "US"]
