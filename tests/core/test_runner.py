"""Tests for the pipeline runner."""

import pytest


class TestDefaultPipelineConfig:
    """The shared default pack config must not short-circuit the decision policy."""

    def test_default_pack_config_has_no_auto_resolve_stop_condition(self):
        from resolvekit.core.engine.config import DEFAULT_PACK_PIPELINE_CONFIG

        # A stop condition with min_confidence set in post_scoring phase bypasses
        # decision-policy gap/ambiguity checks and can silently resolve a tied
        # high-confidence pair to the wrong entity. The default config must not
        # carry that shape — packs opt in explicitly if they need early exit.
        for cond in DEFAULT_PACK_PIPELINE_CONFIG.stop_conditions:
            assert not (
                cond.phase == "post_scoring" and cond.min_confidence is not None
            )


class TestPipelineRunner:
    """Tests for PipelineRunner."""

    def test_runner_creation(self):
        from resolvekit.core.engine.decision import ThresholdDecisionPolicy
        from resolvekit.core.engine.runner import PipelineRunner
        from resolvekit.core.explain import NullTraceSink

        runner = PipelineRunner(
            trace_sink=NullTraceSink(),
            decision_policy=ThresholdDecisionPolicy(
                confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
            ),
        )
        assert runner is not None

    def test_runner_requires_store(self):
        from resolvekit.core.engine.decision import ThresholdDecisionPolicy
        from resolvekit.core.engine.runner import PipelineRunner
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import NormalizedText, Query, ResolutionContext

        runner = PipelineRunner(
            trace_sink=NullTraceSink(),
            decision_policy=ThresholdDecisionPolicy(
                confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
            ),
        )

        query = Query(
            raw_text="USA",
            normalized=NormalizedText(original="USA", normalized="usa"),
        )
        context = ResolutionContext()

        # Should raise if no store configured
        with pytest.raises(ValueError, match="store"):
            runner.resolve(query, context)

    def test_runner_with_mock_source_and_store(self):
        from resolvekit.core.engine.interfaces import (
            CandidateSource,
            DecisionPolicy,
        )
        from resolvekit.core.engine.runner import PipelineRunner
        from resolvekit.core.explain import MemoryTraceSink
        from resolvekit.core.model import (
            CandidateEvidence,
            CandidateSummary,
            EntityRecord,
            GenerationContext,
            NormalizedText,
            Query,
            ReasonCode,
            ResolutionContext,
            ResolutionResult,
            ResolutionStatus,
        )
        from resolvekit.core.store import EntityStore

        class MockStore(EntityStore):
            def get_entity(self, entity_id: str) -> EntityRecord | None:
                if entity_id == "country/USA":
                    return EntityRecord(
                        entity_id="country/USA",
                        entity_type="geo.country",
                        canonical_name="United States",
                        canonical_name_norm="united states",
                    )
                return None

            def lookup_code(self, system: str, value_norm: str) -> list[str]:
                if system == "iso2" and value_norm == "us":
                    return ["country/USA"]
                return []

            def lookup_name_exact(self, value_norm: str, name_kinds=None) -> list[str]:
                return []

            def search_fulltext(self, query_norm: str, fields=None, limit: int = 10):
                return []

            def bulk_get_entities(
                self, entity_ids: list[str]
            ) -> dict[str, EntityRecord]:
                return {eid: e for eid in entity_ids if (e := self.get_entity(eid))}

        # Mock source that finds USA by ISO2 code
        class MockCodeSource(CandidateSource):
            @property
            def name(self) -> str:
                return "mock_exact_code"

            def supports(self, domain_pack_id: str) -> bool:
                return True

            def generate(self, ctx: GenerationContext):
                # Simulate finding USA by code "US"
                if ctx.text_norm.upper() in ("US", "USA"):
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
                return []

        # Simple decision policy
        class MockDecisionPolicy(DecisionPolicy):
            def decide(self, query, context, candidates, trace) -> ResolutionResult:
                if candidates:
                    top = candidates[0]
                    return ResolutionResult(
                        status=ResolutionStatus.RESOLVED,
                        entity_id=top.entity_id,
                        confidence=top.scores.calibrated_score,
                        candidates=[
                            CandidateSummary(
                                entity_id=top.entity_id,
                                confidence=top.scores.calibrated_score,
                            )
                        ],
                        reasons=[ReasonCode.EXACT_CODE_MATCH],
                    )
                return ResolutionResult(
                    status=ResolutionStatus.NO_MATCH,
                    reasons=[ReasonCode.NO_CANDIDATES],
                )

        trace_sink = MemoryTraceSink()
        runner = PipelineRunner(
            trace_sink=trace_sink,
            store=MockStore(),
            sources=[MockCodeSource()],
            decision_policy=MockDecisionPolicy(),
        )

        query = Query(
            raw_text="US",
            normalized=NormalizedText(original="US", normalized="us"),
        )
        context = ResolutionContext()

        result = runner.resolve(query, context)

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "country/USA"
        assert ReasonCode.EXACT_CODE_MATCH in result.reasons
        assert result.candidates[0].canonical_name == "United States"
        assert result.candidates[0].entity_type == "geo.country"

        # Check trace has events
        events = trace_sink.get_events()
        assert len(events) > 0

    def test_deadline_already_expired_skips_sources(self):
        """An already-expired deadline is detected before any source runs."""
        import time

        from resolvekit.core.engine.interfaces import CandidateSource
        from resolvekit.core.engine.runner import PipelineRunner
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ReasonCode,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.core.store import EntityStore

        sources_called = []

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

        class TrackingSource(CandidateSource):
            @property
            def name(self):
                return "tracking_source"

            def supports(self, domain_pack_id):
                return True

            def generate(self, ctx: GenerationContext):
                sources_called.append(True)
                return []

        from resolvekit.core.engine.decision import ThresholdDecisionPolicy

        runner = PipelineRunner(
            trace_sink=NullTraceSink(),
            store=MockStore(),
            sources=[TrackingSource()],
            decision_policy=ThresholdDecisionPolicy(
                confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
            ),
        )

        query = Query(
            raw_text="test",
            normalized=NormalizedText(original="test", normalized="test"),
        )

        # Deadline already expired
        past_deadline = time.monotonic() - 1.0

        start = time.monotonic()
        result = runner.resolve(
            query=query,
            context=ResolutionContext(),
            deadline=past_deadline,
        )
        elapsed = time.monotonic() - start

        assert result.status == ResolutionStatus.ERROR
        assert ReasonCode.TIMEOUT in result.reasons
        assert elapsed < 0.1, (
            f"Expired deadline should return immediately, took {elapsed:.3f}s"
        )
        assert not sources_called, (
            "No sources should run when deadline is already expired"
        )

    def test_deadline_expires_between_sources(self):
        """A deadline that expires during the first source blocks the second source."""
        import time

        from resolvekit.core.engine.interfaces import CandidateSource
        from resolvekit.core.engine.runner import PipelineRunner
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ReasonCode,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.core.store import EntityStore

        sources_called = []

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

        class SlowSource(CandidateSource):
            @property
            def name(self):
                return "slow_source"

            def supports(self, domain_pack_id):
                return True

            def generate(self, ctx: GenerationContext):
                sources_called.append("slow")
                time.sleep(0.15)
                return []

        class FastSource(CandidateSource):
            @property
            def name(self):
                return "fast_source"

            def supports(self, domain_pack_id):
                return True

            def generate(self, ctx: GenerationContext):
                sources_called.append("fast")
                return []

        from resolvekit.core.engine.decision import ThresholdDecisionPolicy

        runner = PipelineRunner(
            trace_sink=NullTraceSink(),
            store=MockStore(),
            sources=[SlowSource(), FastSource()],
            decision_policy=ThresholdDecisionPolicy(
                confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
            ),
        )

        query = Query(
            raw_text="test",
            normalized=NormalizedText(original="test", normalized="test"),
        )

        start = time.monotonic()
        result = runner.resolve(
            query=query,
            context=ResolutionContext(),
            deadline=time.monotonic() + 0.05,
        )
        elapsed = time.monotonic() - start

        assert result.status == ResolutionStatus.ERROR
        assert ReasonCode.TIMEOUT in result.reasons
        # SlowSource ran (deadline hadn't expired when it was checked before SlowSource)
        # FastSource was skipped (deadline expired after SlowSource completed)
        assert "slow" in sources_called
        assert "fast" not in sources_called, (
            "FastSource should be skipped after deadline expired"
        )
        assert elapsed < 0.3, f"Took {elapsed:.3f}s"


