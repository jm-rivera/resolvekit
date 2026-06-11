"""Tests for bulk() code-input short-circuit.

Verifies that when all unique values match a code-shape regex (or when
``from_system=`` is explicitly set), the implementation calls
``_runner.lookup_code(...)`` rather than the full name-resolution pipeline.
"""

from __future__ import annotations

import weakref
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

from resolvekit.core.api.bulk import _bulk_dispatch
from resolvekit.core.api.code_lookup import CodeLookup, looks_like_code
from resolvekit.core.model.bulk_result import BulkResult
from resolvekit.core.model.entity import CodeRecord, EntityRecord
from resolvekit.core.model.result import ReasonCode, ResolutionResult, ResolutionStatus

# ---------------------------------------------------------------------------
# looks_like_code helper
# ---------------------------------------------------------------------------


def test_iso2_looks_like_code():
    assert looks_like_code("US")
    assert looks_like_code("DE")


def test_iso3_looks_like_code():
    assert looks_like_code("USA")
    assert looks_like_code("DEU")


def test_numeric_looks_like_code():
    assert looks_like_code("840")
    assert looks_like_code("276")


def test_dcid_looks_like_code():
    assert looks_like_code("country/USA")


def test_free_text_not_code():
    assert not looks_like_code("United States")
    assert not looks_like_code("Germany")


def test_lowercase_alpha_codes_are_code_shaped():
    # Case-insensitive: "uk" routes to code lookup the same as "UK".
    assert looks_like_code("us")
    assert looks_like_code("uk")
    assert looks_like_code("usa")
    assert looks_like_code("Uk")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(entity_id: str = "country/USA", iso3: str = "USA") -> EntityRecord:
    return EntityRecord(
        entity_id=entity_id,
        entity_type="geo.country",
        canonical_name="United States",
        canonical_name_norm="united states",
        codes=[
            CodeRecord(system="iso3", value=iso3, value_norm=iso3.lower()),
            CodeRecord(system="iso2", value="US", value_norm="us"),
        ],
    )


_MOCK_CODE_SYSTEMS = frozenset({"iso2", "iso3", "numeric", "dcid", "wikidata"})


def _make_resolver_with_lookup(
    entity: EntityRecord | None,
    lookup_result: list[str] | None = None,
) -> MagicMock:
    """Build a mock resolver where lookup_code returns *entity*'s ID.

    Uses a real CodeLookup so resolver._code_lookup.resolve_or_lookup(...)
    calls route through the canonical implementation.
    """
    resolver = MagicMock()
    resolver._routing_mode = None
    resolver._runner.available_packs = frozenset({"geo"})
    resolver._runner.available_code_systems = _MOCK_CODE_SYSTEMS
    eid = entity.entity_id if entity is not None else None
    resolver._runner.lookup_code.return_value = (
        [eid] if eid and lookup_result is None else (lookup_result or [])
    )
    resolver._runner.get_entity.return_value = entity
    resolver._code_lookup = CodeLookup(runner=resolver._runner)
    return resolver


# ---------------------------------------------------------------------------
# from_system= explicit path calls lookup_code, not resolve_many
# ---------------------------------------------------------------------------


def test_explicit_from_system_uses_lookup_code():
    entity = _make_entity()
    resolver = _make_resolver_with_lookup(entity)

    _bulk_dispatch(
        resolver=resolver,
        values=["US"],
        to=None,
        output="series",
        domain=None,
        context=None,
        from_system="iso2",
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )
    # lookup_code should have been called; _resolve_many_internal should NOT
    resolver._runner.lookup_code.assert_called()
    resolver._resolve_many_internal.assert_not_called()


def test_explicit_from_system_returns_entity_id():
    entity = _make_entity()
    resolver = _make_resolver_with_lookup(entity)

    result = _bulk_dispatch(
        resolver=resolver,
        values=["US"],
        to=None,
        output="series",
        domain=None,
        context=None,
        from_system="iso2",
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )
    assert isinstance(result, BulkResult)
    source = result.source[0]
    assert source.entity_id == "country/USA"


# ---------------------------------------------------------------------------
# Auto-detect path: all-code input uses lookup_code
# ---------------------------------------------------------------------------


def test_all_codes_input_bypasses_resolve_many():
    entity = _make_entity()
    resolver = _make_resolver_with_lookup(entity)

    _bulk_dispatch(
        resolver=resolver,
        values=["USA"],  # iso3 — looks_like_code("USA") is True
        to=None,
        output="series",
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )
    resolver._runner.lookup_code.assert_called()
    resolver._resolve_many_internal.assert_not_called()


