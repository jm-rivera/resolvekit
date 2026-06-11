"""Tests for Resolver.within().

Unit tests use MockEntityStore + PipelineRunner (no bundled data).
Integration tests marked @pytest.mark.integration require the bundled geo pack
with containment data.  They are skipped automatically if missing.
"""

from __future__ import annotations

from datetime import date
from typing import cast

import pytest

from resolvekit.core.api import Resolver
from resolvekit.core.engine import PipelineRunner
from resolvekit.core.engine.decision import ThresholdDecisionPolicy
from resolvekit.core.errors import (
    AmbiguousResolutionError,
    EntityNotFoundError,
    UnknownCodeSystemError,
)
from resolvekit.core.explain import NullTraceSink
from resolvekit.core.model import EntityRecord, RelationRecord
from resolvekit.core.model.entity import CodeRecord
from tests.conftest import MockEntityStore

_DEFAULT_POLICY = ThresholdDecisionPolicy(
    confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
)

# ---------------------------------------------------------------------------
# Module-level guard: check whether the bundled geo pack has containment data
# ---------------------------------------------------------------------------


def _geo_pack_has_containment() -> bool:
    """Return True iff the bundled geo pack contains geographic containment data."""
    try:
        from resolvekit import Resolver as PublicResolver

        r = PublicResolver.from_modules(
            module_ids=["geo.countries", "geo.regions", "geo.continents"]
        )
        try:
            results = r.within("Africa", entity_type="geo.country")
            return len(results) > 0
        finally:
            r.close()
    except Exception:
        return False


_GEO_PACK_HAS_CONTAINMENT = _geo_pack_has_containment()

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


def _region(
    entity_id: str,
    name: str,
    relations: list[RelationRecord] | None = None,
) -> EntityRecord:
    return EntityRecord(
        entity_id=entity_id,
        entity_type="geo.region",
        canonical_name=name,
        canonical_name_norm=name.lower(),
        relations=relations or [],
    )


def _subregion(
    entity_id: str,
    name: str,
    relations: list[RelationRecord] | None = None,
) -> EntityRecord:
    return EntityRecord(
        entity_id=entity_id,
        entity_type="geo.subregion",
        canonical_name=name,
        canonical_name_norm=name.lower(),
        relations=relations or [],
    )


# ---------------------------------------------------------------------------
# Unit: within() — one-hop (direct children)
# ---------------------------------------------------------------------------


class TestWithinOneHop:
    def test_one_hop_returns_direct_child(self) -> None:
        africa = _region("wikidataId/Q15", "Africa")
        east_africa = _region(
            "m49/014",
            "Eastern Africa",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="wikidataId/Q15")
            ],
        )
        resolver = _make_resolver(
            {"wikidataId/Q15": africa, "m49/014": east_africa},
            names={"africa": ["wikidataId/Q15"]},
        )

        result = cast(list[EntityRecord], resolver.within("Africa"))

        assert len(result) == 1
        assert result[0].entity_id == "m49/014"

    def test_one_hop_returns_multiple_direct_children(self) -> None:
        africa = _region("wikidataId/Q15", "Africa")
        north = _region(
            "m49/015",
            "Northern Africa",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="wikidataId/Q15")
            ],
        )
        sub = _region(
            "m49/202",
            "Sub-Saharan Africa",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="wikidataId/Q15")
            ],
        )
        resolver = _make_resolver(
            {"wikidataId/Q15": africa, "m49/015": north, "m49/202": sub},
            names={"africa": ["wikidataId/Q15"]},
        )

        result = cast(list[EntityRecord], resolver.within("Africa"))

        ids = {e.entity_id for e in result}
        assert ids == {"m49/015", "m49/202"}


# ---------------------------------------------------------------------------
# Unit: within() — recursive multi-hop
# ---------------------------------------------------------------------------


