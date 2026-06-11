"""Contract tests for the ResolverBackend methods on PipelineRunner.

Verifies that each introspection method returns the correct type and that
``resolve_detailed`` returns a ``PipelineResult`` with a ``.candidates`` attribute.
All tests use a single-pack ``PipelineRunner`` constructed from ``MockEntityStore``.
"""

from __future__ import annotations

from datetime import date

import pytest

from resolvekit.core.engine.decision import ThresholdDecisionPolicy
from resolvekit.core.engine.interfaces import PipelineResult, ResolverBackend
from resolvekit.core.engine.runner import PipelineRunner
from resolvekit.core.model import EntityRecord, ResolutionContext, ResolutionResult
from tests.conftest import MockEntityStore, make_query

_DEFAULT_POLICY = ThresholdDecisionPolicy(
    confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
)


@pytest.fixture()
def snapshot_entity() -> EntityRecord:
    return EntityRecord(
        entity_id="group/SNAPSHOT",
        entity_type="org.group",
        canonical_name="Snapshot Group",
        canonical_name_norm="snapshot group",
        attributes={"snapshot": True},
    )


@pytest.fixture()
def normal_entity() -> EntityRecord:
    return EntityRecord(
        entity_id="country/USA",
        entity_type="geo.country",
        canonical_name="United States",
        canonical_name_norm="united states",
    )


@pytest.fixture()
def runner(
    snapshot_entity: EntityRecord, normal_entity: EntityRecord
) -> PipelineRunner:
    """Single-pack PipelineRunner with two entities and declared type/group frozensets."""
    store = MockEntityStore(
        entities={
            snapshot_entity.entity_id: snapshot_entity,
            normal_entity.entity_id: normal_entity,
        },
        names={"united states": [normal_entity.entity_id]},
    )
    return PipelineRunner(
        store=store,
        pack_id="geo",
        group_entity_types=frozenset({"org.group", "geo.region"}),
        type_prefixes=frozenset({"geo"}),
        decision_policy=_DEFAULT_POLICY,
    )


class TestBackendProtocolCompliance:
    """PipelineRunner satisfies the ResolverBackend Protocol."""

    def test_is_resolver_backend(self, runner: PipelineRunner) -> None:
        assert isinstance(runner, ResolverBackend)


class TestAvailableEntityTypes:
    """available_entity_types returns the stored type_prefixes frozenset."""

    def test_returns_frozenset(self, runner: PipelineRunner) -> None:
        result = runner.available_entity_types
        assert isinstance(result, frozenset)

    def test_contains_declared_prefix(self, runner: PipelineRunner) -> None:
        assert "geo" in runner.available_entity_types

    def test_empty_when_not_declared(self) -> None:
        r = PipelineRunner(
            store=MockEntityStore(), pack_id="geo", decision_policy=_DEFAULT_POLICY
        )
        assert runner_has_no_type_prefixes(r)


def runner_has_no_type_prefixes(r: PipelineRunner) -> bool:
    return r.available_entity_types == frozenset()


class TestAvailableCodeSystems:
    """available_code_systems proxies store.code_systems()."""

    def test_returns_frozenset(self, runner: PipelineRunner) -> None:
        assert isinstance(runner.available_code_systems, frozenset)

    def test_empty_on_no_store(self) -> None:
        r = PipelineRunner(decision_policy=_DEFAULT_POLICY)
        assert r.available_code_systems == frozenset()


class TestAvailableGroupTypes:
    """available_group_types returns the stored group_entity_types frozenset."""

    def test_returns_frozenset(self, runner: PipelineRunner) -> None:
        assert isinstance(runner.available_group_types, frozenset)

    def test_contains_declared_types(self, runner: PipelineRunner) -> None:
        assert "org.group" in runner.available_group_types
        assert "geo.region" in runner.available_group_types

    def test_empty_when_not_declared(self) -> None:
        r = PipelineRunner(
            store=MockEntityStore(), pack_id="geo", decision_policy=_DEFAULT_POLICY
        )
        assert r.available_group_types == frozenset()


class TestGetReverseRelations:
    """get_reverse_relations is kwargs-only and returns a list."""

    def test_returns_list(self, runner: PipelineRunner) -> None:
        result = runner.get_reverse_relations(
            entity_id="country/USA", relation_type="member_of"
        )
        assert isinstance(result, list)

    def test_accepts_as_of(self, runner: PipelineRunner) -> None:
        result = runner.get_reverse_relations(
            entity_id="country/USA",
            relation_type="member_of",
            as_of=date(2023, 1, 1),
        )
        assert isinstance(result, list)

    def test_empty_on_no_store(self) -> None:
        r = PipelineRunner(decision_policy=_DEFAULT_POLICY)
        result = r.get_reverse_relations(entity_id="x", relation_type="member_of")
        assert result == []