def test_mixed_text_and_code_uses_resolve_many():
    """If any unique is free-text, the whole batch goes through _resolve_many_internal."""
    from resolvekit.core.model.result import ResolutionResultList

    entity = _make_entity()
    resolver = MagicMock()
    resolver._routing_mode = None
    resolver._runner.available_packs = frozenset({"geo"})
    resolver.code_systems.return_value = frozenset({"iso2", "iso3"})

    resolved = ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        entity_id=entity.entity_id,
        reasons=[ReasonCode.EXACT_NAME_MATCH],
    )
    no_match = ResolutionResult(
        status=ResolutionStatus.NO_MATCH,
        reasons=[ReasonCode.NO_CANDIDATES],
    )
    resolver._resolve_many_internal.return_value = ResolutionResultList(
        [resolved, no_match]
    )

    _bulk_dispatch(
        resolver=resolver,
        values=["US", "United States"],
        to=None,
        output="series",
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )
    # "United States" is not a code → batch falls through to _resolve_many_internal
    resolver._resolve_many_internal.assert_called_once()
    resolver._runner.lookup_code.assert_not_called()


# ---------------------------------------------------------------------------
# include_entity forced when to= is set
# ---------------------------------------------------------------------------


def test_to_set_forces_entity_hydration():
    """When to= is given, the entity must be populated for dispatch_pivot."""
    entity = _make_entity()
    resolver = _make_resolver_with_lookup(entity)

    out = _bulk_dispatch(
        resolver=resolver,
        values=["US"],
        to="iso3",
        output="series",
        domain=None,
        context=None,
        from_system="iso2",
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )
    # get_entity should have been called to hydrate the entity for dispatch_pivot
    resolver._runner.get_entity.assert_called_with("country/USA")
    # The pivot value should be the iso3 code
    assert out == ["USA"]


# ---------------------------------------------------------------------------
# Dedup: lookup_code called once per unique code
# ---------------------------------------------------------------------------


def test_dedup_on_code_path_calls_lookup_once_per_unique():
    entity = _make_entity()
    resolver = _make_resolver_with_lookup(entity)

    _bulk_dispatch(
        resolver=resolver,
        values=["US", "US", "US"],  # three identical values
        to=None,
        output="series",
        domain=None,
        context=None,
        from_system="iso2",
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )
    # lookup_code should be called once per unique, not once per row
    # With from_system="iso2", _resolve_or_lookup is called once per unique
    # Each call to _resolve_or_lookup calls lookup_code once
    call_count = resolver._runner.lookup_code.call_count
    assert call_count == 1


# ---------------------------------------------------------------------------
# Code not found falls through to null
# ---------------------------------------------------------------------------


def test_code_not_found_returns_null():
    resolver = MagicMock()
    resolver._routing_mode = None
    resolver._runner.available_packs = frozenset({"geo"})
    resolver._runner.lookup_code.return_value = []  # nothing found
    resolver._runner.available_code_systems = frozenset({"iso2"})
    resolver._code_lookup = CodeLookup(runner=resolver._runner)

    out = _bulk_dispatch(
        resolver=resolver,
        values=["ZZ"],
        to="iso3",
        output="series",
        domain=None,
        context=None,
        from_system="iso2",
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )
    assert out == [None]


# ---------------------------------------------------------------------------
# Bulk code path vs. CodeLookup.resolve_or_lookup
#
# _bulk_dispatch uses _bulk_resolve_or_lookup (bulk.py) for code inputs while
# Resolver._code_lookup.resolve_or_lookup (code_lookup.py) is the canonical
# implementation. This test pins the current behaviour: any refactor that routes
# bulk through CodeLookup.resolve_or_lookup must not change the entity_id or
# status returned for these inputs.
# ---------------------------------------------------------------------------