class TestWithinRecursive:
    def _make_africa_tree(self) -> tuple[Resolver, dict[str, EntityRecord]]:
        """Build a 3-level Africa → Sub-Saharan → Eastern Africa → country tree."""
        africa = _region("wikidataId/Q15", "Africa")
        sub_saharan = _region(
            "m49/202",
            "Sub-Saharan Africa",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="wikidataId/Q15")
            ],
        )
        east_africa = _region(
            "m49/014",
            "Eastern Africa",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="m49/202")
            ],
        )
        kenya = _country(
            "country/KEN",
            "Kenya",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="m49/014")
            ],
            codes=[CodeRecord(system="iso3", value="KEN", value_norm="ken")],
        )
        entities = {
            "wikidataId/Q15": africa,
            "m49/202": sub_saharan,
            "m49/014": east_africa,
            "country/KEN": kenya,
        }
        resolver = _make_resolver(entities, names={"africa": ["wikidataId/Q15"]})
        return resolver, entities

    def test_recursive_multi_hop_reaches_country(self) -> None:
        resolver, _ = self._make_africa_tree()

        result = cast(list[EntityRecord], resolver.within("Africa"))

        ids = {e.entity_id for e in result}
        assert "country/KEN" in ids
        assert "m49/202" in ids
        assert "m49/014" in ids
        # container itself must NOT be in results
        assert "wikidataId/Q15" not in ids

    def test_recursive_is_default(self) -> None:
        resolver, _ = self._make_africa_tree()

        result_default = cast(list[EntityRecord], resolver.within("Africa"))
        result_explicit = cast(
            list[EntityRecord], resolver.within("Africa", recursive=True)
        )

        assert {e.entity_id for e in result_default} == {
            e.entity_id for e in result_explicit
        }


# ---------------------------------------------------------------------------
# Unit: within() — entity_type filter
# ---------------------------------------------------------------------------


class TestWithinEntityTypeFilter:
    def test_entity_type_filter_excludes_intermediate_regions(self) -> None:
        """Intermediate regions are traversed but excluded from output when filtered."""
        africa = _region("wikidataId/Q15", "Africa")
        sub_saharan = _region(
            "m49/202",
            "Sub-Saharan Africa",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="wikidataId/Q15")
            ],
        )
        east_africa = _region(
            "m49/014",
            "Eastern Africa",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="m49/202")
            ],
        )
        kenya = _country(
            "country/KEN",
            "Kenya",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="m49/014")
            ],
        )
        resolver = _make_resolver(
            {
                "wikidataId/Q15": africa,
                "m49/202": sub_saharan,
                "m49/014": east_africa,
                "country/KEN": kenya,
            },
            names={"africa": ["wikidataId/Q15"]},
        )

        result = cast(
            list[EntityRecord],
            resolver.within("Africa", entity_type="geo.country"),
        )

        ids = {e.entity_id for e in result}
        # Only the country, not the intermediate regions
        assert ids == {"country/KEN"}

    def test_entity_type_list_input(self) -> None:
        africa = _region("wikidataId/Q15", "Africa")
        sub_saharan = _subregion(
            "m49/202",
            "Sub-Saharan Africa",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="wikidataId/Q15")
            ],
        )
        kenya = _country(
            "country/KEN",
            "Kenya",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="m49/202")
            ],
        )
        resolver = _make_resolver(
            {
                "wikidataId/Q15": africa,
                "m49/202": sub_saharan,
                "country/KEN": kenya,
            },
            names={"africa": ["wikidataId/Q15"]},
        )

        result = cast(
            list[EntityRecord],
            resolver.within("Africa", entity_type=["geo.country", "geo.subregion"]),
        )

        ids = {e.entity_id for e in result}
        # Both types returned
        assert "m49/202" in ids
        assert "country/KEN" in ids

    def test_entity_type_filter_selects_subregion(self) -> None:
        """within(entity_type="geo.subregion") returns M.49 sub-regions, not geo.region siblings."""
        africa = _region("wikidataId/Q15", "Africa")
        # Geographic M.49 sub-region (canonical)
        east_africa = _subregion(
            "m49/014",
            "Eastern Africa",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="wikidataId/Q15")
            ],
        )
        # Statistical aggregate (geo.region) sibling
        stat_group = _region(
            "undata-geo/G00014000",
            "Eastern Africa Statistical",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="wikidataId/Q15")
            ],
        )
        resolver = _make_resolver(
            {
                "wikidataId/Q15": africa,
                "m49/014": east_africa,
                "undata-geo/G00014000": stat_group,
            },
            names={"africa": ["wikidataId/Q15"]},
        )

        result = cast(
            list[EntityRecord],
            resolver.within("Africa", entity_type="geo.subregion"),
        )

        ids = {e.entity_id for e in result}
        # Only the geo.subregion node is returned
        assert "m49/014" in ids
        # The geo.region statistical sibling is excluded
        assert "undata-geo/G00014000" not in ids


