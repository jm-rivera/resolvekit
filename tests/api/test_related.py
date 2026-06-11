"""Tests for Resolver.related() and Resolver.diagnostics.unresolved_relations().

Unit tests use MockEntityStore + PipelineRunner (no bundled data).
Integration tests marked @pytest.mark.integration require the bundled geo pack.
"""

from __future__ import annotations

from datetime import date
from typing import cast

import pytest

import resolvekit
from resolvekit.core.api import Resolver
from resolvekit.core.engine import PipelineRunner
from resolvekit.core.engine.decision import ThresholdDecisionPolicy
from resolvekit.core.errors import (
    AmbiguousResolutionError,
    EntityNotFoundError,
    UnknownCodeSystemError,
)
from resolvekit.core.explain import NullTraceSink
from resolvekit.core.model import (
    EntityRecord,
    RelationRecord,
)
from resolvekit.core.model.entity import CodeRecord, NameRecord
from tests.conftest import MockEntityStore

_DEFAULT_POLICY = ThresholdDecisionPolicy(
    confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_resolver(
    entities: dict[str, EntityRecord],
    *,
    names: dict[str, list[str]] | None = None,
    pack_id: str = "geo",
) -> Resolver:
    """Build a test resolver backed by a MockEntityStore.

    *pack_id* must be non-None for lookup_name_exact to work (StoreView skips
    stores whose pack_id is None).
    """
    store = MockEntityStore(entities=entities, names=names or {})
    runner = PipelineRunner(
        trace_sink=NullTraceSink(),
        store=store,
        sources=[],
        decision_policy=_DEFAULT_POLICY,
        pack_id=pack_id,
    )
    return Resolver(runner=runner)


def _country(
    entity_id: str,
    name: str,
    relations: list[RelationRecord] | None = None,
    codes: list[CodeRecord] | None = None,
) -> EntityRecord:
    return EntityRecord(
        entity_id=entity_id,
        entity_type="geo.country",
        canonical_name=name,
        canonical_name_norm=name.lower(),
        relations=relations or [],
        codes=codes or [],
    )


def _region(entity_id: str, name: str) -> EntityRecord:
    return EntityRecord(
        entity_id=entity_id,
        entity_type="geo.region",
        canonical_name=name,
        canonical_name_norm=name.lower(),
    )


# ---------------------------------------------------------------------------
# Unit: related() — input modes
# ---------------------------------------------------------------------------


class TestRelatedInputModes:
    def test_entity_record_input_resolves_known_target(self) -> None:
        europe = _region("region/EUR", "Europe")
        france = _country(
            "country/FRA",
            "France",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="region/EUR")
            ],
        )
        resolver = _make_resolver({"region/EUR": europe, "country/FRA": france})

        result = resolver.related(france, relation="contained_in")

        assert len(result) == 1
        assert isinstance(result[0], EntityRecord)
        assert result[0].entity_id == "region/EUR"

    def test_string_entity_id_input(self) -> None:
        europe = _region("region/EUR", "Europe")
        france = _country(
            "country/FRA",
            "France",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="region/EUR")
            ],
        )
        resolver = _make_resolver({"region/EUR": europe, "country/FRA": france})

        result = cast(
            list[EntityRecord], resolver.related("country/FRA", relation="contained_in")
        )

        assert len(result) == 1
        assert result[0].entity_id == "region/EUR"

    def test_exact_canonical_name_input(self) -> None:
        europe = _region("region/EUR", "Europe")
        france = _country(
            "country/FRA",
            "France",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="region/EUR")
            ],
        )
        # names dict keys must be lowercased to match the lookup
        resolver = _make_resolver(
            {"region/EUR": europe, "country/FRA": france},
            names={"france": ["country/FRA"]},
        )

        result = cast(
            list[EntityRecord], resolver.related("France", relation="contained_in")
        )

        assert len(result) == 1
        assert result[0].entity_id == "region/EUR"


# ---------------------------------------------------------------------------
# Unit: related() — error cases
# ---------------------------------------------------------------------------