@dataclass
class _ProtocolRunner:
    """Full ResolverBackend stub — no MagicMock, protocol-compliant.

    Code tables:
      iso3 usa  → country/USA
      iso3 gbr  → country/GBR
      iso2 us   → country/USA
      iso2 gb   → country/GBR
      (no entry for fra → NO_MATCH)
    """

    _codes: dict[tuple[str, str], list[str]] = field(
        default_factory=lambda: {
            ("iso3", "usa"): ["country/USA"],
            ("iso3", "gbr"): ["country/GBR"],
            ("iso2", "us"): ["country/USA"],
            ("iso2", "gb"): ["country/GBR"],
        }
    )
    _available_code_systems: frozenset[str] = field(
        default_factory=lambda: frozenset({"iso2", "iso3", "numeric"})
    )

    def resolve(self, query: Any, context: Any, **_: Any) -> ResolutionResult:
        return ResolutionResult(status=ResolutionStatus.NO_MATCH)

    def resolve_detailed(self, query: Any, context: Any, **_: Any) -> Any:
        from resolvekit.core.engine import PipelineResult

        return PipelineResult(result=ResolutionResult(status=ResolutionStatus.NO_MATCH))

    def close(self) -> None:
        pass

    def get_entity(self, entity_id: str) -> EntityRecord | None:
        return None

    def lookup_code(
        self,
        system: str,
        value_norm: str,
        *,
        pack_filter: frozenset[str] | None = None,
    ) -> list[str]:
        return self._codes.get((system, value_norm), [])

    @property
    def available_packs(self) -> frozenset[str]:
        return frozenset({"geo"})

    @property
    def available_entity_types(self) -> frozenset[str]:
        return frozenset()

    @property
    def available_code_systems(self) -> frozenset[str]:
        return self._available_code_systems

    @property
    def available_group_types(self) -> frozenset[str]:
        return frozenset()

    def get_reverse_relations(
        self, *, entity_id: str, relation_type: str, as_of: Any = None
    ) -> list[str]:
        return []

    def get_relations_as_of(
        self, *, entity_id: str, relation_type: str, as_of: Any
    ) -> frozenset[str]:
        return frozenset()

    def list_entities_by_type(self, *, entity_type: str) -> list[EntityRecord]:
        return []

    def get_pack_group_types(self, *, pack_id: str) -> frozenset[str]:
        return frozenset()

    def is_snapshot_entity(self, *, entity_id: str) -> bool:
        return False

    def lookup_pack_id(self) -> str | None:
        return "geo"

    def normalize_code_value(
        self, system: str, value: str, *, pack_filter: frozenset[str] | None = None
    ) -> str:
        return value.casefold()

    def lookup_name_exact(
        self, *, value: str, pack_filter: frozenset[str] | None = None
    ) -> list[tuple[str, str]]:
        return []


def _make_real_resolver() -> Any:
    """Build a real Resolver wrapping _ProtocolRunner, with _resolve_inner stubbed."""
    from resolvekit.core.api.resolver import Resolver

    runner = _ProtocolRunner()
    resolver = Resolver(runner=runner, cache_size=0)  # type: ignore[arg-type]

    # Stub _resolve_inner so free-text fall-throughs return a deterministic NO_MATCH
    # rather than hitting a real FTS pipeline that the stub runner doesn't support.
    def _fake_inner(
        text: str,
        *,
        normalized_domain: Any,
        context: Any,
        include_entity: bool,
        timeout: Any,
        _self_ref: Any = None,
    ) -> ResolutionResult:
        return ResolutionResult(
            status=ResolutionStatus.NO_MATCH,
            reasons=[ReasonCode.NO_CANDIDATES],
            query_text=text,
        )

    resolver._resolve_inner = _fake_inner  # type: ignore[method-assign]
    return resolver


# Test inputs: code-shaped values and a name input.
# Code inputs exercise _bulk_resolve_or_lookup; names exercise the fallback
# path through _resolve_inner.
@pytest.mark.parametrize(
    "value",
    [
        "USA",  # ISO-3 → resolves to country/USA
        "GBR",  # ISO-3 → resolves to country/GBR
        "FRA",  # ISO-3 unknown → NO_MATCH on both paths
        "United States",  # free-text name → both paths fall through to _resolve_inner
    ],
)
def test_bulk_and_resolve_or_lookup_agree_on_code_inputs(value: str) -> None:
    """bulk([x]) and CodeLookup.resolve_or_lookup(x) must agree on entity_id and status.

    Pins the behaviour that any refactor routing bulk through
    CodeLookup.resolve_or_lookup instead of its own _bulk_resolve_or_lookup
    copy must preserve.
    """
    resolver = _make_real_resolver()

    # --- bulk path ---
    bulk_result = resolver.bulk(values=[value], not_found="null", on_error="raise")
    # bulk returns a BulkResult when to=None; source[0] is the ResolutionResult.
    assert isinstance(bulk_result, BulkResult)
    bulk_res: ResolutionResult = bulk_result.source[0]

    # --- CodeLookup.resolve_or_lookup path ---
    ref: weakref.ref = weakref.ref(resolver)
    lookup_res = resolver._code_lookup.resolve_or_lookup(
        value,
        explainer_ref=ref,
        from_system=None,
        domain=None,
        context=None,
        include_entity=False,
        timeout=None,
        resolve_inner_fn=resolver._resolve_inner,
    )

    assert bulk_res.entity_id == lookup_res.entity_id, (
        f"entity_id mismatch for {value!r}: "
        f"bulk={bulk_res.entity_id!r}, resolve_or_lookup={lookup_res.entity_id!r}"
    )
    assert bulk_res.status == lookup_res.status, (
        f"status mismatch for {value!r}: "
        f"bulk={bulk_res.status!r}, resolve_or_lookup={lookup_res.status!r}"
    )
