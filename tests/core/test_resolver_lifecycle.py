"""Tests for Resolver lifecycle: close(), context manager, resolve-after-close."""

import pytest

from resolvekit.core.api import Resolver
from resolvekit.core.engine import PipelineRunner
from resolvekit.core.engine.decision import ThresholdDecisionPolicy
from resolvekit.core.explain import NullTraceSink
from resolvekit.core.model import ResolutionStatus
from resolvekit.core.util import TextNormalizer
from tests.conftest import MockEntityStore


def _make_resolver() -> Resolver:
    """Create a minimal resolver for lifecycle tests."""
    store = MockEntityStore(codes={("iso2", "us"): ["country/USA"]})
    runner = PipelineRunner(
        trace_sink=NullTraceSink(),
        store=store,
        sources=[],
        decision_policy=ThresholdDecisionPolicy(
            confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
        ),
    )
    return Resolver(runner=runner, normalizer=TextNormalizer())


class TestResolverClose:
    """Tests for Resolver.close() and context manager."""

    def test_close_is_idempotent(self):
        resolver = _make_resolver()
        resolver.close()
        resolver.close()  # should not raise

    def test_resolve_after_close_raises(self):
        resolver = _make_resolver()
        resolver.close()

        with pytest.raises(RuntimeError, match="closed"):
            resolver.resolve("US")

    def test_resolve_explained_after_close_raises(self):
        resolver = _make_resolver()
        resolver.close()

        with pytest.raises(RuntimeError, match="closed"):
            resolver.resolve_explained("US")

    def test_context_manager_closes(self):
        with _make_resolver() as resolver:
            assert not resolver._closed

        assert resolver._closed

    def test_context_manager_closes_on_exception(self):
        with (
            pytest.raises(ValueError, match="test error"),
            _make_resolver() as resolver,
        ):
            raise ValueError("test error")

        assert resolver._closed

    def test_context_manager_resolve_works(self, geo_test_datapack):
        with Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        ) as resolver:
            result = resolver.resolve("US")
            assert result.status == ResolutionStatus.RESOLVED

    def test_resolve_after_context_manager_raises(self, geo_test_datapack):
        with Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        ) as resolver:
            pass

        with pytest.raises(RuntimeError, match="closed"):
            resolver.resolve("US")