# ---------------------------------------------------------------------------
# Unit: within() — recursive=False (direct children only)
# ---------------------------------------------------------------------------


class TestWithinNonRecursive:
    def test_recursive_false_returns_only_direct_children(self) -> None:
        africa = _region("wikidataId/Q15", "Africa")
        sub_saharan = _region(
            "m49/202",
            "Sub-Saharan Africa",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="wikidataId/Q15")
            ],
        )
        kenya = _country(
            "country/KEN",
            "Kenya",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="m49/202")
            ],
        )
        resolver = _make_resolver(
            {
                "wikidataId/Q15": africa,
                "m49/202": sub_saharan,
                "country/KEN": kenya,
            },
            names={"africa": ["wikidataId/Q15"]},
        )

        result = cast(list[EntityRecord], resolver.within("Africa", recursive=False))

        ids = {e.entity_id for e in result}
        # Only direct child — not the grandchild country
        assert ids == {"m49/202"}


# ---------------------------------------------------------------------------
# Unit: within() — max_depth bound
# ---------------------------------------------------------------------------


class TestWithinMaxDepth:
    def test_max_depth_one_matches_non_recursive(self) -> None:
        africa = _region("wikidataId/Q15", "Africa")
        sub_saharan = _region(
            "m49/202",
            "Sub-Saharan Africa",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="wikidataId/Q15")
            ],
        )
        east_africa = _region(
            "m49/014",
            "Eastern Africa",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="m49/202")
            ],
        )
        resolver = _make_resolver(
            {
                "wikidataId/Q15": africa,
                "m49/202": sub_saharan,
                "m49/014": east_africa,
            },
            names={"africa": ["wikidataId/Q15"]},
        )

        result_depth1 = cast(list[EntityRecord], resolver.within("Africa", max_depth=1))
        result_no_recurse = cast(
            list[EntityRecord], resolver.within("Africa", recursive=False)
        )

        assert {e.entity_id for e in result_depth1} == {
            e.entity_id for e in result_no_recurse
        }

    def test_max_depth_two_stops_at_second_hop(self) -> None:
        africa = _region("wikidataId/Q15", "Africa")
        sub_saharan = _region(
            "m49/202",
            "Sub-Saharan Africa",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="wikidataId/Q15")
            ],
        )
        east_africa = _region(
            "m49/014",
            "Eastern Africa",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="m49/202")
            ],
        )
        kenya = _country(
            "country/KEN",
            "Kenya",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="m49/014")
            ],
        )
        resolver = _make_resolver(
            {
                "wikidataId/Q15": africa,
                "m49/202": sub_saharan,
                "m49/014": east_africa,
                "country/KEN": kenya,
            },
            names={"africa": ["wikidataId/Q15"]},
        )

        result = cast(list[EntityRecord], resolver.within("Africa", max_depth=2))

        ids = {e.entity_id for e in result}
        assert "m49/202" in ids
        assert "m49/014" in ids
        # Country is at depth 3 — excluded by max_depth=2
        assert "country/KEN" not in ids


# ---------------------------------------------------------------------------
# Unit: within() — DAG dedup (diamond paths)
# ---------------------------------------------------------------------------


