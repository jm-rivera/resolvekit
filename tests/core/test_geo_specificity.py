"""Tests for M9 geo candidate re-ordering (specificity ranking)."""

from resolvekit.packs.geo._specificity import (
    _GEO_SPECIFICITY,
    geo_candidate_ordering_key,
)


class TestGeoSpecificityRanks:
    def test_specificity_ranks_known_types(self):
        assert geo_candidate_ordering_key("geo.country") == 0
        assert geo_candidate_ordering_key("geo.admin1") == 1
        assert geo_candidate_ordering_key("geo.region") == 2
        # geo.subregion (UN M.49 sub-regions) shares the geo.region tier:
        # both are aggregate types that rank below countries/admin1.
        assert geo_candidate_ordering_key("geo.subregion") == 2
        assert geo_candidate_ordering_key("geo.continental_union") == 3

    def test_country_ranks_before_region(self):
        country_rank = geo_candidate_ordering_key("geo.country")
        region_rank = geo_candidate_ordering_key("geo.region")
        assert country_rank is not None
        assert region_rank is not None
        assert country_rank < region_rank

    def test_unknown_entity_type_returns_none(self):
        # None signals "no opinion" to the runner, which treats it as lowest priority
        assert geo_candidate_ordering_key("geo.city") is None
        assert geo_candidate_ordering_key("org.ngo") is None
        assert geo_candidate_ordering_key("") is None
        assert geo_candidate_ordering_key("geo.unknown_subtype") is None

    def test_specificity_dict_completeness(self):
        # Known geo types map onto a contiguous rank range 0-4, with no gaps.
        # Ranks are not required to be unique: geo.region and geo.subregion
        # intentionally share rank 2 (same aggregate-specificity tier).
        ranks = set(_GEO_SPECIFICITY.values())
        assert sorted(ranks) == [0, 1, 2, 3, 4]


class TestOrgPackReturnsNoneOrdering:
    def test_org_pack_returns_none_ordering(self):
        from resolvekit.packs.org.pack import OrgPack

        pack = OrgPack()
        assert pack.candidate_ordering_key("org.ngo") is None
        assert pack.candidate_ordering_key("geo.country") is None
        assert pack.candidate_ordering_key("") is None


