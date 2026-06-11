"""Unit tests for core/parse/_pivot.py.

Tests apply_to_pivot and coerce_to_str_list helpers without constructing
a full Resolver. apply_to_pivot covers both the store_for_domain path and
the per-entity fallback; coerce_to_str_list covers None, NaN, int, and str.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import pytest

from resolvekit.core.model import (
    EntityRecord,
    ResolutionResult,
    ResolutionStatus,
)
from resolvekit.core.parse._pivot import apply_to_pivot, coerce_to_str_list
from resolvekit.core.parse.result import ParsedEntity

# ---------------------------------------------------------------------------
# Minimal mock runner
# ---------------------------------------------------------------------------


@dataclass
class _MockRunner:
    """Minimal runner stub for pivot tests."""

    entities: dict[str, EntityRecord] = field(default_factory=dict)
    store_raises: bool = False

    def store_for_domain(self, domain: str) -> Any:
        if self.store_raises:
            raise ValueError(f"no store for {domain!r}")
        raise NotImplementedError("store not configured for this test")

    def get_entity(self, entity_id: str) -> EntityRecord | None:
        return self.entities.get(entity_id)

    # Satisfy the rest of the ResolverBackend protocol as no-ops.
    @property
    def available_packs(self) -> frozenset[str]:
        return frozenset()

    @property
    def available_entity_types(self) -> frozenset[str]:
        return frozenset()

    @property
    def available_code_systems(self) -> frozenset[str]:
        return frozenset()

    @property
    def available_group_types(self) -> frozenset[str]:
        return frozenset()

    def resolve(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def resolve_detailed(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def lookup_code(self, *args: Any, **kwargs: Any) -> list[str]:
        return []

    def lookup_name_exact(self, *args: Any, **kwargs: Any) -> list[tuple[str, str]]:
        return []

    def lookup_code_attributed(
        self, *args: Any, **kwargs: Any
    ) -> list[tuple[str, str]]:
        return []

    def get_relations_as_of(self, *args: Any, **kwargs: Any) -> frozenset[str]:
        return frozenset()

    def get_reverse_relations(self, *args: Any, **kwargs: Any) -> list[str]:
        return []

    def get_pack_group_types(self, *args: Any, **kwargs: Any) -> frozenset[str]:
        return frozenset()

    def is_snapshot_entity(self, *args: Any, **kwargs: Any) -> bool:
        return False

    def lookup_pack_id(self) -> str | None:
        return None

    def list_entities_by_type(self, *args: Any, **kwargs: Any) -> list[EntityRecord]:
        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(
    entity_id: str = "country/USA",
    canonical_name: str = "United States",
    iso3: str = "USA",
) -> EntityRecord:
    from resolvekit.core.model.entity import CodeRecord

    return EntityRecord(
        entity_id=entity_id,
        entity_type="geo.country",
        canonical_name=canonical_name,
        canonical_name_norm=canonical_name.lower(),
        names=[],
        codes=[CodeRecord(system="iso3", value=iso3, value_norm=iso3.lower())],
    )


def _make_parsed_entity(
    entity_id: str = "country/USA",
    pack_id: str = "geo",
    status: ResolutionStatus = ResolutionStatus.RESOLVED,
) -> ParsedEntity:
    resolution = ResolutionResult(
        status=status,
        entity_id=entity_id if status == ResolutionStatus.RESOLVED else None,
        confidence=0.9 if status == ResolutionStatus.RESOLVED else None,
        reasons=[],
        query_text="test",
    )
    return ParsedEntity(
        surface="test",
        start=0,
        end=4,
        entity_id=entity_id if status == ResolutionStatus.RESOLVED else None,
        entity_type="geo.country" if status == ResolutionStatus.RESOLVED else None,
        pack_id=pack_id if status == ResolutionStatus.RESOLVED else None,
        status=status,
        confidence=0.9 if status == ResolutionStatus.RESOLVED else None,
        resolution=resolution,
    )


# ---------------------------------------------------------------------------
# gap 1: apply_to_pivot fallback branch
# ---------------------------------------------------------------------------


class TestApplyToPivotFallback:
    """store_for_domain raises ValueError → fallback to per-entity get_entity."""

    def test_fallback_populates_output(self) -> None:
        """When store_for_domain raises, get_entity is used and output is set."""
        entity = _make_entity()
        runner = _MockRunner(entities={"country/USA": entity}, store_raises=True)

        entities = [_make_parsed_entity(entity_id="country/USA", pack_id="geo")]
        result = apply_to_pivot(
            entities, "iso3", runner=runner, code_systems=frozenset({"iso3"})
        )

        assert len(result) == 1
        assert result[0].output == "USA"

    def test_fallback_per_entity_miss_leaves_output_none(self) -> None:
        """Fallback get_entity returning None → entity not in map → output stays None."""
        runner = _MockRunner(entities={}, store_raises=True)

        entities = [_make_parsed_entity(entity_id="country/USA", pack_id="geo")]
        result = apply_to_pivot(
            entities, "iso3", runner=runner, code_systems=frozenset({"iso3"})
        )

        assert len(result) == 1
        # Entity not in entity_map → output stays None.
        assert result[0].output is None

    def test_nil_span_skipped_by_fallback(self) -> None:
        """NO_MATCH spans are not looked up and output stays None."""
        runner = _MockRunner(store_raises=True)

        nil_entity = _make_parsed_entity(
            entity_id="country/USA",
            pack_id="geo",
            status=ResolutionStatus.NO_MATCH,
        )
        result = apply_to_pivot(
            [nil_entity], "iso3", runner=runner, code_systems=frozenset({"iso3"})
        )

        assert len(result) == 1
        assert result[0].output is None

    def test_store_success_path_populates_output(self) -> None:
        """When store_for_domain works, bulk_get_entities is used."""

        class _MockStore:
            def bulk_get_entities(
                self, entity_ids: list[str]
            ) -> dict[str, EntityRecord]:
                return {"country/USA": _make_entity()}

        class _SuccessRunner(_MockRunner):
            def store_for_domain(self, domain: str) -> Any:
                return _MockStore()

        runner = _SuccessRunner()
        entities = [_make_parsed_entity(entity_id="country/USA", pack_id="geo")]
        result = apply_to_pivot(
            entities, "iso3", runner=runner, code_systems=frozenset({"iso3"})
        )

        assert len(result) == 1
        assert result[0].output == "USA"

    def test_to_none_returns_unchanged(self) -> None:
        """to=None returns the input list unchanged."""
        runner = _MockRunner()
        entities = [_make_parsed_entity()]
        result = apply_to_pivot(
            entities, None, runner=runner, code_systems=frozenset({"iso3"})
        )
        assert result is entities


# ---------------------------------------------------------------------------
# gap 2: coerce_to_str_list NaN handling
# ---------------------------------------------------------------------------


class TestCoerceToStrList:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, ""),
            (float("nan"), ""),
            (3, "3"),
            ("x", "x"),
            (0, "0"),
            (math.nan, ""),
        ],
    )
    def test_coerce_parametrized(self, value: Any, expected: str) -> None:
        result = coerce_to_str_list([value])
        assert result == [expected]

    def test_empty_input(self) -> None:
        assert coerce_to_str_list([]) == []

    def test_mixed_list(self) -> None:
        result = coerce_to_str_list([None, float("nan"), 3, "x"])
        assert result == ["", "", "3", "x"]