class TestWithinDagDedup:
    def test_child_reachable_via_two_paths_returned_once(self) -> None:
        """Americas → LAC → South America → country, AND Americas → continent → country.

        Kenya is reachable via two paths: Americas → region_a → KEN and
        Americas → region_b → KEN.  Must appear once in results.
        """
        americas = _region("wikidataId/Q828", "Americas")
        region_a = _region(
            "m49/region_a",
            "Region A",
            relations=[
                RelationRecord(
                    relation_type="contained_in", target_id="wikidataId/Q828"
                )
            ],
        )
        region_b = _region(
            "m49/region_b",
            "Region B",
            relations=[
                RelationRecord(
                    relation_type="contained_in", target_id="wikidataId/Q828"
                )
            ],
        )
        # Country reachable from both region_a and region_b
        country_x = _country(
            "country/XXX",
            "Country X",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="m49/region_a"),
                RelationRecord(relation_type="contained_in", target_id="m49/region_b"),
            ],
        )
        resolver = _make_resolver(
            {
                "wikidataId/Q828": americas,
                "m49/region_a": region_a,
                "m49/region_b": region_b,
                "country/XXX": country_x,
            },
            names={"americas": ["wikidataId/Q828"]},
        )

        result = cast(list[EntityRecord], resolver.within("Americas"))

        ids = [e.entity_id for e in result]
        assert ids.count("country/XXX") == 1


# ---------------------------------------------------------------------------
# Unit: within() — to= pivot
# ---------------------------------------------------------------------------


class TestWithinToPivot:
    def test_to_iso3_with_entity_type_filter(self) -> None:
        africa = _region("wikidataId/Q15", "Africa")
        east_africa = _region(
            "m49/014",
            "Eastern Africa",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="wikidataId/Q15")
            ],
        )
        kenya = _country(
            "country/KEN",
            "Kenya",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="m49/014")
            ],
            codes=[CodeRecord(system="iso3", value="KEN", value_norm="ken")],
        )
        resolver = _make_resolver(
            {
                "wikidataId/Q15": africa,
                "m49/014": east_africa,
                "country/KEN": kenya,
            },
            names={"africa": ["wikidataId/Q15"]},
        )

        result = resolver.within("Africa", entity_type="geo.country", to="iso3")

        assert result == ["KEN"]

    def test_to_returns_none_for_missing_code(self) -> None:
        africa = _region("wikidataId/Q15", "Africa")
        # Country has no iso3 code
        country_no_code = _country(
            "country/ZZZ",
            "Nowhere",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="wikidataId/Q15")
            ],
        )
        resolver = _make_resolver(
            {"wikidataId/Q15": africa, "country/ZZZ": country_no_code},
            names={"africa": ["wikidataId/Q15"]},
        )

        result = resolver.within("Africa", to="iso3")

        assert result == [None]


# ---------------------------------------------------------------------------
# Unit: within() — error cases
# ---------------------------------------------------------------------------