class TestGetRelationsAsOf:
    """get_relations_as_of is kwargs-only and returns a frozenset."""

    def test_returns_frozenset(self, runner: PipelineRunner) -> None:
        result = runner.get_relations_as_of(
            entity_id="country/USA",
            relation_type="member_of",
            as_of=date(2023, 1, 1),
        )
        assert isinstance(result, frozenset)

    def test_empty_on_no_store(self) -> None:
        r = PipelineRunner(decision_policy=_DEFAULT_POLICY)
        result = r.get_relations_as_of(
            entity_id="x", relation_type="member_of", as_of=date(2023, 1, 1)
        )
        assert result == frozenset()


class TestListEntitiesByType:
    """list_entities_by_type is kwargs-only and returns a list of EntityRecord."""

    def test_returns_list(self, runner: PipelineRunner) -> None:
        result = runner.list_entities_by_type(entity_type="geo.country")
        assert isinstance(result, list)

    def test_empty_on_no_store(self) -> None:
        r = PipelineRunner(decision_policy=_DEFAULT_POLICY)
        assert r.list_entities_by_type(entity_type="geo.country") == []


class TestGetPackGroupTypes:
    """get_pack_group_types is kwargs-only; matches pack_id to declared group types."""

    def test_returns_frozenset_for_matching_pack(self, runner: PipelineRunner) -> None:
        result = runner.get_pack_group_types(pack_id="geo")
        assert isinstance(result, frozenset)
        assert "org.group" in result

    def test_empty_for_wrong_pack(self, runner: PipelineRunner) -> None:
        result = runner.get_pack_group_types(pack_id="org")
        assert result == frozenset()

    def test_empty_when_no_pack_id(self) -> None:
        r = PipelineRunner(
            store=MockEntityStore(),
            group_entity_types=frozenset({"geo.region"}),
            decision_policy=_DEFAULT_POLICY,
        )
        result = r.get_pack_group_types(pack_id="geo")
        assert result == frozenset()


class TestIsSnapshotEntity:
    """is_snapshot_entity is kwargs-only; reads attributes['snapshot']."""

    def test_true_for_snapshot(self, runner: PipelineRunner) -> None:
        assert runner.is_snapshot_entity(entity_id="group/SNAPSHOT") is True

    def test_false_for_non_snapshot(self, runner: PipelineRunner) -> None:
        assert runner.is_snapshot_entity(entity_id="country/USA") is False

    def test_false_for_missing_entity(self, runner: PipelineRunner) -> None:
        assert runner.is_snapshot_entity(entity_id="no/such") is False

    def test_false_on_no_store(self) -> None:
        r = PipelineRunner(decision_policy=_DEFAULT_POLICY)
        assert r.is_snapshot_entity(entity_id="x") is False


class TestLookupPackId:
    """lookup_pack_id returns the configured pack_id."""

    def test_returns_pack_id(self, runner: PipelineRunner) -> None:
        assert runner.lookup_pack_id() == "geo"

    def test_returns_none_when_unset(self) -> None:
        r = PipelineRunner(decision_policy=_DEFAULT_POLICY)
        assert r.lookup_pack_id() is None


class TestLookupNameExact:
    """lookup_name_exact is kwargs-only and returns (pack_id, entity_id) pairs."""

    def test_returns_pairs(self, runner: PipelineRunner) -> None:
        result = runner.lookup_name_exact(value="united states")
        assert isinstance(result, list)
        assert result == [("geo", "country/USA")]

    def test_empty_on_no_match(self, runner: PipelineRunner) -> None:
        result = runner.lookup_name_exact(value="nowhere")
        assert result == []

    def test_pack_filter_matching(self, runner: PipelineRunner) -> None:
        result = runner.lookup_name_exact(
            value="united states", pack_filter=frozenset({"geo"})
        )
        assert result == [("geo", "country/USA")]

    def test_pack_filter_excluding(self, runner: PipelineRunner) -> None:
        result = runner.lookup_name_exact(
            value="united states", pack_filter=frozenset({"org"})
        )
        assert result == []

    def test_empty_on_no_store(self) -> None:
        r = PipelineRunner(pack_id="x", decision_policy=_DEFAULT_POLICY)
        assert r.lookup_name_exact(value="anything") == []

    def test_empty_on_no_pack_id(self) -> None:
        r = PipelineRunner(store=MockEntityStore(), decision_policy=_DEFAULT_POLICY)
        assert r.lookup_name_exact(value="anything") == []


