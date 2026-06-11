"""Verify resolve_detailed() returns PipelineResult and resolve() returns
ResolutionResult, and that timeout→deadline conversion works correctly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import pytest

from resolvekit.core.api.resolver import Resolver
from resolvekit.core.engine.interfaces import PipelineResult
from resolvekit.core.model import (
    EntityRecord,
    Query,
    ReasonCode,
    ResolutionContext,
    ResolutionResult,
    ResolutionStatus,
)

# ---------------------------------------------------------------------------
# Minimal fake backend
# ---------------------------------------------------------------------------


@dataclass
class _FakeBackend:
    """Minimal ResolverBackend that tracks calls and returns synthetic results."""

    _available: frozenset[str] = field(default_factory=frozenset)

    def resolve(
        self,
        query: Query,
        context: ResolutionContext,
        *,
        trace_sink: Any = None,
        deadline: float | None = None,
    ) -> ResolutionResult:
        return ResolutionResult(
            status=ResolutionStatus.RESOLVED,
            entity_id="country/USA",
            confidence=0.95,
            reasons=[ReasonCode.FTS_MATCH],
            query_text=query.raw_text,
        )

    def resolve_detailed(
        self,
        query: Query,
        context: ResolutionContext,
        *,
        trace_sink: Any = None,
        deadline: float | None = None,
    ) -> PipelineResult:
        result = ResolutionResult(
            status=ResolutionStatus.RESOLVED,
            entity_id="country/USA",
            confidence=0.95,
            reasons=[ReasonCode.FTS_MATCH],
            query_text=query.raw_text,
        )
        return PipelineResult(result=result, pack_id="geo")

    def close(self) -> None:
        pass

    def get_entity(self, entity_id: str) -> EntityRecord | None:
        return None

    def lookup_code(
        self,
        system: str,
        value_norm: str,
        *,
        pack_filter: frozenset[str] | None = None,
    ) -> list[str]:
        return []

    @property
    def available_packs(self) -> frozenset[str]:
        return self._available

    @property
    def available_entity_types(self) -> frozenset[str]:
        return frozenset()

    @property
    def available_code_systems(self) -> frozenset[str]:
        return frozenset()

    @property
    def available_group_types(self) -> frozenset[str]:
        return frozenset()

    def get_reverse_relations(
        self, *, entity_id: str, relation_type: str, as_of: Any = None
    ) -> list[str]:
        return []

    def get_relations_as_of(
        self, *, entity_id: str, relation_type: str, as_of: Any
    ) -> frozenset[str]:
        return frozenset()

    def list_entities_by_type(self, *, entity_type: str) -> list[EntityRecord]:
        return []

    def get_pack_group_types(self, *, pack_id: str) -> frozenset[str]:
        return frozenset()

    def is_snapshot_entity(self, *, entity_id: str) -> bool:
        return False

    def lookup_pack_id(self) -> str | None:
        return None

    def lookup_name_exact(
        self, *, value: str, pack_filter: frozenset[str] | None = None
    ) -> list[tuple[str, str]]:
        return []


def _make_resolver() -> tuple[Resolver, _FakeBackend]:
    backend = _FakeBackend()
    resolver = Resolver(backend, cache_size=0)
    return resolver, backend


# ---------------------------------------------------------------------------
# resolve() returns ResolutionResult
# ---------------------------------------------------------------------------


class TestResolveReturnType:
    def test_resolve_returns_resolution_result(self) -> None:
        resolver, _ = _make_resolver()
        result = resolver.resolve("United States")
        assert isinstance(result, ResolutionResult)
        assert not isinstance(result, PipelineResult)

    def test_resolve_status_is_resolved(self) -> None:
        resolver, _ = _make_resolver()
        result = resolver.resolve("United States")
        assert result.status == ResolutionStatus.RESOLVED

    def test_resolve_non_string_returns_no_match(self) -> None:
        resolver, _ = _make_resolver()
        result = resolver.resolve(None)  # type: ignore[arg-type]
        assert isinstance(result, ResolutionResult)
        assert result.status == ResolutionStatus.NO_MATCH

    def test_resolve_empty_string_returns_no_match(self) -> None:
        resolver, _ = _make_resolver()
        result = resolver.resolve("")
        assert isinstance(result, ResolutionResult)
        assert result.status == ResolutionStatus.NO_MATCH


# ---------------------------------------------------------------------------
# resolve_detailed() returns PipelineResult
# ---------------------------------------------------------------------------


class TestResolveDetailed:
    def test_resolve_detailed_returns_pipeline_result(self) -> None:
        resolver, _ = _make_resolver()
        result = resolver.resolve_detailed("United States")
        assert isinstance(result, PipelineResult)

    def test_resolve_detailed_has_result_attribute(self) -> None:
        resolver, _ = _make_resolver()
        pipeline = resolver.resolve_detailed("United States")
        assert hasattr(pipeline, "result")
        assert isinstance(pipeline.result, ResolutionResult)

    def test_resolve_detailed_result_is_resolved(self) -> None:
        resolver, _ = _make_resolver()
        pipeline = resolver.resolve_detailed("United States")
        assert pipeline.result.status == ResolutionStatus.RESOLVED

    def test_resolve_detailed_empty_string_returns_no_match(self) -> None:
        resolver, _ = _make_resolver()
        pipeline = resolver.resolve_detailed("")
        assert isinstance(pipeline, PipelineResult)
        assert pipeline.result.status == ResolutionStatus.NO_MATCH

    def test_resolve_detailed_non_string_returns_no_match(self) -> None:
        resolver, _ = _make_resolver()
        pipeline = resolver.resolve_detailed(None)  # type: ignore[arg-type]
        assert isinstance(pipeline, PipelineResult)
        assert pipeline.result.status == ResolutionStatus.NO_MATCH

    def test_resolve_detailed_closed_resolver_raises(self) -> None:
        resolver, _ = _make_resolver()
        resolver.close()
        with pytest.raises(RuntimeError, match="closed"):
            resolver.resolve_detailed("US")

    def test_resolve_detailed_negative_timeout_raises(self) -> None:
        resolver, _ = _make_resolver()
        with pytest.raises(ValueError, match="timeout must be positive"):
            resolver.resolve_detailed("US", timeout=-1.0)

    def test_resolve_and_resolve_detailed_agree_on_entity(self) -> None:
        """resolve() and resolve_detailed().result should both report country/USA."""
        resolver, _ = _make_resolver()
        simple = resolver.resolve("United States")
        detailed = resolver.resolve_detailed("United States")
        assert simple.entity_id == detailed.result.entity_id


# ---------------------------------------------------------------------------
# Deadline (timeout → absolute monotonic timestamp)
# ---------------------------------------------------------------------------


@dataclass
class _DeadlineCapturingBackend(_FakeBackend):
    """Records the deadline passed by resolve_detailed for inspection."""

    captured_deadline: float | None = field(default=None, init=False)

    def resolve_detailed(
        self,
        query: Query,
        context: ResolutionContext,
        *,
        trace_sink: Any = None,
        deadline: float | None = None,
    ) -> PipelineResult:
        self.captured_deadline = deadline
        return super().resolve_detailed(
            query, context, trace_sink=trace_sink, deadline=deadline
        )


class TestResolveDetailedDeadline:
    def test_positive_timeout_produces_future_deadline(self) -> None:
        """A timeout of 5 s must produce deadline > now, not an instant-timeout."""
        backend = _DeadlineCapturingBackend()
        resolver = Resolver(backend, cache_size=0)
        before = time.monotonic()
        resolver.resolve_detailed("United States", timeout=5.0)
        assert backend.captured_deadline is not None
        assert backend.captured_deadline > before

    def test_tiny_timeout_produces_near_deadline(self) -> None:
        """A very small timeout should produce a deadline that is very close to now."""
        backend = _DeadlineCapturingBackend()
        resolver = Resolver(backend, cache_size=0)
        before = time.monotonic()
        resolver.resolve_detailed("United States", timeout=0.001)
        after = time.monotonic()
        assert backend.captured_deadline is not None
        # Deadline must be between (before + 0.001) and (after + 0.001)
        assert backend.captured_deadline >= before + 0.001
        assert backend.captured_deadline <= after + 0.001

    def test_no_timeout_passes_none_deadline(self) -> None:
        """When no timeout is set, deadline passed to the runner must be None."""
        backend = _DeadlineCapturingBackend()
        resolver = Resolver(backend, cache_size=0)
        resolver.resolve_detailed("United States")
        assert backend.captured_deadline is None


# ---------------------------------------------------------------------------
# Explainer reference (resolve_explained._explainer)
# ---------------------------------------------------------------------------


class TestResolveExplainedExplainerRef:
    def test_resolve_explained_result_has_explainer_set(self) -> None:
        """result._explainer must be set after resolve_explained so .explain() works."""
        resolver, _ = _make_resolver()
        explained = resolver.resolve_explained("United States")
        assert explained.result._explainer is not None

    def test_resolve_explained_result_explainer_refs_resolver(self) -> None:
        """The _explainer weakref must point to the resolver (the Explainer)."""
        resolver, _ = _make_resolver()
        explained = resolver.resolve_explained("United States")
        ref = explained.result._explainer
        assert ref is not None
        assert ref() is resolver


# ---------------------------------------------------------------------------
# resolve_detailed() applies the same finalization as resolve()
# ---------------------------------------------------------------------------


@dataclass
class _AmbiguousGroupBackend(_FakeBackend):
    """Returns a raw AMBIGUOUS result whose top-2 holds exactly one group-typed
    candidate, so the group-preference tiebreak should promote it to RESOLVED.
    """

    def _raw_ambiguous(self, query: Query) -> ResolutionResult:
        from resolvekit.core.model import CandidateSummary

        return ResolutionResult(
            status=ResolutionStatus.AMBIGUOUS,
            reasons=[ReasonCode.AMBIGUOUS_LOW_GAP],
            query_text=query.raw_text,
            candidates=[
                CandidateSummary(
                    entity_id="group/EU",
                    confidence=0.80,
                    entity_type="geo.group",
                    pack_id="geo",
                ),
                CandidateSummary(
                    entity_id="country/FRA",
                    confidence=0.79,
                    entity_type="geo.country",
                    pack_id="geo",
                ),
            ],
        )

    def resolve(
        self,
        query: Query,
        context: ResolutionContext,
        *,
        trace_sink: Any = None,
        deadline: float | None = None,
    ) -> ResolutionResult:
        return self._raw_ambiguous(query)

    def resolve_detailed(
        self,
        query: Query,
        context: ResolutionContext,
        *,
        trace_sink: Any = None,
        deadline: float | None = None,
    ) -> PipelineResult:
        return PipelineResult(result=self._raw_ambiguous(query), pack_id="geo")

    def get_pack_group_types(self, *, pack_id: str) -> frozenset[str]:
        return frozenset({"geo.group"}) if pack_id == "geo" else frozenset()


class TestResolveDetailedFinalization:
    def test_resolve_detailed_applies_group_preference_tiebreak(self) -> None:
        """resolve_detailed().result must reflect the group tiebreak that
        resolve() applies — both promote the unique group candidate to RESOLVED.
        """
        backend = _AmbiguousGroupBackend()
        resolver = Resolver(backend, cache_size=0)

        simple = resolver.resolve("EU")
        detailed = resolver.resolve_detailed("EU")

        assert simple.status == ResolutionStatus.RESOLVED
        assert simple.entity_id == "group/EU"
        assert detailed.result.status == ResolutionStatus.RESOLVED
        assert detailed.result.entity_id == "group/EU"
        assert detailed.result.entity_id == simple.entity_id

    def test_resolve_detailed_sets_explainer_ref(self) -> None:
        """result._explainer is set so .result.explain() works, matching resolve()."""
        backend = _AmbiguousGroupBackend()
        resolver = Resolver(backend, cache_size=0)
        detailed = resolver.resolve_detailed("EU")
        ref = detailed.result._explainer
        assert ref is not None
        assert ref() is resolver
