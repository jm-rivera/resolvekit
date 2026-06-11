"""Unit tests for _apply_group_preference_tiebreak and _resolve_group_id adapter.

Tests use a stub ResolverBackend whose _packs dict carries real GeoPack() and
OrgPack() instances (for pack metadata lookups) and a tiny custom-pack stub
(for the cross-pack and known_groups tests). All ResolutionResult objects are
constructed synthetically — no datapack files are required.
"""

import pytest

from resolvekit.core.api.resolver import Resolver
from resolvekit.core.errors import (
    AmbiguousResolutionError,
    GroupNotFoundError,
    ResolutionError,
)
from resolvekit.core.model.entity import EntityRecord
from resolvekit.core.model.result import (
    CandidateSummary,
    ReasonCode,
    ResolutionResult,
    ResolutionStatus,
)
from resolvekit.packs.geo.pack import GeoPack
from resolvekit.packs.org.pack import OrgPack

# ---------------------------------------------------------------------------
# Stub infrastructure
# ---------------------------------------------------------------------------


def _make_entity(entity_id: str, entity_type: str, canonical_name: str) -> EntityRecord:
    return EntityRecord(
        entity_id=entity_id,
        entity_type=entity_type,
        canonical_name=canonical_name,
        canonical_name_norm=canonical_name.casefold(),
    )


class _StubStore:
    """Minimal store stub that supports list_entities_by_type."""

    def __init__(self, entities_by_type: dict[str, list[EntityRecord]]) -> None:
        self._by_type = entities_by_type

    def list_entities_by_type(self, entity_type: str) -> list[EntityRecord]:
        return self._by_type.get(entity_type, [])


class _CustomPack:
    """Stub pack declaring a custom group type for extension tests."""

    pack_id = "custom"
    GROUP_ENTITY_TYPES: frozenset[str] = frozenset({"geo.alliance"})

    @property
    def group_entity_types(self) -> frozenset[str]:
        return self.GROUP_ENTITY_TYPES


class _StubBackend:
    """Minimal ResolverBackend stub for unit tests.

    Packs expose GeoPack / OrgPack / _CustomPack instances so that
    _apply_group_preference_tiebreak can look up pack metadata via the
    new ResolverBackend methods (get_pack_group_types, available_group_types, etc.).

    _resolve_result, when set, is returned by resolve() — used only for
    _resolve_group_id adapter tests.

    _stores, when set, is used by known_groups() tests.
    """

    def __init__(
        self,
        packs: dict[str, object] | None = None,
        resolve_result: ResolutionResult | None = None,
        stores: dict[str, _StubStore] | None = None,
    ) -> None:
        self._packs = packs or {"geo": GeoPack(), "org": OrgPack()}
        self._resolve_result = resolve_result
        self._stores = stores or {}
        self.available_packs: frozenset[str] = frozenset(self._packs)

    # ------------------------------------------------------------------
    # Core ResolverBackend methods
    # ------------------------------------------------------------------

    def resolve(
        self, _query: object, _context: object, **_kwargs: object
    ) -> ResolutionResult:  # type: ignore[override]
        if self._resolve_result is not None:
            return self._resolve_result
        raise NotImplementedError("_StubBackend.resolve not configured for this test")

    def resolve_detailed(  # type: ignore[override]
        self, _query: object, _context: object, **_kwargs: object
    ) -> object:
        raise NotImplementedError(
            "_StubBackend.resolve_detailed not used in these tests"
        )

    def close(self) -> None:
        pass

    def get_entity(self, _entity_id: str) -> EntityRecord | None:
        return None

    def lookup_code(
        self,
        _system: str,
        _value_norm: str,
        *,
        pack_filter: "frozenset[str] | None" = None,
    ) -> list[str]:
        return []

    # ------------------------------------------------------------------
    # Introspection methods (new ResolverBackend surface from S2a/S2c)
    # ------------------------------------------------------------------

    @property
    def available_entity_types(self) -> frozenset[str]:
        types: set[str] = set()
        for pack in self._packs.values():
            hints = getattr(pack, "routing_hints", None)
            if hints is not None:
                types.update(getattr(hints, "type_prefixes", frozenset()))
        return frozenset(types)

    @property
    def available_code_systems(self) -> frozenset[str]:
        return frozenset()

    @property
    def available_group_types(self) -> frozenset[str]:
        types: set[str] = set()
        for pack in self._packs.values():
            types.update(getattr(pack, "group_entity_types", frozenset()))
        return frozenset(types)

    def get_pack_group_types(self, *, pack_id: str) -> frozenset[str]:
        pack = self._packs.get(pack_id)
        return getattr(pack, "group_entity_types", frozenset()) if pack else frozenset()

    def get_reverse_relations(
        self,
        *,
        entity_id: str,
        relation_type: str,
        as_of: "object | None" = None,
    ) -> list[str]:
        return []

    def get_relations_as_of(
        self,
        *,
        entity_id: str,
        relation_type: str,
        as_of: object,
    ) -> frozenset[str]:
        return frozenset()

    def list_entities_by_type(self, *, entity_type: str) -> list[EntityRecord]:
        result: list[EntityRecord] = []
        for store in self._stores.values():
            result.extend(store.list_entities_by_type(entity_type))
        return result

    def is_snapshot_entity(self, *, entity_id: str) -> bool:
        return False

    def lookup_pack_id(self) -> "str | None":
        return None

    def lookup_name_exact(
        self,
        *,
        value: str,
        pack_filter: "frozenset[str] | None" = None,
    ) -> "list[tuple[str, str]]":
        return []