class TestRelatedErrorCases:
    def test_unknown_string_raises_entity_not_found_error(self) -> None:
        resolver = _make_resolver({})

        with pytest.raises(EntityNotFoundError):
            resolver.related("NoSuchPlaceXYZ")

    def test_near_miss_raises_not_fuzzy_guessed(self) -> None:
        # "Westeurop" is a near-miss for "Western Europe" but must NOT fuzzy-match.
        europe = _region("region/EUR", "Europe")
        resolver = _make_resolver(
            {"region/EUR": europe},
            names={"europe": ["region/EUR"]},
        )

        with pytest.raises(EntityNotFoundError):
            resolver.related("Westeurop")

    def test_ambiguous_name_raises_ambiguous_resolution_error(self) -> None:
        # Two entities share the same name (as seen by the exact-name index).
        entity_a = _region("region/A", "Ambiguous")
        entity_b = _region("region/B", "Ambiguous")
        resolver = _make_resolver(
            {"region/A": entity_a, "region/B": entity_b},
            names={"ambiguous": ["region/A", "region/B"]},
        )

        with pytest.raises(AmbiguousResolutionError):
            resolver.related("Ambiguous")

    def test_closed_resolver_raises_runtime_error(self) -> None:
        france = _country("country/FRA", "France")
        resolver = _make_resolver({"country/FRA": france})
        resolver.close()

        with pytest.raises(RuntimeError, match="closed"):
            resolver.related(france)


# ---------------------------------------------------------------------------
# Unit: related() — edge filtering
# ---------------------------------------------------------------------------


class TestRelatedEdgeFiltering:
    def test_omits_unresolvable_targets(self) -> None:
        # "WesternEurope" is not in the store — must be omitted, not fuzzy-guessed.
        europe = _region("region/EUR", "Europe")
        france = _country(
            "country/FRA",
            "France",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="region/EUR"),
                RelationRecord(relation_type="contained_in", target_id="WesternEurope"),
            ],
        )
        resolver = _make_resolver({"region/EUR": europe, "country/FRA": france})

        result = cast(list[EntityRecord], resolver.related(france))

        entity_ids = [e.entity_id for e in result]
        assert "region/EUR" in entity_ids
        assert "WesternEurope" not in entity_ids
        # Only the resolvable target is returned.
        assert len(result) == 1

    def test_relation_filter(self) -> None:
        nato = _region("groups/NATO", "NATO")
        europe = _region("region/EUR", "Europe")
        germany = _country(
            "country/DEU",
            "Germany",
            relations=[
                RelationRecord(relation_type="member_of", target_id="groups/NATO"),
                RelationRecord(relation_type="contained_in", target_id="region/EUR"),
            ],
        )
        resolver = _make_resolver(
            {"groups/NATO": nato, "region/EUR": europe, "country/DEU": germany}
        )

        contained = cast(
            list[EntityRecord], resolver.related(germany, relation="contained_in")
        )
        members = cast(
            list[EntityRecord], resolver.related(germany, relation="member_of")
        )

        assert [e.entity_id for e in contained] == ["region/EUR"]
        assert [e.entity_id for e in members] == ["groups/NATO"]

    def test_empty_relations_returns_empty_list(self) -> None:
        france = _country("country/FRA", "France")
        resolver = _make_resolver({"country/FRA": france})

        result = resolver.related(france)

        assert result == []


# ---------------------------------------------------------------------------
# Unit: related() — as_of temporal filtering
# ---------------------------------------------------------------------------


class TestRelatedTemporalFiltering:
    def _make_eu_resolver(self) -> tuple[Resolver, EntityRecord, EntityRecord]:
        eu = _region("groups/EU", "European Union")
        germany = _country(
            "country/DEU",
            "Germany",
            relations=[
                RelationRecord(
                    relation_type="member_of",
                    target_id="groups/EU",
                    valid_from="1958-01-01",
                    valid_until=None,
                )
            ],
        )
        resolver = _make_resolver({"groups/EU": eu, "country/DEU": germany})
        return resolver, germany, eu

    def test_as_of_active(self) -> None:
        resolver, germany, _ = self._make_eu_resolver()

        result = cast(
            list[EntityRecord],
            resolver.related(germany, relation="member_of", as_of=date(2025, 1, 1)),
        )

        assert len(result) == 1
        assert result[0].entity_id == "groups/EU"

    def test_as_of_before_valid_from(self) -> None:
        resolver, germany, _ = self._make_eu_resolver()

        result = resolver.related(germany, relation="member_of", as_of=date(1950, 1, 1))

        assert result == []

    def test_as_of_after_valid_until(self) -> None:
        eu = _region("groups/EU", "European Union")
        uk = _country(
            "country/GBR",
            "United Kingdom",
            relations=[
                RelationRecord(
                    relation_type="member_of",
                    target_id="groups/EU",
                    valid_from="1973-01-01",
                    valid_until="2020-02-01",
                )
            ],
        )
        resolver = _make_resolver({"groups/EU": eu, "country/GBR": uk})

        # After Brexit
        after = resolver.related(uk, relation="member_of", as_of=date(2025, 1, 1))
        assert after == []

        # Before Brexit
        before = cast(
            list[EntityRecord],
            resolver.related(uk, relation="member_of", as_of=date(2018, 1, 1)),
        )
        assert len(before) == 1
        assert before[0].entity_id == "groups/EU"

    def test_as_of_none_returns_all_edges(self) -> None:
        # A closed membership (valid_until set) should still be returned when as_of=None.
        eu = _region("groups/EU", "European Union")
        uk = _country(
            "country/GBR",
            "United Kingdom",
            relations=[
                RelationRecord(
                    relation_type="member_of",
                    target_id="groups/EU",
                    valid_from="1973-01-01",
                    valid_until="2020-02-01",
                )
            ],
        )
        resolver = _make_resolver({"groups/EU": eu, "country/GBR": uk})

        result = resolver.related(uk, relation="member_of")

        assert len(result) == 1