class TestWithinErrorCases:
    def test_unknown_to_raises_unknown_code_system_error(self) -> None:
        africa = _region("wikidataId/Q15", "Africa")
        resolver = _make_resolver(
            {"wikidataId/Q15": africa},
            names={"africa": ["wikidataId/Q15"]},
        )

        with pytest.raises(UnknownCodeSystemError):
            resolver.within("Africa", to="no_such_system_xyz")

    def test_non_scalar_to_raises_unknown_code_system_error(self) -> None:
        africa = _region("wikidataId/Q15", "Africa")
        resolver = _make_resolver(
            {"wikidataId/Q15": africa},
            names={"africa": ["wikidataId/Q15"]},
        )

        with pytest.raises(UnknownCodeSystemError):
            resolver.within("Africa", to="aliases")

    def test_unknown_container_raises_entity_not_found_error(self) -> None:
        resolver = _make_resolver({})

        with pytest.raises(EntityNotFoundError):
            resolver.within("NoSuchRegionXYZ")

    def test_ambiguous_container_raises_ambiguous_resolution_error(self) -> None:
        entity_a = _region("region/A", "Ambiguous")
        entity_b = _region("region/B", "Ambiguous")
        resolver = _make_resolver(
            {"region/A": entity_a, "region/B": entity_b},
            names={"ambiguous": ["region/A", "region/B"]},
        )

        with pytest.raises(AmbiguousResolutionError):
            resolver.within("Ambiguous")

    def test_geo_hierarchy_preference_picks_m49_node(self) -> None:
        """When a name matches a geo.subregion m49/* node and a geo.region twin, within() picks the subregion."""
        # m49 canonical sub-region node (geo.subregion after promotion)
        m49_region = _subregion(
            "m49/155",
            "Western Europe",
            relations=[],
        )
        # Non-canonical statistical aggregate with the same name
        oecd_region = EntityRecord(
            entity_id="undata-geo/G00130000",
            entity_type="geo.region",
            canonical_name="Western Europe",
            canonical_name_norm="western europe",
            relations=[],
        )
        child = _country(
            "country/DEU",
            "Germany",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="m49/155")
            ],
        )
        resolver = _make_resolver(
            {
                "m49/155": m49_region,
                "undata-geo/G00130000": oecd_region,
                "country/DEU": child,
            },
            names={"western europe": ["m49/155", "undata-geo/G00130000"]},
        )

        # Should resolve to the m49 node without raising AmbiguousResolutionError
        result = cast(list[EntityRecord], resolver.within("Western Europe"))
        ids = {e.entity_id for e in result}
        # Germany is a child of the m49 node — it should be in results
        assert "country/DEU" in ids

    def test_geo_hierarchy_preference_picks_continent_type(self) -> None:
        """When a name matches a geo.continent entity and another entity, within() picks the continent."""
        continent = EntityRecord(
            entity_id="wikidataId/Q828",
            entity_type="geo.continent",
            canonical_name="Americas",
            canonical_name_norm="americas",
            relations=[],
        )
        stat_region = EntityRecord(
            entity_id="undata-geo/G00134000",
            entity_type="geo.region",
            canonical_name="Americas",
            canonical_name_norm="americas",
            relations=[],
        )
        child = _country(
            "country/CAN",
            "Canada",
            relations=[
                RelationRecord(
                    relation_type="contained_in", target_id="wikidataId/Q828"
                )
            ],
        )
        resolver = _make_resolver(
            {
                "wikidataId/Q828": continent,
                "undata-geo/G00134000": stat_region,
                "country/CAN": child,
            },
            names={"americas": ["wikidataId/Q828", "undata-geo/G00134000"]},
        )

        result = cast(list[EntityRecord], resolver.within("Americas"))
        ids = {e.entity_id for e in result}
        assert "country/CAN" in ids

    def test_ambiguous_among_non_geo_nodes_still_raises(self) -> None:
        """Two non-canonical same-name entities (no m49/*, no geo.continent) → still raises."""
        entity_a = EntityRecord(
            entity_id="undata-geo/A",
            entity_type="geo.region",
            canonical_name="Duplicate",
            canonical_name_norm="duplicate",
            relations=[],
        )
        entity_b = EntityRecord(
            entity_id="undata-geo/B",
            entity_type="geo.region",
            canonical_name="Duplicate",
            canonical_name_norm="duplicate",
            relations=[],
        )
        resolver = _make_resolver(
            {"undata-geo/A": entity_a, "undata-geo/B": entity_b},
            names={"duplicate": ["undata-geo/A", "undata-geo/B"]},
        )

        with pytest.raises(AmbiguousResolutionError):
            resolver.within("Duplicate")

    def test_entity_type_region_excludes_subregion(self) -> None:
        """entity_type="geo.region" does NOT return geo.subregion nodes."""
        africa = _region("wikidataId/Q15", "Africa")
        # geo.subregion node (the M.49 canonical node after promotion)
        sub_saharan_sub = _subregion(
            "m49/202",
            "Sub-Saharan Africa",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="wikidataId/Q15")
            ],
        )
        # True geo.region statistical aggregate sibling
        stat_agg = _region(
            "undata-geo/G00202000",
            "Statistical Sub-Saharan",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="wikidataId/Q15")
            ],
        )
        resolver = _make_resolver(
            {
                "wikidataId/Q15": africa,
                "m49/202": sub_saharan_sub,
                "undata-geo/G00202000": stat_agg,
            },
            names={"africa": ["wikidataId/Q15"]},
        )

        result = cast(
            list[EntityRecord],
            resolver.within("Africa", entity_type="geo.region"),
        )

        ids = {e.entity_id for e in result}
        # geo.subregion node must NOT be returned when filtering for geo.region
        assert "m49/202" not in ids
        # The true geo.region statistical aggregate is returned
        assert "undata-geo/G00202000" in ids

    def test_geo_hierarchy_preference_picks_subregion_type(self) -> None:
        """A non-m49/ entity_id with entity_type=geo.subregion is recognized as a hierarchy node."""
        # Canonical sub-region: non-m49/ id, typed geo.subregion
        canonical_sub = _subregion(
            "canonical/western_europe",
            "Western Europe",
            relations=[],
        )
        # Same-named statistical aggregate typed geo.region
        stat_twin = _region(
            "undata-geo/G00130000",
            "Western Europe",
            relations=[],
        )
        child = _country(
            "country/DEU",
            "Germany",
            relations=[
                RelationRecord(
                    relation_type="contained_in", target_id="canonical/western_europe"
                )
            ],
        )
        resolver = _make_resolver(
            {
                "canonical/western_europe": canonical_sub,
                "undata-geo/G00130000": stat_twin,
                "country/DEU": child,
            },
            names={
                "western europe": ["canonical/western_europe", "undata-geo/G00130000"]
            },
        )

        # Must resolve without AmbiguousResolutionError — type is the sole criterion
        result = cast(list[EntityRecord], resolver.within("Western Europe"))
        ids = {e.entity_id for e in result}
        assert "country/DEU" in ids

    def test_empty_containment_returns_empty_list(self) -> None:
        africa = _region("wikidataId/Q15", "Africa")
        resolver = _make_resolver(
            {"wikidataId/Q15": africa},
            names={"africa": ["wikidataId/Q15"]},
        )

        result = resolver.within("Africa")

        assert result == []

    def test_closed_resolver_raises_runtime_error(self) -> None:
        africa = _region("wikidataId/Q15", "Africa")
        resolver = _make_resolver(
            {"wikidataId/Q15": africa},
            names={"africa": ["wikidataId/Q15"]},
        )
        resolver.close()

        with pytest.raises(RuntimeError, match="closed"):
            resolver.within("Africa")


