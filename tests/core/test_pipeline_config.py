"""Tests for pipeline config and stop conditions."""


def test_stop_condition_model():
    from resolvekit.core.engine.config import PipelineConfig, StopCondition

    stop = StopCondition(
        name="exact_code_single",
        source_name="geo_exact_code",
        min_candidates=1,
        max_candidates=1,
    )
    config = PipelineConfig(stop_conditions=[stop])

    assert config.stop_conditions[0].source_name == "geo_exact_code"


def test_runner_honors_stop_condition():
    from resolvekit.core.engine.config import PipelineConfig, StopCondition
    from resolvekit.core.engine.interfaces import CandidateSource
    from resolvekit.core.engine.runner import PipelineRunner
    from resolvekit.core.explain import NullTraceSink
    from resolvekit.core.model import (
        CandidateEvidence,
        GenerationContext,
        NormalizedText,
        Query,
        ResolutionContext,
        ResolutionStatus,
    )
    from resolvekit.core.store import EntityStore

    class MockStore(EntityStore):
        def get_entity(self, entity_id):
            return None

        def lookup_code(self, system, value_norm):
            return ["country/USA"] if value_norm == "us" else []

        def lookup_name_exact(self, value_norm, name_kinds=None):
            return []

        def search_fulltext(self, query_norm, fields=None, limit=10):
            return []

        def bulk_get_entities(self, entity_ids):
            return {}

    class ExactCodeSource(CandidateSource):
        @property
        def name(self):
            return "geo_exact_code"

        def supports(self, domain_pack_id: str):
            return True

        def generate(self, ctx: GenerationContext):
            return [
                CandidateEvidence(
                    entity_id="country/USA",
                    source_name=self.name,
                    raw_score=1.0,
                    rank=1,
                    matched_field="code.iso2",
                    matched_value="US",
                )
            ]

    class FTSSource(CandidateSource):
        @property
        def name(self):
            return "geo_fts"

        def supports(self, domain_pack_id: str):
            return True

        def generate(self, ctx: GenerationContext):
            # Should not be called if stop condition triggers
            raise AssertionError("FTS should not run when stop condition is met")

    config = PipelineConfig(
        stop_conditions=[
            StopCondition(
                name="exact_code_single",
                source_name="geo_exact_code",
                min_candidates=1,
                max_candidates=1,
                phase="generation",  # Stop during candidate generation
            )
        ],
    )

    from resolvekit.core.engine.decision import ThresholdDecisionPolicy

    runner = PipelineRunner(
        trace_sink=NullTraceSink(),
        store=MockStore(),
        sources=[ExactCodeSource(), FTSSource()],
        config=config,
        decision_policy=ThresholdDecisionPolicy(
            confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
        ),
    )

    query = Query(
        raw_text="US",
        normalized=NormalizedText(original="US", normalized="us"),
    )
    result = runner.resolve(query, ResolutionContext())

    assert result.status == ResolutionStatus.RESOLVED


def test_post_scoring_stop_without_min_confidence_uses_decision_policy():
    """Post-scoring stop condition without min_confidence falls through to decision policy.

    This prevents auto-resolving low-confidence candidates when only candidate
    count constraints are specified.
    """
    from resolvekit.core.engine.config import PipelineConfig, StopCondition
    from resolvekit.core.engine.interfaces import CandidateSource
    from resolvekit.core.engine.runner import PipelineRunner
    from resolvekit.core.explain import NullTraceSink
    from resolvekit.core.model import (
        CandidateEvidence,
        GenerationContext,
        NormalizedText,
        Query,
        ResolutionContext,
        ResolutionStatus,
    )
    from resolvekit.core.store import EntityStore

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

    class LowConfidenceSource(CandidateSource):
        @property
        def name(self):
            return "low_confidence_source"

        def supports(self, domain_pack_id: str):
            return True

        def generate(self, ctx: GenerationContext):
            # Return a single candidate with low confidence (0.5)
            # This is below the default threshold (0.8)
            return [
                CandidateEvidence(
                    entity_id="country/USA",
                    source_name=self.name,
                    raw_score=0.5,
                    rank=1,
                )
            ]

    # Post-scoring stop condition without min_confidence
    config = PipelineConfig(
        stop_conditions=[
            StopCondition(
                name="single_candidate",
                max_candidates=1,
                # phase defaults to "post_scoring"
                # min_confidence is None
            )
        ],
    )

    from resolvekit.core.engine.decision import ThresholdDecisionPolicy

    runner = PipelineRunner(
        trace_sink=NullTraceSink(),
        store=MockStore(),
        sources=[LowConfidenceSource()],
        config=config,
        decision_policy=ThresholdDecisionPolicy(
            confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
        ),
    )

    query = Query(
        raw_text="US",
        normalized=NormalizedText(original="US", normalized="us"),
    )
    result = runner.resolve(query, ResolutionContext())

    # Should NOT auto-resolve because min_confidence wasn't set.
    # Falls through to decision policy which rejects low confidence.
    assert result.status == ResolutionStatus.NO_MATCH


def test_post_scoring_stop_with_min_confidence_auto_resolves():
    """Post-scoring stop condition with explicit min_confidence auto-resolves."""
    from resolvekit.core.engine.config import PipelineConfig, StopCondition
    from resolvekit.core.engine.interfaces import CandidateSource
    from resolvekit.core.engine.runner import PipelineRunner
    from resolvekit.core.explain import NullTraceSink
    from resolvekit.core.model import (
        CandidateEvidence,
        GenerationContext,
        NormalizedText,
        Query,
        ResolutionContext,
        ResolutionStatus,
    )
    from resolvekit.core.store import EntityStore

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

    class HighConfidenceSource(CandidateSource):
        @property
        def name(self):
            return "high_confidence_source"

        def supports(self, domain_pack_id: str):
            return True

        def generate(self, ctx: GenerationContext):
            return [
                CandidateEvidence(
                    entity_id="country/USA",
                    source_name=self.name,
                    raw_score=0.95,
                    rank=1,
                )
            ]

    # Post-scoring stop condition WITH explicit min_confidence
    config = PipelineConfig(
        stop_conditions=[
            StopCondition(
                name="high_confidence_single",
                max_candidates=1,
                min_confidence=0.9,
                # phase defaults to "post_scoring"
            )
        ],
    )

    from resolvekit.core.engine.decision import ThresholdDecisionPolicy

    runner = PipelineRunner(
        trace_sink=NullTraceSink(),
        store=MockStore(),
        sources=[HighConfidenceSource()],
        config=config,
        decision_policy=ThresholdDecisionPolicy(
            confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
        ),
    )

    query = Query(
        raw_text="US",
        normalized=NormalizedText(original="US", normalized="us"),
    )
    result = runner.resolve(query, ResolutionContext())

    # Should auto-resolve because min_confidence is set and met
    assert result.status == ResolutionStatus.RESOLVED
    assert result.entity_id == "country/USA"
    assert result.confidence == 0.95