# ---------------------------------------------------------------------------
# Unit: related() — to= pivot
# ---------------------------------------------------------------------------


class TestRelatedToPivot:
    def test_to_returns_code_strings(self) -> None:
        france = _country(
            "country/FRA",
            "France",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="region/EUR")
            ],
            codes=[CodeRecord(system="iso3", value="FRA", value_norm="fra")],
        )
        europe_with_code = EntityRecord(
            entity_id="region/EUR",
            entity_type="geo.region",
            canonical_name="Europe",
            canonical_name_norm="europe",
            codes=[CodeRecord(system="iso3", value="EUR", value_norm="eur")],
        )
        resolver = _make_resolver(
            {"region/EUR": europe_with_code, "country/FRA": france}
        )

        result = resolver.related(france, relation="contained_in", to="iso3")

        assert result == ["EUR"]

    def test_non_scalar_to_raises_unknown_code_system_error(self) -> None:
        france = _country("country/FRA", "France")
        resolver = _make_resolver({"country/FRA": france})

        with pytest.raises(UnknownCodeSystemError):
            resolver.related(france, to="aliases")

    def test_unknown_to_raises_unknown_code_system_error(self) -> None:
        france = _country("country/FRA", "France")
        resolver = _make_resolver({"country/FRA": france})

        with pytest.raises(UnknownCodeSystemError):
            resolver.related(france, to="no_such_system_xyz")

    def test_name_lang_pivot_returns_localized_names(self) -> None:
        # Europe has a French name; the region entity doesn't — expect [None].
        europe_fr = EntityRecord(
            entity_id="region/EUR",
            entity_type="geo.region",
            canonical_name="Europe",
            canonical_name_norm="europe",
            names=[
                NameRecord(
                    value="Europe",
                    value_norm="europe",
                    kind="canonical",
                    lang="en",
                    is_preferred=True,
                ),
                NameRecord(
                    value="Europe",
                    value_norm="europe",
                    kind="canonical",
                    lang="fr",
                    is_preferred=True,
                ),
            ],
        )
        other_region = EntityRecord(
            entity_id="region/OTH",
            entity_type="geo.region",
            canonical_name="Other",
            canonical_name_norm="other",
            # No French name record — pivot must return None, not raise.
        )
        france = _country(
            "country/FRA",
            "France",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="region/EUR"),
                RelationRecord(relation_type="contained_in", target_id="region/OTH"),
            ],
        )
        resolver = _make_resolver(
            {
                "region/EUR": europe_fr,
                "region/OTH": other_region,
                "country/FRA": france,
            }
        )

        result = resolver.related(france, relation="contained_in", to="name:fr")

        # region/EUR has a French name; region/OTH doesn't → None.
        assert result == ["Europe", None]

    def test_aliases_pivot_still_raises_unknown_code_system_error(self) -> None:
        france = _country("country/FRA", "France")
        resolver = _make_resolver({"country/FRA": france})

        with pytest.raises(UnknownCodeSystemError):
            resolver.related(france, to="aliases")

    def test_iso3_pivot_still_works_as_scalar(self) -> None:
        europe_with_code = EntityRecord(
            entity_id="region/EUR",
            entity_type="geo.region",
            canonical_name="Europe",
            canonical_name_norm="europe",
            codes=[CodeRecord(system="iso3", value="EUR", value_norm="eur")],
        )
        france = _country(
            "country/FRA",
            "France",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="region/EUR")
            ],
        )
        resolver = _make_resolver(
            {"region/EUR": europe_with_code, "country/FRA": france}
        )

        result = resolver.related(france, relation="contained_in", to="iso3")

        assert result == ["EUR"]