class TestApplyConfidenceThreshold:
    """Tests for PipelineRunner.apply_confidence_threshold."""

    def _make_runner_with_threshold_policy(self, threshold: float):
        from resolvekit.core.engine.decision import ThresholdDecisionPolicy
        from resolvekit.core.engine.runner import PipelineRunner
        from resolvekit.core.explain import NullTraceSink

        return PipelineRunner(
            trace_sink=NullTraceSink(),
            decision_policy=ThresholdDecisionPolicy(
                confidence_threshold=threshold,
                min_gap=0.1,
                gap_inclusive=True,
            ),
        )

    def test_returns_true_and_mutates_threshold_policy(self):
        """Returns True and updates confidence_threshold when policy is ThresholdDecisionPolicy."""
        from resolvekit.core.engine.decision import ThresholdDecisionPolicy

        runner = self._make_runner_with_threshold_policy(0.8)
        updated = runner.apply_confidence_threshold(threshold=0.6)

        assert updated is True
        assert isinstance(runner._decision_policy, ThresholdDecisionPolicy)
        assert runner._decision_policy.confidence_threshold == pytest.approx(0.6)

    def test_returns_false_for_non_threshold_policy(self):
        """Returns False when decision policy does not support confidence_threshold."""
        from resolvekit.core.engine.interfaces import DecisionPolicy
        from resolvekit.core.engine.runner import PipelineRunner
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import ResolutionResult, ResolutionStatus

        class NoThresholdPolicy(DecisionPolicy):
            def decide(self, query, context, candidates, trace) -> ResolutionResult:
                return ResolutionResult(status=ResolutionStatus.NO_MATCH, reasons=[])

        runner = PipelineRunner(
            trace_sink=NullTraceSink(),
            decision_policy=NoThresholdPolicy(),
        )
        updated = runner.apply_confidence_threshold(threshold=0.5)

        assert updated is False

    def test_kwargs_only_signature(self):
        """apply_confidence_threshold must be called with keyword argument."""
        runner = self._make_runner_with_threshold_policy(0.8)
        with pytest.raises(TypeError):
            runner.apply_confidence_threshold(0.5)  # type: ignore[call-arg]