# ---------------------------------------------------------------------------
# Helpers to build synthetic ResolutionResult objects
# ---------------------------------------------------------------------------


def _ambiguous(candidates: list[CandidateSummary]) -> ResolutionResult:
    return ResolutionResult(
        status=ResolutionStatus.AMBIGUOUS,
        reasons=[ReasonCode.AMBIGUOUS_LOW_GAP],
        candidates=candidates,
    )


def _resolved(entity_id: str = "groups/G7") -> ResolutionResult:
    return ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        entity_id=entity_id,
        confidence=0.95,
        reasons=[ReasonCode.ACRONYM_MATCH],
    )


def _no_match() -> ResolutionResult:
    return ResolutionResult(
        status=ResolutionStatus.NO_MATCH,
        reasons=[ReasonCode.NO_CANDIDATES],
    )


def _error() -> ResolutionResult:
    return ResolutionResult(
        status=ResolutionStatus.ERROR,
        reasons=[ReasonCode.STORE_ERROR],
    )


def _group_cand(
    entity_id: str = "groups/G7",
    *,
    confidence: float = 0.92,
    entity_type: str = "geo.organization",
    pack_id: str = "geo",
) -> CandidateSummary:
    return CandidateSummary(
        entity_id=entity_id,
        confidence=confidence,
        entity_type=entity_type,
        pack_id=pack_id,
    )


def _non_group_cand(
    entity_id: str = "region/SomeRegion",
    *,
    confidence: float = 0.91,
    entity_type: str = "geo.region",
    pack_id: str = "geo",
) -> CandidateSummary:
    return CandidateSummary(
        entity_id=entity_id,
        confidence=confidence,
        entity_type=entity_type,
        pack_id=pack_id,
    )


def _make_resolver(
    packs: dict[str, object] | None = None,
    resolve_result: ResolutionResult | None = None,
    stores: dict[str, _StubStore] | None = None,
) -> Resolver:
    backend = _StubBackend(packs=packs, resolve_result=resolve_result, stores=stores)
    return Resolver(runner=backend)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _apply_group_preference_tiebreak — rule-fires tests
# ---------------------------------------------------------------------------


def test_rule_fires_when_unique_group_in_top_two() -> None:
    """AMBIGUOUS with group at rank 1, non-group at rank 2 → RESOLVED to group."""
    group = _group_cand(confidence=0.92)
    other = _non_group_cand(confidence=0.91)
    result = _ambiguous([group, other])

    resolver = _make_resolver()
    out = resolver._apply_group_preference_tiebreak(result)

    assert out.is_resolved
    assert out.entity_id == group.entity_id
    assert out.confidence == group.confidence
    assert out.reasons == [ReasonCode.GROUP_PREFERENCE_TIEBREAK]
    assert out.match_tier is None
    assert out.candidates == result.candidates  # original candidates preserved


def test_rule_fires_when_group_at_rank_two() -> None:
    """AMBIGUOUS with non-group at rank 1, group at rank 2 → RESOLVED to group's confidence."""
    other = _non_group_cand(confidence=0.93)
    group = _group_cand(confidence=0.91)
    result = _ambiguous([other, group])

    resolver = _make_resolver()
    out = resolver._apply_group_preference_tiebreak(result)

    assert out.is_resolved
    assert out.entity_id == group.entity_id
    # Confidence must be the group's, NOT the rank-1 non-group's.
    assert out.confidence == group.confidence
    assert out.reasons == [ReasonCode.GROUP_PREFERENCE_TIEBREAK]
    assert out.match_tier is None