class TestNormalizeCodeValue:
    """normalize_code_value is kwargs-only and returns a normalized str."""

    def test_returns_str(self, runner: PipelineRunner) -> None:
        result = runner.normalize_code_value("iso3", "FRA")
        assert isinstance(result, str)

    def test_casefolds_iso3(self, runner: PipelineRunner) -> None:
        assert runner.normalize_code_value("iso3", "FRA") == "fra"

    def test_accepts_pack_filter_kwarg(self, runner: PipelineRunner) -> None:
        result = runner.normalize_code_value(
            "iso3", "FRA", pack_filter=frozenset({"geo"})
        )
        assert isinstance(result, str)

    def test_unknown_system_strips_whitespace(self, runner: PipelineRunner) -> None:
        result = runner.normalize_code_value("unknown_system", " value ")
        assert result == "value"


class TestResolveMethods:
    """resolve returns ResolutionResult; resolve_detailed returns PipelineResult with candidates."""

    def test_resolve_returns_resolution_result(self, runner: PipelineRunner) -> None:
        query = make_query("united states")
        ctx = ResolutionContext()
        result = runner.resolve(query, ctx)
        assert isinstance(result, ResolutionResult)

    def test_resolve_detailed_returns_pipeline_result(
        self, runner: PipelineRunner
    ) -> None:
        query = make_query("united states")
        ctx = ResolutionContext()
        result = runner.resolve_detailed(query, ctx)
        assert isinstance(result, PipelineResult)
        # candidates attribute exists (may be None for no-match but must be present)
        assert hasattr(result, "candidates")

    def test_resolve_detailed_result_is_resolution_result(
        self, runner: PipelineRunner
    ) -> None:
        query = make_query("united states")
        ctx = ResolutionContext()
        pipeline_result = runner.resolve_detailed(query, ctx)
        assert isinstance(pipeline_result.result, ResolutionResult)

    def test_resolve_result_matches_resolve_detailed_result(
        self, runner: PipelineRunner
    ) -> None:
        """resolve() output is identical to resolve_detailed().result."""
        query = make_query("united states")
        ctx = ResolutionContext()
        simple = runner.resolve(query, ctx)
        detailed = runner.resolve_detailed(query, ctx)
        # Same status and entity_id — identical outcome
        assert simple.status == detailed.result.status
        assert simple.entity_id == detailed.result.entity_id


# ===========================================================================
# MultiPackRunner
# ===========================================================================


from resolvekit.core.engine.multi_runner import MultiPackRunner  # noqa: E402
from resolvekit.core.model import NormalizedText, Query  # noqa: E402


class _GeoStore(MockEntityStore):
    """Geo store with two countries and a snapshot group."""

    def __init__(self) -> None:
        entities = {
            "country/USA": EntityRecord(
                entity_id="country/USA",
                entity_type="geo.country",
                canonical_name="United States",
                canonical_name_norm="united states",
            ),
            "country/DEU": EntityRecord(
                entity_id="country/DEU",
                entity_type="geo.country",
                canonical_name="Germany",
                canonical_name_norm="germany",
            ),
            "geo.group/G7": EntityRecord(
                entity_id="geo.group/G7",
                entity_type="geo.group",
                canonical_name="G7",
                canonical_name_norm="g7",
                attributes={"snapshot": True},
            ),
        }
        names = {
            "united states": ["country/USA"],
            "germany": ["country/DEU"],
            "g7": ["geo.group/G7"],
        }
        codes = {("iso2", "us"): ["country/USA"]}
        super().__init__(entities=entities, codes=codes, names=names)

    def code_systems(self) -> frozenset[str]:
        return frozenset({"iso2", "iso3"})

    def get_reverse_relations(
        self, target_id: str, relation_type: str, *, as_of: date | None = None
    ) -> list[str]:
        if relation_type == "member_of" and target_id == "geo.group/G7":
            return ["country/USA", "country/DEU"]
        return []

    def get_relations_as_of(
        self, entity_id: str, relation_type: str, as_of: date
    ) -> list[str]:
        if entity_id == "country/USA" and relation_type == "member_of":
            return ["geo.group/G7"]
        return []

    def list_entities_by_type(self, entity_type: str) -> list[EntityRecord]:
        return [e for e in self._entities.values() if e.entity_type == entity_type]