# ---------------------------------------------------------------------------
# Unit: within() — container not surfaced (C8)
# ---------------------------------------------------------------------------


class TestWithinContainerNotSurfaced:
    def test_back_edge_does_not_surface_container(self) -> None:
        """A child with a back-edge pointing to the container must NOT include
        the container in results.  The visited set is seeded with the container
        to prevent this (back-edge deduplication).
        """
        africa = _region("wikidataId/Q15", "Africa")
        # Child has a back-edge pointing at the container (cycle / back-ref)
        weird_child = _region(
            "m49/weird",
            "Weird Region",
            relations=[
                RelationRecord(
                    relation_type="contained_in", target_id="wikidataId/Q15"
                ),
                # back-edge: also contained_in itself (simulates a back-pointer)
                RelationRecord(
                    relation_type="contained_in", target_id="wikidataId/Q15"
                ),
            ],
        )
        resolver = _make_resolver(
            {"wikidataId/Q15": africa, "m49/weird": weird_child},
            names={"africa": ["wikidataId/Q15"]},
        )

        result = cast(list[EntityRecord], resolver.within("Africa"))

        ids = {e.entity_id for e in result}
        # Container itself must never appear in results
        assert "wikidataId/Q15" not in ids
        # The child itself should appear
        assert "m49/weird" in ids

    def test_container_with_self_referential_child_excluded(self) -> None:
        """Container is excluded even when a descendant has a back-edge to it."""
        container = _region("container/ROOT", "Root")
        # child_a points to container AND is a child itself
        child_a = _region(
            "child/A",
            "Child A",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="container/ROOT")
            ],
        )
        # grandchild has back-edge to the root container
        grandchild = _region(
            "child/B",
            "Child B (grandchild with back-edge)",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="child/A"),
                RelationRecord(
                    relation_type="contained_in", target_id="container/ROOT"
                ),
            ],
        )
        resolver = _make_resolver(
            {
                "container/ROOT": container,
                "child/A": child_a,
                "child/B": grandchild,
            },
            names={"root": ["container/ROOT"]},
        )

        result = cast(list[EntityRecord], resolver.within("Root"))

        ids = {e.entity_id for e in result}
        assert "container/ROOT" not in ids
        assert "child/A" in ids
        assert "child/B" in ids


# ---------------------------------------------------------------------------
# Unit: within() — as_of temporal filter
# ---------------------------------------------------------------------------