# ---------------------------------------------------------------------------
# _apply_group_preference_tiebreak — no-op tests
# ---------------------------------------------------------------------------


def test_rule_no_op_when_group_at_rank_three() -> None:
    """Group at rank 3 must NOT fire the rule — latent-hazard pin."""
    other1 = _non_group_cand("region/A", confidence=0.93)
    other2 = _non_group_cand("region/B", confidence=0.90)
    group = _group_cand(confidence=0.85)
    result = _ambiguous([other1, other2, group])

    resolver = _make_resolver()
    out = resolver._apply_group_preference_tiebreak(result)

    assert out.is_ambiguous
    assert out.reasons == result.reasons  # original reasons preserved verbatim


def test_rule_no_op_when_two_groups_tied_at_top() -> None:
    """Two group-typed candidates in top 2 → genuine group-vs-group conflict, stays AMBIGUOUS."""
    group1 = _group_cand("groups/G7", confidence=0.92, entity_type="geo.organization")
    group2 = _group_cand(
        "groups/G20", confidence=0.91, entity_type="geo.continental_union"
    )
    result = _ambiguous([group1, group2])

    resolver = _make_resolver()
    out = resolver._apply_group_preference_tiebreak(result)

    assert out.is_ambiguous


def test_rule_no_op_when_zero_groups() -> None:
    """Top 2 contain no group-typed candidates → rule does not fire."""
    other1 = _non_group_cand("region/A", confidence=0.93)
    other2 = _non_group_cand("region/B", confidence=0.91)
    result = _ambiguous([other1, other2])

    resolver = _make_resolver()
    out = resolver._apply_group_preference_tiebreak(result)

    assert out.is_ambiguous


def test_rule_no_op_when_already_resolved() -> None:
    """RESOLVED result is returned unchanged (identity)."""
    result = _resolved()
    resolver = _make_resolver()
    out = resolver._apply_group_preference_tiebreak(result)
    assert out is result


def test_rule_no_op_when_no_match() -> None:
    """NO_MATCH result is returned unchanged."""
    result = _no_match()
    resolver = _make_resolver()
    out = resolver._apply_group_preference_tiebreak(result)
    assert out is result


def test_rule_no_op_when_empty_candidates() -> None:
    """AMBIGUOUS with no candidates is returned unchanged (defensive guard)."""
    result = _ambiguous([])
    resolver = _make_resolver()
    out = resolver._apply_group_preference_tiebreak(result)
    assert out.is_ambiguous


# ---------------------------------------------------------------------------
# _apply_group_preference_tiebreak — pack metadata consultation
# ---------------------------------------------------------------------------


def test_rule_consults_pack_metadata_per_candidate() -> None:
    """Pack-declared group_entity_types are consulted per candidate's pack_id.

    Sub-case A: candidate with entity_type in geo's group_entity_types → fires.
    Sub-case B: same entity_type but pack_id="org" (org has empty set) → does NOT fire.
    """
    # Sub-case A: geo pack declares "geo.organization" as group-like → rule fires.
    geo_group = _group_cand(
        "groups/G7", confidence=0.92, entity_type="geo.organization", pack_id="geo"
    )
    org_region = _non_group_cand(
        "org/SomeOrg", confidence=0.90, entity_type="org.ngo", pack_id="org"
    )
    result_a = _ambiguous([geo_group, org_region])

    resolver = _make_resolver()
    out_a = resolver._apply_group_preference_tiebreak(result_a)

    assert out_a.is_resolved, "Sub-case A: expected rule to fire for geo.organization"
    assert out_a.pack_id == "geo"

    # Sub-case B: same entity_type but routed through org pack (empty group_entity_types).
    org_group = _group_cand(
        "org/G7Alias",
        confidence=0.92,
        entity_type="geo.organization",
        pack_id="org",
    )
    result_b = _ambiguous([org_group, org_region])

    out_b = resolver._apply_group_preference_tiebreak(result_b)

    assert out_b.is_ambiguous, (
        "Sub-case B: org pack has empty group_entity_types → no fire"
    )


# ---------------------------------------------------------------------------
# _resolve_group_id adapter tests
# ---------------------------------------------------------------------------


def test_resolve_group_id_returns_id_when_resolved() -> None:
    """_resolve_group_id returns entity_id when resolve() returns RESOLVED."""
    backend = _StubBackend(resolve_result=_resolved("groups/G7"))
    resolver = Resolver(runner=backend)  # type: ignore[arg-type]
    assert resolver._resolve_group_id("G7") == "groups/G7"