class _OrgStore(MockEntityStore):
    """Org store with one organization."""

    def __init__(self) -> None:
        entities = {
            "org/WHO": EntityRecord(
                entity_id="org/WHO",
                entity_type="org.igo",
                canonical_name="World Health Organization",
                canonical_name_norm="world health organization",
            ),
        }
        names = {"world health organization": ["org/WHO"]}
        super().__init__(entities=entities, names=names)

    def code_systems(self) -> frozenset[str]:
        return frozenset({"lei"})

    def list_entities_by_type(self, entity_type: str) -> list[EntityRecord]:
        return [e for e in self._entities.values() if e.entity_type == entity_type]


@pytest.fixture()
def two_pack_runner() -> MultiPackRunner:
    from resolvekit.core.engine import HybridRouter
    from resolvekit.packs.geo import GeoPack
    from resolvekit.packs.org import OrgPack

    return MultiPackRunner(
        router=HybridRouter(packs=["geo", "org"]),
        packs={"geo": GeoPack(), "org": OrgPack()},
        stores={"geo": _GeoStore(), "org": _OrgStore()},
    )


class TestMultiPackRunnerBackendContract:
    """Each ResolverBackend method is correctly implemented on MultiPackRunner."""

    def test_available_entity_types_unions_packs(
        self, two_pack_runner: MultiPackRunner
    ) -> None:
        types = two_pack_runner.available_entity_types
        assert isinstance(types, frozenset)
        # geo declares "geo" prefix, org declares "org" prefix
        assert "geo" in types
        assert "org" in types

    def test_available_code_systems_unions_stores(
        self, two_pack_runner: MultiPackRunner
    ) -> None:
        systems = two_pack_runner.available_code_systems
        assert isinstance(systems, frozenset)
        assert "iso2" in systems
        assert "lei" in systems

    def test_available_group_types_unions_packs(
        self, two_pack_runner: MultiPackRunner
    ) -> None:
        group_types = two_pack_runner.available_group_types
        assert isinstance(group_types, frozenset)
        assert len(group_types) > 0

    def test_get_reverse_relations_returns_sorted_ids(
        self, two_pack_runner: MultiPackRunner
    ) -> None:
        members = two_pack_runner.get_reverse_relations(
            entity_id="geo.group/G7", relation_type="member_of"
        )
        assert isinstance(members, list)
        assert members == sorted(members), (
            "get_reverse_relations must return sorted IDs"
        )
        assert "country/USA" in members
        assert "country/DEU" in members

    def test_get_reverse_relations_with_as_of(
        self, two_pack_runner: MultiPackRunner
    ) -> None:
        members = two_pack_runner.get_reverse_relations(
            entity_id="geo.group/G7",
            relation_type="member_of",
            as_of=date(2024, 1, 1),
        )
        assert isinstance(members, list)

    def test_get_relations_as_of_returns_frozenset(
        self, two_pack_runner: MultiPackRunner
    ) -> None:
        result = two_pack_runner.get_relations_as_of(
            entity_id="country/USA",
            relation_type="member_of",
            as_of=date(2024, 1, 1),
        )
        assert isinstance(result, frozenset)

    def test_list_entities_by_type_fans_across_stores(
        self, two_pack_runner: MultiPackRunner
    ) -> None:
        countries = two_pack_runner.list_entities_by_type(entity_type="geo.country")
        assert isinstance(countries, list)
        country_ids = [e.entity_id for e in countries]
        assert "country/USA" in country_ids
        assert "country/DEU" in country_ids

    def test_list_entities_by_type_no_duplicates(
        self, two_pack_runner: MultiPackRunner
    ) -> None:
        all_entities = two_pack_runner.list_entities_by_type(entity_type="geo.country")
        entity_ids = [e.entity_id for e in all_entities]
        assert len(entity_ids) == len(set(entity_ids)), "No duplicate entity IDs"

    def test_get_pack_group_types_geo(self, two_pack_runner: MultiPackRunner) -> None:
        geo_types = two_pack_runner.get_pack_group_types(pack_id="geo")
        assert isinstance(geo_types, frozenset)

    def test_get_pack_group_types_org(self, two_pack_runner: MultiPackRunner) -> None:
        org_types = two_pack_runner.get_pack_group_types(pack_id="org")
        assert isinstance(org_types, frozenset)

    def test_get_pack_group_types_unknown_pack_returns_empty(
        self, two_pack_runner: MultiPackRunner
    ) -> None:
        unknown = two_pack_runner.get_pack_group_types(pack_id="nonexistent")
        assert unknown == frozenset()

    def test_is_snapshot_entity_true_for_snapshot(
        self, two_pack_runner: MultiPackRunner
    ) -> None:
        assert two_pack_runner.is_snapshot_entity(entity_id="geo.group/G7") is True

    def test_is_snapshot_entity_false_for_regular(
        self, two_pack_runner: MultiPackRunner
    ) -> None:
        assert two_pack_runner.is_snapshot_entity(entity_id="country/USA") is False

    def test_is_snapshot_entity_false_for_unknown(
        self, two_pack_runner: MultiPackRunner
    ) -> None:
        assert two_pack_runner.is_snapshot_entity(entity_id="country/UNKNOWN") is False

    def test_lookup_pack_id_returns_none(
        self, two_pack_runner: MultiPackRunner
    ) -> None:
        assert two_pack_runner.lookup_pack_id() is None

    def test_lookup_name_exact_returns_pack_entity_pairs(
        self, two_pack_runner: MultiPackRunner
    ) -> None:
        results = two_pack_runner.lookup_name_exact(value="united states")
        assert isinstance(results, list)
        assert all(isinstance(pair, tuple) and len(pair) == 2 for pair in results)
        pack_ids = [pair[0] for pair in results]
        entity_ids = [pair[1] for pair in results]
        assert "geo" in pack_ids
        assert "country/USA" in entity_ids

    def test_lookup_name_exact_with_pack_filter(
        self, two_pack_runner: MultiPackRunner
    ) -> None:
        all_results = two_pack_runner.lookup_name_exact(value="united states")
        filtered = two_pack_runner.lookup_name_exact(
            value="united states", pack_filter=frozenset({"geo"})
        )
        assert all(pack_id == "geo" for pack_id, _ in filtered)
        assert all(pair in all_results for pair in filtered)

    def test_lookup_name_exact_no_match_returns_empty(
        self, two_pack_runner: MultiPackRunner
    ) -> None:
        results = two_pack_runner.lookup_name_exact(value="zzz_no_such_entity_zzz")
        assert results == []