class TestWithinAsOf:
    def test_as_of_none_returns_all_edges(self) -> None:
        africa = _region("wikidataId/Q15", "Africa")
        # Expired containment edge
        old_child = _region(
            "m49/old",
            "Old Region",
            relations=[
                RelationRecord(
                    relation_type="contained_in",
                    target_id="wikidataId/Q15",
                    valid_from="1950-01-01",
                    valid_until="1990-01-01",
                )
            ],
        )
        resolver = _make_resolver(
            {"wikidataId/Q15": africa, "m49/old": old_child},
            names={"africa": ["wikidataId/Q15"]},
        )

        # as_of=None returns all edges including expired ones
        result = cast(list[EntityRecord], resolver.within("Africa", as_of=None))

        assert any(e.entity_id == "m49/old" for e in result)

    def test_as_of_date_filters_out_expired_edge(self) -> None:
        africa = _region("wikidataId/Q15", "Africa")
        old_child = _region(
            "m49/old",
            "Old Region",
            relations=[
                RelationRecord(
                    relation_type="contained_in",
                    target_id="wikidataId/Q15",
                    valid_from="1950-01-01",
                    valid_until="1990-01-01",
                )
            ],
        )
        resolver = _make_resolver(
            {"wikidataId/Q15": africa, "m49/old": old_child},
            names={"africa": ["wikidataId/Q15"]},
        )

        result = resolver.within("Africa", as_of=date(2025, 1, 1))

        assert result == []


# ---------------------------------------------------------------------------
# Integration tests (gated — skip if containment data not available)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def geo_containment_resolver():  # type: ignore[no-untyped-def]
    from resolvekit import Resolver as PublicResolver

    r = PublicResolver.from_modules(
        module_ids=["geo.countries", "geo.regions", "geo.continents"]
    )
    yield r
    r.close()


@pytest.mark.skipif(
    not _GEO_PACK_HAS_CONTAINMENT,
    reason="geo pack does not include containment data",
)
@pytest.mark.integration
def test_within_africa_countries_iso3(geo_containment_resolver) -> None:  # type: ignore[no-untyped-def]
    """Africa contains approximately 54 countries (ISO3 pivot)."""
    result = geo_containment_resolver.within(
        "Africa", entity_type="geo.country", to="iso3"
    )
    assert isinstance(result, list)
    codes = [c for c in result if c is not None]
    assert len(codes) >= 50, f"Expected ~54 African countries, got {len(codes)}"


@pytest.mark.skipif(
    not _GEO_PACK_HAS_CONTAINMENT,
    reason="geo pack does not include containment data",
)
@pytest.mark.integration
def test_within_europe_records(geo_containment_resolver) -> None:  # type: ignore[no-untyped-def]
    """Europe within returns EntityRecords (no to= pivot)."""
    result = cast(
        list[EntityRecord],
        geo_containment_resolver.within("Europe", entity_type="geo.country"),
    )
    assert len(result) > 0
    assert all(isinstance(e, EntityRecord) for e in result)
    assert all(e.entity_type == "geo.country" for e in result)


@pytest.mark.skipif(
    not _GEO_PACK_HAS_CONTAINMENT,
    reason="geo pack does not include containment data",
)
@pytest.mark.integration
def test_within_eastern_africa_multihop(geo_containment_resolver) -> None:  # type: ignore[no-untyped-def]
    """Eastern Africa (minted m49 sub-region) resolves and returns countries via multi-hop."""
    result = geo_containment_resolver.within(
        "Eastern Africa", entity_type="geo.country", to="iso3"
    )
    codes = [c for c in result if c is not None]
    # Eastern Africa has ~20 countries (Kenya, Tanzania, Uganda, etc.)
    assert len(codes) > 5, f"Expected >5 Eastern African countries, got {len(codes)}"
    assert "KEN" in codes


@pytest.mark.skipif(
    not _GEO_PACK_HAS_CONTAINMENT,
    reason="geo pack does not include containment data",
)
@pytest.mark.integration
def test_within_americas_dedup(geo_containment_resolver) -> None:  # type: ignore[no-untyped-def]
    """Americas: countries reachable via multiple paths are returned exactly once."""
    result = cast(
        list[EntityRecord],
        geo_containment_resolver.within("Americas", entity_type="geo.country"),
    )
    entity_ids = [e.entity_id for e in result]
    # No duplicates
    assert len(entity_ids) == len(set(entity_ids)), (
        "Duplicate entities returned from within(Americas)"
    )
    assert len(result) > 0


