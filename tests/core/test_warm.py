"""Tests for warm-up plumbing: CandidateSource.warm(), PipelineRunner.warm(),
MultiPackRunner.warm(), Resolver warm=True/False, and the module-level warm()
convenience function.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from resolvekit.core.api.resolver import Resolver
from resolvekit.core.engine.decision import ThresholdDecisionPolicy
from resolvekit.core.engine.interfaces import CandidateSource
from resolvekit.core.engine.multi_runner import MultiPackRunner
from resolvekit.core.engine.runner import PipelineRunner
from resolvekit.core.explain import NullTraceSink
from resolvekit.core.model import (
    CandidateEvidence,
    GenerationContext,
)
from tests.conftest import MockEntityStore

# ---------------------------------------------------------------------------
# Minimal CandidateSource helpers
# ---------------------------------------------------------------------------


class _MinimalSource(CandidateSource):
    """Minimal concrete subclass that does not override warm()."""

    @property
    def name(self) -> str:
        return "minimal"

    def supports(self, domain_pack_id: str) -> bool:
        return True

    def generate(self, ctx: GenerationContext) -> list[CandidateEvidence]:
        return []


class _EventSource(_MinimalSource):
    """Source whose warm() sets a threading.Event."""

    def __init__(self) -> None:
        self.warmed = threading.Event()

    @property
    def name(self) -> str:
        return "event_source"

    def warm(self) -> None:
        self.warmed.set()


class _FailingSource(_MinimalSource):
    """Source whose warm() always raises."""

    @property
    def name(self) -> str:
        return "failing_source"

    def warm(self) -> None:
        raise RuntimeError("warm() failed intentionally")


def _make_runner(
    sources: list[CandidateSource] | None = None,
) -> PipelineRunner:
    store = MockEntityStore()
    return PipelineRunner(
        trace_sink=NullTraceSink(),
        store=store,
        sources=sources or [],
        decision_policy=ThresholdDecisionPolicy(
            confidence_threshold=0.8,
            min_gap=0.1,
            gap_inclusive=True,
        ),
    )


def _make_resolver(
    sources: list[CandidateSource] | None = None,
    *,
    warm: bool = False,
) -> Resolver:
    from resolvekit.core.util import TextNormalizer

    runner = _make_runner(sources=sources)
    return Resolver(runner=runner, normalizer=TextNormalizer(), warm=warm)


# ---------------------------------------------------------------------------
# (1) CandidateSource.warm() default is a no-op
# ---------------------------------------------------------------------------


class TestCandidateSourceWarmDefault:
    def test_warm_is_callable_on_minimal_subclass(self) -> None:
        source = _MinimalSource()
        # Must not raise; return value is None.
        result = source.warm()
        assert result is None


# ---------------------------------------------------------------------------
# (2) PipelineRunner.warm() fires the event on a warming source
# ---------------------------------------------------------------------------


class TestPipelineRunnerWarm:
    def test_warm_fires_event_source(self) -> None:
        event_src = _EventSource()
        runner = _make_runner(sources=[event_src])
        assert not event_src.warmed.is_set()
        runner.warm()
        assert event_src.warmed.is_set()

    def test_warm_skips_failing_source_and_continues(self) -> None:
        """A source whose warm() raises must not prevent subsequent sources."""
        event_src = _EventSource()
        failing_src = _FailingSource()
        runner = _make_runner(sources=[failing_src, event_src])
        # Should not raise, and the event_src should still be warmed.
        runner.warm()
        assert event_src.warmed.is_set()

    def test_warm_no_sources_is_noop(self) -> None:
        runner = _make_runner(sources=[])
        runner.warm()  # must not raise


# ---------------------------------------------------------------------------
# (3) MultiPackRunner.warm() delegates to all pack runners
# ---------------------------------------------------------------------------


class TestMultiPackRunnerWarm:
    def test_warm_delegates_to_all_runners(self) -> None:
        runner_a = _make_runner()
        runner_b = _make_runner()
        runner_a.warm = MagicMock()  # type: ignore[method-assign]
        runner_b.warm = MagicMock()  # type: ignore[method-assign]

        # Build a MultiPackRunner stub that already has runners pre-injected.
        # We bypass __init__ by constructing a bare object and patching _runners.
        multi = object.__new__(MultiPackRunner)
        multi._runners = {"pack_a": runner_a, "pack_b": runner_b}  # type: ignore[attr-defined]

        multi.warm()

        runner_a.warm.assert_called_once()
        runner_b.warm.assert_called_once()


# ---------------------------------------------------------------------------
# (4) Resolver(warm=True) — background thread fires the event
# ---------------------------------------------------------------------------


class TestResolverWarmTrue:
    def test_background_warm_fires_event(self) -> None:
        event_src = _EventSource()
        resolver = _make_resolver(sources=[event_src], warm=True)
        fired = event_src.warmed.wait(timeout=10)
        resolver.close()
        assert fired, "Background warm-up did not fire within 10 s"


# ---------------------------------------------------------------------------
# (5) Resolver(warm=False) — event not set at construction; warm() sets it
# ---------------------------------------------------------------------------


class TestResolverWarmFalse:
    def test_no_background_warm_on_construction(self) -> None:
        event_src = _EventSource()
        resolver = _make_resolver(sources=[event_src], warm=False)
        # Give a brief window — the event must NOT be set yet.
        # (No thread was started, so this is a deterministic check.)
        assert not event_src.warmed.is_set()
        resolver.close()

    def test_explicit_warm_call_sets_event(self) -> None:
        event_src = _EventSource()
        resolver = _make_resolver(sources=[event_src], warm=False)
        assert not event_src.warmed.is_set()
        resolver.warm()
        assert event_src.warmed.is_set()
        resolver.close()


# ---------------------------------------------------------------------------
# (6) Module-level resolvekit.warm() calls .warm() on the default resolver
# ---------------------------------------------------------------------------


class TestModuleLevelWarm:
    def test_warm_calls_resolver_warm(self) -> None:
        import resolvekit
        import resolvekit._convenience as conv

        stub_resolver = MagicMock()
        stub_resolver.warm = MagicMock()

        with patch.object(conv, "_get_default", return_value=stub_resolver):
            resolvekit.warm()

        stub_resolver.warm.assert_called_once()