class TestRunnerReordering:
    """Integration tests for the M9 sort inside ResultEnricher._enrich_result_candidates."""

    def _make_runner(self, entities_by_id: dict, ordering_key=None):
        from resolvekit.core.engine.decision import ThresholdDecisionPolicy
        from resolvekit.core.engine.runner import PipelineRunner
        from resolvekit.core.explain import NullTraceSink
        from tests.conftest import MockEntityStore

        store = MockEntityStore(entities=entities_by_id)
        return PipelineRunner(
            trace_sink=NullTraceSink(),
            store=store,
            candidate_ordering_key=ordering_key,
            decision_policy=ThresholdDecisionPolicy(
                confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
            ),
        )

    def _make_summary(self, entity_id: str, confidence: float):
        from resolvekit.core.model.result import CandidateSummary

        return CandidateSummary(entity_id=entity_id, confidence=confidence)

    def _make_result(self, candidates):
        from resolvekit.core.model.result import (
            ReasonCode,
            ResolutionResult,
            ResolutionStatus,
        )

        return ResolutionResult(
            status=ResolutionStatus.AMBIGUOUS,
            candidates=candidates,
            reasons=[ReasonCode.AMBIGUOUS_LOW_GAP],
        )

    def test_runner_reorders_when_mixed_types_present(self):
        """Country precedes region when confidence is tied."""
        from resolvekit.core.model import EntityRecord

        entities = {
            "region/A": EntityRecord(
                entity_id="region/A",
                entity_type="geo.region",
                canonical_name="Region A",
                canonical_name_norm="region a",
            ),
            "country/B": EntityRecord(
                entity_id="country/B",
                entity_type="geo.country",
                canonical_name="Country B",
                canonical_name_norm="country b",
            ),
        }
        runner = self._make_runner(entities, geo_candidate_ordering_key)

        # Region appears first in raw candidates; tied confidence -> reorder fires
        candidates = [
            self._make_summary("region/A", 0.75),
            self._make_summary("country/B", 0.75),
        ]
        result = self._make_result(candidates)
        enriched = runner._enricher._enrich_result_candidates(result, entities, {})
        ordered_types = [c.entity_type for c in enriched.candidates]
        assert ordered_types == ["geo.country", "geo.region"]

    def test_runner_no_reorder_when_only_specific(self):
        """No reorder when all candidates are specific types (rank <= 1)."""
        from resolvekit.core.model import EntityRecord

        entities = {
            "country/A": EntityRecord(
                entity_id="country/A",
                entity_type="geo.country",
                canonical_name="Country A",
                canonical_name_norm="country a",
            ),
            "admin1/B": EntityRecord(
                entity_id="admin1/B",
                entity_type="geo.admin1",
                canonical_name="Admin B",
                canonical_name_norm="admin b",
            ),
        }
        runner = self._make_runner(entities, geo_candidate_ordering_key)

        candidates = [
            self._make_summary("admin1/B", 0.80),
            self._make_summary("country/A", 0.75),
        ]
        result = self._make_result(candidates)
        enriched = runner._enricher._enrich_result_candidates(result, entities, {})

        # No aggregating type present -> guard doesn't fire -> original order kept
        assert enriched.candidates[0].entity_id == "admin1/B"

    def test_runner_no_reorder_when_only_aggregating(self):
        """No reorder when all candidates are aggregating types only."""
        from resolvekit.core.model import EntityRecord

        entities = {
            "region/A": EntityRecord(
                entity_id="region/A",
                entity_type="geo.region",
                canonical_name="Region A",
                canonical_name_norm="region a",
            ),
            "continental_union/B": EntityRecord(
                entity_id="continental_union/B",
                entity_type="geo.continental_union",
                canonical_name="Union B",
                canonical_name_norm="union b",
            ),
        }
        runner = self._make_runner(entities, geo_candidate_ordering_key)

        candidates = [
            self._make_summary("continental_union/B", 0.70),
            self._make_summary("region/A", 0.75),
        ]
        result = self._make_result(candidates)
        enriched = runner._enricher._enrich_result_candidates(result, entities, {})

        # No specific type present -> guard doesn't fire -> original order kept
        assert enriched.candidates[0].entity_id == "continental_union/B"

    def test_runner_no_reorder_when_no_ordering_key(self):
        """When no candidate_ordering_key is set, order is unchanged."""
        from resolvekit.core.model import EntityRecord

        entities = {
            "region/A": EntityRecord(
                entity_id="region/A",
                entity_type="geo.region",
                canonical_name="Region A",
                canonical_name_norm="region a",
            ),
            "country/B": EntityRecord(
                entity_id="country/B",
                entity_type="geo.country",
                canonical_name="Country B",
                canonical_name_norm="country b",
            ),
        }
        runner = self._make_runner(entities, ordering_key=None)

        candidates = [
            self._make_summary("region/A", 0.75),
            self._make_summary("country/B", 0.75),
        ]
        result = self._make_result(candidates)
        enriched = runner._enricher._enrich_result_candidates(result, entities, {})

        # No ordering hook -> region remains first
        assert enriched.candidates[0].entity_id == "region/A"

    def test_runner_reorders_preserves_confidence_order_across_buckets(self):
        """Confidence difference dominates: higher-confidence region stays above
        lower-confidence country; lowest-confidence entity is always last."""
        from resolvekit.core.model import EntityRecord

        entities = {
            "region/X": EntityRecord(
                entity_id="region/X",
                entity_type="geo.region",
                canonical_name="Region X",
                canonical_name_norm="region x",
            ),
            "country/high": EntityRecord(
                entity_id="country/high",
                entity_type="geo.country",
                canonical_name="High Confidence Country",
                canonical_name_norm="high confidence country",
            ),
            "country/low": EntityRecord(
                entity_id="country/low",
                entity_type="geo.country",
                canonical_name="Low Confidence Country",
                canonical_name_norm="low confidence country",
            ),
        }
        runner = self._make_runner(entities, geo_candidate_ordering_key)

        # region/X (0.75) has higher confidence than country/high (0.74);
        # confidence buckets differ so specificity tie-break doesn't apply there.
        # country/low (0.60) must always sort last.
        candidates = [
            self._make_summary("region/X", 0.75),
            self._make_summary("country/high", 0.74),
            self._make_summary("country/low", 0.60),
        ]
        result = self._make_result(candidates)
        enriched = runner._enricher._enrich_result_candidates(result, entities, {})
        ordered_ids = [c.entity_id for c in enriched.candidates]

        assert ordered_ids[0] == "region/X"
        assert ordered_ids[-1] == "country/low"