@pytest.mark.skipif(
    not _GEO_PACK_HAS_CONTAINMENT,
    reason="geo pack does not include containment data",
)
@pytest.mark.integration
def test_within_south_america(geo_containment_resolver) -> None:  # type: ignore[no-untyped-def]
    """South America (continent Q18, reuse edge) returns non-empty country set."""
    result = geo_containment_resolver.within(
        "South America", entity_type="geo.country", to="iso3"
    )
    codes = [c for c in result if c is not None]
    assert len(codes) > 0, (
        "within('South America') returned no countries; reuse edge may be missing"
    )
    # Brazil must be there
    assert "BRA" in codes


# ---------------------------------------------------------------------------
# Integration: geo-hierarchy disambiguation (m49 vs undata statistical twins)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _GEO_PACK_HAS_CONTAINMENT,
    reason="geo pack does not include containment data",
)
@pytest.mark.integration
def test_within_western_europe_prefers_m49(geo_containment_resolver) -> None:  # type: ignore[no-untyped-def]
    """Western Europe resolves to the m49/155 node (not the undata twin) and returns countries."""
    result = geo_containment_resolver.within(
        "Western Europe", entity_type="geo.country", to="iso3"
    )
    codes = [c for c in result if c is not None]
    assert len(codes) > 0, "within('Western Europe') returned no countries"
    # Germany and France are canonical Western Europe members
    assert "DEU" in codes or "FRA" in codes, (
        f"Expected DEU or FRA in Western Europe, got {codes!r}"
    )


@pytest.mark.skipif(
    not _GEO_PACK_HAS_CONTAINMENT,
    reason="geo pack does not include containment data",
)
@pytest.mark.integration
def test_within_northern_africa_prefers_m49(geo_containment_resolver) -> None:  # type: ignore[no-untyped-def]
    """Northern Africa resolves to the m49 node (not undata twin) and returns countries."""
    result = geo_containment_resolver.within(
        "Northern Africa", entity_type="geo.country", to="iso3"
    )
    codes = [c for c in result if c is not None]
    assert len(codes) > 0, "within('Northern Africa') returned no countries"
    # Egypt and Morocco are Northern Africa members
    assert any(c in codes for c in ("EGY", "MAR")), (
        f"Expected EGY or MAR in Northern Africa, got {codes!r}"
    )


@pytest.mark.skipif(
    not _GEO_PACK_HAS_CONTAINMENT,
    reason="geo pack does not include containment data",
)
@pytest.mark.integration
def test_within_central_africa_prefers_m49(geo_containment_resolver) -> None:  # type: ignore[no-untyped-def]
    """Central Africa resolves to the m49 node (not undata twin) and returns countries."""
    result = geo_containment_resolver.within(
        "Central Africa", entity_type="geo.country", to="iso3"
    )
    codes = [c for c in result if c is not None]
    assert len(codes) > 0, "within('Central Africa') returned no countries"


@pytest.mark.skipif(
    not _GEO_PACK_HAS_CONTAINMENT,
    reason="geo pack does not include containment data",
)
@pytest.mark.integration
def test_within_europe_subregion_filter(geo_containment_resolver) -> None:  # type: ignore[no-untyped-def]
    """within("Europe", entity_type="geo.subregion") returns sub-regions including m49/155 (Western Europe)."""
    result = cast(
        list[EntityRecord],
        geo_containment_resolver.within("Europe", entity_type="geo.subregion"),
    )
    ids = {e.entity_id for e in result}
    assert len(ids) >= 1, f"Expected at least one geo.subregion in Europe, got {ids!r}"
    assert "m49/155" in ids, (
        f"Expected m49/155 (Western Europe) in geo.subregion results for Europe, got {ids!r}"
    )
    assert all(e.entity_type == "geo.subregion" for e in result), (
        "All returned entities should have entity_type='geo.subregion'"
    )
