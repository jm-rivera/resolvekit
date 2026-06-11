"""Tests for multi-pack pipeline runner."""

import pytest


class TestMultiPackRunner:
    """Tests for multi-pack resolution."""

    def test_routes_to_single_pack(self):
        from resolvekit.core.engine import ExplicitRouter
        from resolvekit.core.engine.multi_runner import MultiPackRunner
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            EntityRecord,
            NormalizedText,
            Query,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo import GeoPack

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                if entity_id == "country/USA":
                    return EntityRecord(
                        entity_id="country/USA",
                        entity_type="geo.country",
                        canonical_name="United States",
                        canonical_name_norm="united states",
                    )
                return None

            def lookup_code(self, system, value_norm):
                if system == "iso2" and value_norm == "us":
                    return ["country/USA"]
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {eid: e for eid in entity_ids if (e := self.get_entity(eid))}

        runner = MultiPackRunner(
            router=ExplicitRouter(available_packs=["geo"]),
            packs={"geo": GeoPack()},
            stores={"geo": MockStore()},
            trace_sink=NullTraceSink(),
        )

        query = Query(
            raw_text="US",
            normalized=NormalizedText(original="US", normalized="us"),
            domains={"geo"},
        )

        result = runner.resolve(query, ResolutionContext())

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "country/USA"

    def test_merges_results_from_multiple_packs(self):
        from resolvekit.core.engine import HybridRouter
        from resolvekit.core.engine.multi_runner import MultiPackRunner
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            EntityRecord,
            NormalizedText,
            Query,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo import GeoPack
        from resolvekit.packs.org import OrgPack

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                if entity_id == "org/EU":
                    return EntityRecord(
                        entity_id="org/EU",
                        entity_type="org.igo",
                        canonical_name="European Union",
                        canonical_name_norm="european union",
                    )
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                if value_norm == "eu" and name_kinds and "acronym" in name_kinds:
                    return ["org/EU"]
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {eid: e for eid in entity_ids if (e := self.get_entity(eid))}

        runner = MultiPackRunner(
            router=HybridRouter(packs=["geo", "org"]),
            packs={"geo": GeoPack(), "org": OrgPack()},
            stores={"geo": MockStore(), "org": MockStore()},
            trace_sink=NullTraceSink(),
        )

        query = Query(
            raw_text="EU",
            normalized=NormalizedText(original="EU", normalized="eu"),
        )

        result = runner.resolve(query, ResolutionContext())

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "org/EU"

    def test_handles_no_match_gracefully(self):
        from resolvekit.core.engine import ExplicitRouter
        from resolvekit.core.engine.multi_runner import MultiPackRunner
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            NormalizedText,
            Query,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo import GeoPack

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        runner = MultiPackRunner(
            router=ExplicitRouter(available_packs=["geo"]),
            packs={"geo": GeoPack()},
            stores={"geo": MockStore()},
            trace_sink=NullTraceSink(),
        )

        query = Query(
            raw_text="NonExistent",
            normalized=NormalizedText(original="NonExistent", normalized="nonexistent"),
            domains={"geo"},
        )

        result = runner.resolve(query, ResolutionContext())

        assert result.status == ResolutionStatus.NO_MATCH

    def test_raises_on_missing_store(self):
        from resolvekit.core.engine import ExplicitRouter
        from resolvekit.core.engine.multi_runner import MultiPackRunner
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.packs.geo import GeoPack

        with pytest.raises(ValueError, match="No store configured"):
            MultiPackRunner(
                router=ExplicitRouter(available_packs=["geo"]),
                packs={"geo": GeoPack()},
                stores={},  # Missing store for geo
                trace_sink=NullTraceSink(),
            )

    def test_pack_specific_normalization(self):
        """Test that pack-specific normalizers are applied per-pack."""
        from resolvekit.core.engine import HybridRouter
        from resolvekit.core.engine.multi_runner import MultiPackRunner
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            EntityRecord,
            NormalizedText,
            Query,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.core.util.normalization import (
            NormalizationProfile,
            TextNormalizer,
        )
        from resolvekit.packs.geo import GeoPack
        from resolvekit.packs.org import OrgPack

        # Track what normalized values are used for lookups
        lookup_calls = []

        class MockOrgStore(EntityStore):
            def get_entity(self, entity_id):
                if entity_id == "org/ATT":
                    return EntityRecord(
                        entity_id="org/ATT",
                        entity_type="org.company",
                        canonical_name="AT&T",
                        canonical_name_norm="att",  # Stored without punctuation
                    )
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                lookup_calls.append(("org", value_norm))
                # Only match if punctuation was stripped (org profile)
                if value_norm == "att":
                    return ["org/ATT"]
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {eid: e for eid in entity_ids if (e := self.get_entity(eid))}

        class MockGeoStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                lookup_calls.append(("geo", value_norm))
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        # Org normalizer strips punctuation
        org_profile = NormalizationProfile(strip_punctuation=True)
        # Geo normalizer preserves punctuation
        geo_profile = NormalizationProfile(strip_punctuation=False)

        runner = MultiPackRunner(
            router=HybridRouter(packs=["geo", "org"]),
            packs={"geo": GeoPack(), "org": OrgPack()},
            stores={"geo": MockGeoStore(), "org": MockOrgStore()},
            trace_sink=NullTraceSink(),
            pack_normalizers={
                "geo": TextNormalizer(geo_profile),
                "org": TextNormalizer(org_profile),
            },
        )

        query = Query(
            raw_text="AT&T",
            normalized=NormalizedText(original="AT&T", normalized="at&t"),
        )

        result = runner.resolve(query, ResolutionContext())

        # Verify org pack received query normalized without punctuation
        org_lookups = [v for pack, v in lookup_calls if pack == "org"]
        assert any("att" in v for v in org_lookups), f"Org lookups: {org_lookups}"

        # Verify geo pack received query with punctuation preserved
        geo_lookups = [v for pack, v in lookup_calls if pack == "geo"]
        assert any("at&t" in v for v in geo_lookups), f"Geo lookups: {geo_lookups}"

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "org/ATT"

    def test_tier_first_merge_prefers_exact_code_over_acronym(self):
        from resolvekit.core.engine import HybridRouter
        from resolvekit.core.engine.multi_runner import MultiPackRunner
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            EntityRecord,
            MatchTier,
            NormalizedText,
            Query,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo import GeoPack
        from resolvekit.packs.org import OrgPack

        class MockGeoStore(EntityStore):
            def get_entity(self, entity_id):
                if entity_id == "country/USA":
                    return EntityRecord(
                        entity_id="country/USA",
                        entity_type="geo.country",
                        canonical_name="United States",
                        canonical_name_norm="united states",
                    )
                return None

            def lookup_code(self, system, value_norm):
                if system == "iso2" and value_norm == "us":
                    return ["country/USA"]
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {eid: e for eid in entity_ids if (e := self.get_entity(eid))}

        class MockOrgStore(EntityStore):
            def get_entity(self, entity_id):
                if entity_id == "org/US_Fund":
                    return EntityRecord(
                        entity_id="org/US_Fund",
                        entity_type="org.fund",
                        canonical_name="US Development Fund",
                        canonical_name_norm="us development fund",
                    )
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                if value_norm == "us" and name_kinds and "acronym" in name_kinds:
                    return ["org/US_Fund"]
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {eid: e for eid in entity_ids if (e := self.get_entity(eid))}

        runner = MultiPackRunner(
            router=HybridRouter(packs=["geo", "org"]),
            packs={"geo": GeoPack(), "org": OrgPack()},
            stores={"geo": MockGeoStore(), "org": MockOrgStore()},
            trace_sink=NullTraceSink(),
        )

        query = Query(
            raw_text="US",
            normalized=NormalizedText(original="US", normalized="us"),
        )

        result = runner.resolve(query, ResolutionContext())

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "country/USA"
        assert result.pack_id == "geo"
        assert result.match_tier == MatchTier.EXACT_CODE

    def test_cross_pack_exact_name_collision_returns_type_hint(self):
        from resolvekit.core.engine import HybridRouter
        from resolvekit.core.engine.multi_runner import MultiPackRunner
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            EntityRecord,
            MatchTier,
            NormalizedText,
            Query,
            ReasonCode,
            RefinementHint,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo import GeoPack
        from resolvekit.packs.org import OrgPack

        class MockGeoStore(EntityStore):
            def get_entity(self, entity_id):
                if entity_id == "city/Paris":
                    return EntityRecord(
                        entity_id="city/Paris",
                        entity_type="geo.city",
                        canonical_name="Paris",
                        canonical_name_norm="paris",
                    )
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                if value_norm == "paris":
                    return ["city/Paris"]
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {eid: e for eid in entity_ids if (e := self.get_entity(eid))}

        class MockOrgStore(EntityStore):
            def get_entity(self, entity_id):
                if entity_id == "org/Paris":
                    return EntityRecord(
                        entity_id="org/Paris",
                        entity_type="org.agreement",
                        canonical_name="Paris",
                        canonical_name_norm="paris",
                    )
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                if value_norm == "paris" and name_kinds and "canonical" in name_kinds:
                    return ["org/Paris"]
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {eid: e for eid in entity_ids if (e := self.get_entity(eid))}

        runner = MultiPackRunner(
            router=HybridRouter(packs=["geo", "org"]),
            packs={"geo": GeoPack(), "org": OrgPack()},
            stores={"geo": MockGeoStore(), "org": MockOrgStore()},
            trace_sink=NullTraceSink(),
        )

        query = Query(
            raw_text="Paris",
            normalized=NormalizedText(original="Paris", normalized="paris"),
        )

        result = runner.resolve(query, ResolutionContext())

        assert result.status == ResolutionStatus.AMBIGUOUS
        assert result.match_tier == MatchTier.EXACT_NAME
        assert result.reasons == (ReasonCode.AMBIGUOUS_DOMAIN_COLLISION,)
        assert RefinementHint.ENTITY_TYPES in result.refinement_hints
        assert {candidate.pack_id for candidate in result.candidates} == {"geo", "org"}

    def test_multi_runner_forwards_pack_config_to_pipeline_runner(self):
        """MultiPackRunner passes pack.config to each PipelineRunner."""
        from unittest.mock import patch

        from resolvekit.core.engine import ExplicitRouter
        from resolvekit.core.engine.config import PipelineConfig, StopCondition
        from resolvekit.core.engine.multi_runner import MultiPackRunner
        from resolvekit.core.engine.runner import PipelineRunner
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo import GeoPack

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        config = PipelineConfig(
            stop_conditions=[
                StopCondition(
                    name="high_conf_stop", phase="generation", min_confidence=0.9
                ),
            ]
        )

        GeoPack()
        # Inject a config onto the pack via monkeypatching the property

        constructed_runners = []
        original_init = PipelineRunner.__init__

        def capturing_init(self_runner, *args, **kwargs):
            constructed_runners.append(kwargs.get("config"))
            original_init(self_runner, *args, **kwargs)

        with (
            patch.object(
                GeoPack, "config", new_callable=lambda: property(lambda self: config)
            ),
            patch.object(PipelineRunner, "__init__", capturing_init),
        ):
            MultiPackRunner(
                router=ExplicitRouter(available_packs=["geo"]),
                packs={"geo": GeoPack()},
                stores={"geo": MockStore()},
                trace_sink=NullTraceSink(),
            )

        assert len(constructed_runners) == 1
        assert constructed_runners[0] is config