# ---------------------------------------------------------------------------
# Unit: related() — dedup
# ---------------------------------------------------------------------------


class TestRelatedDedup:
    def test_dedup_preserves_first_seen_edge_order(self) -> None:
        # Two edges that both resolve to the same entity_id — only first kept.
        europe = _region("region/EUR", "Europe")
        france = _country(
            "country/FRA",
            "France",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="region/EUR"),
                RelationRecord(relation_type="also_in", target_id="region/EUR"),
            ],
        )
        resolver = _make_resolver({"region/EUR": europe, "country/FRA": france})

        result = cast(list[EntityRecord], resolver.related(france))

        assert len(result) == 1
        assert result[0].entity_id == "region/EUR"


# ---------------------------------------------------------------------------
# Unit: unresolved_relations()
# ---------------------------------------------------------------------------


class TestUnresolvedRelations:
    def test_returns_dicts_for_dangling_targets(self) -> None:
        france = _country(
            "country/FRA",
            "France",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="WesternEurope"),
                RelationRecord(relation_type="contained_in", target_id="Earth"),
            ],
        )
        resolver = _make_resolver({"country/FRA": france})

        result = resolver.diagnostics.unresolved_relations(france)

        assert len(result) == 2
        target_ids = {d["target_id"] for d in result}
        assert target_ids == {"WesternEurope", "Earth"}
        # Each dict has the documented keys.
        for d in result:
            assert set(d.keys()) == {
                "relation_type",
                "target_id",
                "valid_from",
                "valid_until",
            }

    def test_excludes_resolvable_targets(self) -> None:
        europe = _region("region/EUR", "Europe")
        france = _country(
            "country/FRA",
            "France",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="region/EUR"),
                RelationRecord(relation_type="contained_in", target_id="WesternEurope"),
            ],
        )
        resolver = _make_resolver({"region/EUR": europe, "country/FRA": france})

        result = resolver.diagnostics.unresolved_relations(france)

        # Only the dangling edge is reported.
        assert len(result) == 1
        assert result[0]["target_id"] == "WesternEurope"

    def test_relation_filter_honored(self) -> None:
        france = _country(
            "country/FRA",
            "France",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="WesternEurope"),
                RelationRecord(relation_type="member_of", target_id="SomeMissingGroup"),
            ],
        )
        resolver = _make_resolver({"country/FRA": france})

        result = resolver.diagnostics.unresolved_relations(
            france, relation="contained_in"
        )

        assert len(result) == 1
        assert result[0]["relation_type"] == "contained_in"

    def test_closed_resolver_raises_runtime_error(self) -> None:
        france = _country("country/FRA", "France")
        resolver = _make_resolver({"country/FRA": france})
        resolver.close()

        with pytest.raises(RuntimeError, match="closed"):
            resolver.diagnostics.unresolved_relations(france)

    def test_no_as_of_filter_returns_expired_edges(self) -> None:
        # Expired edges (valid_until in the past) must be reported — no as_of filter.
        france = _country(
            "country/FRA",
            "France",
            relations=[
                RelationRecord(
                    relation_type="member_of",
                    target_id="MissingOldGroup",
                    valid_from="1950-01-01",
                    valid_until="1990-01-01",
                )
            ],
        )
        resolver = _make_resolver({"country/FRA": france})

        result = resolver.diagnostics.unresolved_relations(france)

        assert len(result) == 1
        assert result[0]["valid_until"] == "1990-01-01"

    def test_dict_keys_include_temporal_fields(self) -> None:
        france = _country(
            "country/FRA",
            "France",
            relations=[
                RelationRecord(
                    relation_type="contained_in",
                    target_id="WesternEurope",
                    valid_from="2000-01-01",
                    valid_until="2010-01-01",
                )
            ],
        )
        resolver = _make_resolver({"country/FRA": france})

        result = resolver.diagnostics.unresolved_relations(france)

        assert result[0]["valid_from"] == "2000-01-01"
        assert result[0]["valid_until"] == "2010-01-01"


# ---------------------------------------------------------------------------
# Guard: RelationRecord not in public __all__
# ---------------------------------------------------------------------------


def test_relation_record_not_in_public_all() -> None:
    assert "RelationRecord" not in resolvekit.__all__, (
        "RelationRecord must not appear in resolvekit.__all__ — "
        "it is an internal type not part of the stable public API"
    )