class TestMultiPackRunnerResolveSplit:
    """resolve() and resolve_detailed() split behavior."""

    def test_resolve_returns_resolution_result(
        self, two_pack_runner: MultiPackRunner
    ) -> None:
        from resolvekit.core.model import ResolutionResult

        query = Query(
            raw_text="US",
            normalized=NormalizedText(original="US", normalized="us"),
            domains={"geo"},
        )
        result = two_pack_runner.resolve(query, ResolutionContext())
        assert isinstance(result, ResolutionResult)

    def test_resolve_detailed_returns_pipeline_result(
        self, two_pack_runner: MultiPackRunner
    ) -> None:
        query = Query(
            raw_text="US",
            normalized=NormalizedText(original="US", normalized="us"),
            domains={"geo"},
        )
        pipeline = two_pack_runner.resolve_detailed(query, ResolutionContext())
        assert isinstance(pipeline, PipelineResult)
        assert hasattr(pipeline, "candidates")

    def test_resolve_result_matches_resolve_detailed_result(
        self, two_pack_runner: MultiPackRunner
    ) -> None:
        query = Query(
            raw_text="US",
            normalized=NormalizedText(original="US", normalized="us"),
            domains={"geo"},
        )
        ctx = ResolutionContext()
        plain = two_pack_runner.resolve(query, ctx)
        detailed = two_pack_runner.resolve_detailed(query, ctx)
        assert plain.status == detailed.result.status
        assert plain.entity_id == detailed.result.entity_id

    def test_resolve_kwargs_only(self, two_pack_runner: MultiPackRunner) -> None:
        """trace_sink and deadline are keyword-only."""
        import inspect

        sig = inspect.signature(two_pack_runner.resolve)
        kw_only = {
            p.name
            for p in sig.parameters.values()
            if p.kind == inspect.Parameter.KEYWORD_ONLY
        }
        assert "trace_sink" in kw_only
        assert "deadline" in kw_only


class TestMultiPackNormalizeCodeValue:
    """normalize_code_value on MultiPackRunner routes through domain normalizers."""

    def test_returns_str(self, two_pack_runner: MultiPackRunner) -> None:
        result = two_pack_runner.normalize_code_value("iso3", "FRA")
        assert isinstance(result, str)

    def test_geo_iso3_casefolds(self, two_pack_runner: MultiPackRunner) -> None:
        assert two_pack_runner.normalize_code_value("iso3", "FRA") == "fra"

    def test_accepts_pack_filter_kwarg(self, two_pack_runner: MultiPackRunner) -> None:
        result = two_pack_runner.normalize_code_value(
            "iso3", "FRA", pack_filter=frozenset({"geo"})
        )
        assert isinstance(result, str)

    def test_unknown_system_strips_whitespace(
        self, two_pack_runner: MultiPackRunner
    ) -> None:
        result = two_pack_runner.normalize_code_value("unknown_system", " value ")
        assert result == "value"