class TestMultiPackRunnerApplyConfidenceThreshold:
    """Tests for MultiPackRunner.apply_confidence_threshold."""

    def _make_multi_runner_with_geo(self):
        from resolvekit.core.engine import ExplicitRouter
        from resolvekit.core.engine.multi_runner import MultiPackRunner
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import EntityRecord
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo import GeoPack

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return EntityRecord(
                    entity_id=entity_id,
                    entity_type="geo.country",
                    canonical_name="Test",
                    canonical_name_norm="test",
                )

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        return MultiPackRunner(
            router=ExplicitRouter(available_packs=["geo"]),
            packs={"geo": GeoPack()},
            stores={"geo": MockStore()},
            trace_sink=NullTraceSink(),
        )

    def test_returns_true_when_at_least_one_sub_runner_updates(self):
        """Returns True when at least one sub-runner has a ThresholdDecisionPolicy."""
        runner = self._make_multi_runner_with_geo()
        updated = runner.apply_confidence_threshold(threshold=0.6)
        assert updated is True

    def test_threshold_propagates_to_sub_runner_policy(self):
        """After calling apply_confidence_threshold, each sub-runner reflects the new value."""
        from resolvekit.core.engine.decision import ThresholdDecisionPolicy

        runner = self._make_multi_runner_with_geo()
        runner.apply_confidence_threshold(threshold=0.55)

        for sub_runner in runner._runners.values():
            policy = sub_runner._decision_policy
            if isinstance(policy, ThresholdDecisionPolicy):
                assert policy.confidence_threshold == pytest.approx(0.55)

    def test_kwargs_only_signature(self):
        """apply_confidence_threshold must be called with keyword argument."""
        runner = self._make_multi_runner_with_geo()
        with pytest.raises(TypeError):
            runner.apply_confidence_threshold(0.5)  # type: ignore[call-arg]

    def test_all_sub_runners_updated_with_two_threshold_policy_packs(self):
        """Real MultiPackRunner with two ThresholdDecisionPolicy packs: both must update.

        Regression test for the any()-over-generator short-circuit bug: previously
        only the first sub-runner (dict-insertion order) was updated; the rest were
        silently skipped.
        """
        from resolvekit.core.engine import HybridRouter
        from resolvekit.core.engine.decision import ThresholdDecisionPolicy
        from resolvekit.core.engine.multi_runner import MultiPackRunner
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo import GeoPack
        from resolvekit.packs.org import OrgPack

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        runner = MultiPackRunner(
            router=HybridRouter(packs=["geo", "org"]),
            packs={"geo": GeoPack(), "org": OrgPack()},
            stores={"geo": MockStore(), "org": MockStore()},
            trace_sink=NullTraceSink(),
        )

        # Both GeoPack and OrgPack use ThresholdDecisionPolicy subclasses; verify that.
        for pack_id, sub_runner in runner._runners.items():
            assert isinstance(sub_runner._decision_policy, ThresholdDecisionPolicy), (
                f"Pack '{pack_id}' decision_policy is not a ThresholdDecisionPolicy"
            )

        updated = runner.apply_confidence_threshold(threshold=0.75)

        assert updated is True
        for pack_id, sub_runner in runner._runners.items():
            policy = sub_runner._decision_policy
            assert isinstance(policy, ThresholdDecisionPolicy)
            assert policy.confidence_threshold == pytest.approx(0.75), (
                f"Pack '{pack_id}' threshold not updated (short-circuit regression)"
            )