def test_resolve_group_id_raises_ambiguous_on_two_groups() -> None:
    """Two group candidates both in top 2 → rule does not fire → adapter raises AmbiguousResolutionError."""
    group1 = _group_cand("groups/G7", confidence=0.92, entity_type="geo.organization")
    group2 = _group_cand(
        "groups/G20", confidence=0.91, entity_type="geo.continental_union"
    )
    backend = _StubBackend(resolve_result=_ambiguous([group1, group2]))
    resolver = Resolver(runner=backend)  # type: ignore[arg-type]

    with pytest.raises(AmbiguousResolutionError) as exc_info:
        resolver._resolve_group_id("G")

    assert len(exc_info.value.candidates) == 2


def test_resolve_group_id_raises_for_rank_three_group() -> None:
    """Group at rank 3 → rule does not fire → adapter raises AmbiguousResolutionError."""
    other1 = _non_group_cand("region/A", confidence=0.93)
    other2 = _non_group_cand("region/B", confidence=0.90)
    group = _group_cand(confidence=0.85)
    backend = _StubBackend(resolve_result=_ambiguous([other1, other2, group]))
    resolver = Resolver(runner=backend)  # type: ignore[arg-type]

    with pytest.raises(AmbiguousResolutionError):
        resolver._resolve_group_id("somequery")


def test_resolve_group_id_raises_group_not_found_on_no_match() -> None:
    """NO_MATCH result → adapter raises GroupNotFoundError."""
    backend = _StubBackend(resolve_result=_no_match())
    resolver = Resolver(runner=backend)  # type: ignore[arg-type]

    with pytest.raises(GroupNotFoundError):
        resolver._resolve_group_id("UnknownGroup")


def test_resolve_group_id_raises_resolution_error_on_error() -> None:
    """ERROR result → adapter raises ResolutionError (NOT GroupNotFoundError).

    Ensures store outages surface as ResolutionError and are not silently swallowed
    by callers catching GroupNotFoundError for "skip unknowns" logic.
    """
    backend = _StubBackend(resolve_result=_error())
    resolver = Resolver(runner=backend)  # type: ignore[arg-type]

    with pytest.raises(ResolutionError) as exc_info:
        resolver._resolve_group_id("StoreFailing")

    # Must be ResolutionError but NOT GroupNotFoundError (GroupNotFoundError subclasses
    # ResolutionError with NO_MATCH status; ERROR status is distinct).
    assert not isinstance(exc_info.value, GroupNotFoundError)
    assert exc_info.value.status == ResolutionStatus.ERROR


# ---------------------------------------------------------------------------
# known_groups — pack-declared types
# ---------------------------------------------------------------------------


def test_rule_no_op_when_single_candidate() -> None:
    """AMBIGUOUS with exactly one candidate → the ``< 2`` guard returns result unchanged."""
    single = _group_cand(confidence=0.92)
    result = _ambiguous([single])

    resolver = _make_resolver()
    out = resolver._apply_group_preference_tiebreak(result)

    assert out.is_ambiguous
    assert out.reasons == result.reasons  # original reasons preserved verbatim


def test_known_groups_includes_pack_declared_types() -> None:
    """known_groups() enumerates entity types from pack metadata, including custom packs.

    Build a resolver whose _packs includes a custom pack declaring "geo.alliance".
    The _stores dict maps "custom" to a stub store that returns a synthetic alliance
    entity. known_groups() must include that entity's canonical name alongside geo's.
    """
    alliance_entity = _make_entity(
        entity_id="alliance/TEST_ALLIANCE",
        entity_type="geo.alliance",
        canonical_name="Test Alliance",
    )
    stub_store = _StubStore({"geo.alliance": [alliance_entity]})

    packs: dict[str, object] = {
        "geo": GeoPack(),
        "org": OrgPack(),
        "custom": _CustomPack(),
    }
    backend = _StubBackend(packs=packs, stores={"custom": stub_store})
    resolver = Resolver(runner=backend)  # type: ignore[arg-type]

    # _all_pack_group_types() should union across all packs including custom.
    all_types = resolver._all_pack_group_types()
    assert "geo.alliance" in all_types
    assert "geo.organization" in all_types
    assert "geo.continental_union" in all_types

    # known_groups() should list "Test Alliance" from the custom store.
    groups = resolver.known_groups()
    assert "Test Alliance" in groups
