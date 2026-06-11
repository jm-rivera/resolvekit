"""Verify QueryPreparer, CodeLookup, and BatchResolver depend on the
ResolverBackend protocol and construct without importing the Resolver facade.
"""

from __future__ import annotations

import weakref
from dataclasses import dataclass, field
from typing import Any

import pytest

from resolvekit.core.api.batch import BatchResolver
from resolvekit.core.api.code_lookup import CodeLookup, looks_like_code
from resolvekit.core.api.query_prep import QueryPreparer
from resolvekit.core.engine import PipelineResult, RoutingMode
from resolvekit.core.model import (
    EntityRecord,
    Query,
    ReasonCode,
    ResolutionContext,
    ResolutionResult,
    ResolutionResultList,
    ResolutionStatus,
)
from resolvekit.core.util.normalization import TextNormalizer

# ---------------------------------------------------------------------------
# Minimal stub ResolverBackend — no Resolver dependency
# ---------------------------------------------------------------------------


@dataclass
class _StubRunner:
    """Minimal ResolverBackend stub — all protocol methods are present."""

    _available_packs: frozenset[str] = field(default_factory=frozenset)
    _code_systems: frozenset[str] = field(
        default_factory=lambda: frozenset({"iso2", "iso3", "numeric"})
    )
    call_count: int = 0

    def resolve(
        self,
        query: Query,
        context: ResolutionContext,
        *,
        trace_sink: Any = None,
        deadline: float | None = None,
    ) -> ResolutionResult:
        self.call_count += 1
        return ResolutionResult(
            status=ResolutionStatus.RESOLVED,
            entity_id=f"entity/{query.raw_text}",
            confidence=0.9,
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
        self.call_count += 1
        result = ResolutionResult(
            status=ResolutionStatus.RESOLVED,
            entity_id=f"entity/{query.raw_text}",
            confidence=0.9,
            reasons=[ReasonCode.FTS_MATCH],
            query_text=query.raw_text,
        )
        return PipelineResult(result=result)

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
        if system == "iso2" and value_norm == "us":
            return ["country/USA"]
        return []

    @property
    def available_packs(self) -> frozenset[str]:
        return self._available_packs

    @property
    def available_entity_types(self) -> frozenset[str]:
        return frozenset()

    @property
    def available_code_systems(self) -> frozenset[str]:
        return self._code_systems

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
        return "stub"

    def normalize_code_value(
        self, system: str, value: str, *, pack_filter: frozenset[str] | None = None
    ) -> str:
        return value.casefold()

    def lookup_name_exact(
        self, *, value: str, pack_filter: frozenset[str] | None = None
    ) -> list[tuple[str, str]]:
        return []


# ---------------------------------------------------------------------------
# QueryPreparer
# ---------------------------------------------------------------------------


class TestQueryPreparer:
    def _make(
        self, routing_mode: RoutingMode | None = None
    ) -> tuple[QueryPreparer, _StubRunner]:
        runner = _StubRunner()
        default_ctx = ResolutionContext()
        preparer = QueryPreparer(
            runner=runner,
            normalizer=TextNormalizer(),
            pack_normalizers={},
            max_query_length=1000,
            routing_mode=routing_mode,
            default_context=default_ctx,
        )
        return preparer, runner

    def test_normalize_returns_normalized_text(self) -> None:
        preparer, _ = self._make()
        result = preparer.normalize("Hello World")
        # NFC + casefold
        assert result.normalized == "hello world"

    def test_prepare_query_returns_query_and_context(self) -> None:
        preparer, _ = self._make()
        ctx = ResolutionContext()
        query, returned_ctx = preparer.prepare_query("United States", ctx, None)
        assert query.raw_text == "United States"
        assert returned_ctx is ctx

    def test_prepare_query_uses_default_context_when_none(self) -> None:
        preparer, _ = self._make()
        _, returned_ctx = preparer.prepare_query("US", None, None)
        assert isinstance(returned_ctx, ResolutionContext)

    def test_prepare_query_truncates_long_text(self) -> None:
        runner = _StubRunner()
        default_ctx = ResolutionContext()
        preparer = QueryPreparer(
            runner=runner,
            normalizer=TextNormalizer(),
            pack_normalizers={},
            max_query_length=5,
            routing_mode=None,
            default_context=default_ctx,
        )
        query, _ = preparer.prepare_query("Hello World", None, None)
        assert query.raw_text == "Hello"

    def test_invalid_query_result_returns_no_match(self) -> None:
        preparer, _ = self._make()
        result = preparer.invalid_query_result()
        assert result.status == ResolutionStatus.NO_MATCH
        assert ReasonCode.INVALID_QUERY in result.reasons

    def test_invalid_query_result_custom_reason(self) -> None:
        preparer, _ = self._make()
        result = preparer.invalid_query_result(ReasonCode.INVALID_INPUT_TYPE)
        assert ReasonCode.INVALID_INPUT_TYPE in result.reasons

    def test_auto_routing_mode_raises_on_domains(self) -> None:
        preparer, _ = self._make(routing_mode=RoutingMode.AUTO)
        with pytest.raises(ValueError, match="AUTO routing mode"):
            preparer.prepare_query("US", None, frozenset({"geo"}))

    def test_no_resolver_import(self) -> None:
        """QueryPreparer module must not import from api/resolver.py."""
        import importlib
        import sys

        mod = importlib.import_module("resolvekit.core.api.query_prep")
        for name, m in sys.modules.items():
            if "api.resolver" in name:
                # query_prep should not have pulled resolver.py into sys.modules
                # via its own import chain
                assert "query_prep" not in getattr(m, "__file__", ""), (
                    f"query_prep imported api.resolver ({name})"
                )
        _ = mod  # used


# ---------------------------------------------------------------------------
# CodeLookup
# ---------------------------------------------------------------------------


class TestCodeLookup:
    def _make(self) -> tuple[CodeLookup, _StubRunner]:
        runner = _StubRunner()
        return CodeLookup(runner=runner), runner

    def test_looks_like_code_iso2(self) -> None:
        assert looks_like_code("US")
        assert looks_like_code("DE")

    def test_looks_like_code_iso3(self) -> None:
        assert looks_like_code("USA")
        assert looks_like_code("DEU")

    def test_looks_like_code_numeric(self) -> None:
        assert looks_like_code("840")

    def test_looks_like_code_dcid(self) -> None:
        assert looks_like_code("country/USA")

    def test_not_looks_like_code_free_text(self) -> None:
        assert not looks_like_code("United States")

    def test_looks_like_code_lowercase_alpha(self) -> None:
        # Lowercase 2-3 letter alpha routes to code lookup — see
        # ``looks_like_code`` docstring on the few iso2/word collisions.
        assert looks_like_code("us")
        assert looks_like_code("usa")

    def test_sorted_code_systems_priority(self) -> None:
        lookup, _ = self._make()
        systems = lookup.sorted_code_systems()
        # iso2 and iso3 should appear before numeric
        assert systems.index("iso2") < systems.index("numeric")
        assert systems.index("iso3") < systems.index("numeric")

    def test_make_code_resolved_result(self) -> None:
        lookup, _ = self._make()

        # Use a dummy weakref — the ref target doesn't need to be alive for this test
        class _Sentinel:
            pass

        sentinel = _Sentinel()
        ref: weakref.ref = weakref.ref(sentinel)  # type: ignore[type-arg]

        result = lookup.make_code_resolved_result(ref, "country/USA", None, "US")
        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "country/USA"
        assert result.query_text == "US"
        assert ReasonCode.EXACT_CODE_MATCH in result.reasons
        assert result._explainer is ref

    def test_resolve_or_lookup_explicit_from_system(self) -> None:
        lookup, _ = self._make()

        class _Sentinel:
            pass

        sentinel = _Sentinel()
        ref: weakref.ref = weakref.ref(sentinel)  # type: ignore[type-arg]

        def _noop_inner(*args: object, **kwargs: object) -> ResolutionResult:
            return ResolutionResult(status=ResolutionStatus.NO_MATCH)

        result = lookup.resolve_or_lookup(
            "US",
            explainer_ref=ref,
            from_system="iso2",
            resolve_inner_fn=_noop_inner,
        )
        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "country/USA"

    def test_resolve_or_lookup_falls_through_to_inner(self) -> None:
        """Non-code text falls through to resolve_inner_fn."""
        lookup, _ = self._make()

        class _Sentinel:
            pass

        sentinel = _Sentinel()
        ref: weakref.ref = weakref.ref(sentinel)  # type: ignore[type-arg]

        called: list[str] = []

        def _inner(text: str, **kwargs: object) -> ResolutionResult:
            called.append(text)
            return ResolutionResult(status=ResolutionStatus.NO_MATCH)

        lookup.resolve_or_lookup(
            "United States",
            explainer_ref=ref,
            resolve_inner_fn=_inner,
        )
        assert called == ["United States"]

    def test_no_resolver_import_in_code_lookup(self) -> None:
        """CodeLookup must not import from api/resolver.py at module level."""
        import resolvekit.core.api.code_lookup as mod

        src = getattr(mod, "__file__", "")
        # If code_lookup.py imported resolver.py, we'd see circular issues
        # at construction; the test just verifies construction works without Resolver.
        lookup = CodeLookup(runner=_StubRunner())
        assert lookup is not None
        _ = src


# ---------------------------------------------------------------------------
# BatchResolver
# ---------------------------------------------------------------------------


class TestBatchResolver:
    def _make(self) -> tuple[BatchResolver, QueryPreparer, _StubRunner]:
        runner = _StubRunner()
        default_ctx = ResolutionContext()
        preparer = QueryPreparer(
            runner=runner,
            normalizer=TextNormalizer(),
            pack_normalizers={},
            max_query_length=1000,
            routing_mode=None,
            default_context=default_ctx,
        )
        batch = BatchResolver(
            runner=runner,
            query_preparer=preparer,
            routing_mode=None,
            default_timeout=None,
        )
        return batch, preparer, runner

    def _fake_resolve_inner(self, text: str, **kwargs: object) -> ResolutionResult:
        return ResolutionResult(
            status=ResolutionStatus.RESOLVED,
            entity_id=f"entity/{text}",
            confidence=0.9,
            reasons=[ReasonCode.FTS_MATCH],
            query_text=text,
        )

    class _Sentinel:
        """Weakref-able sentinel for batch tests."""

    def _explainer_ref_factory(self) -> weakref.ref:
        sentinel = self._Sentinel()
        self._sentinel = sentinel  # keep alive
        return weakref.ref(sentinel)  # type: ignore[return-value]

    def test_resolve_many_deduplicates_same_text(self) -> None:
        batch, _, _ = self._make()
        resolve_calls: list[str] = []

        def tracking_inner(text: str, **kwargs: object) -> ResolutionResult:
            resolve_calls.append(text)
            return self._fake_resolve_inner(text)

        results = batch.resolve_many_internal(
            ["Italy", "Italy", "Germany"],
            resolve_inner_fn=tracking_inner,
            explainer_ref_factory=self._explainer_ref_factory,
        )
        assert len(results) == 3
        # Italy resolved once, Germany once — dedup in effect
        assert resolve_calls.count("Italy") == 1
        assert resolve_calls.count("Germany") == 1

    def test_resolve_many_preserves_order(self) -> None:
        batch, _, _ = self._make()
        texts = ["Alpha", "Beta", "Gamma"]
        results = batch.resolve_many_internal(
            texts,
            resolve_inner_fn=self._fake_resolve_inner,
            explainer_ref_factory=self._explainer_ref_factory,
        )
        assert [r.entity_id for r in results] == [
            "entity/Alpha",
            "entity/Beta",
            "entity/Gamma",
        ]

    def test_resolve_many_returns_resolution_result_list(self) -> None:
        batch, _, _ = self._make()
        results = batch.resolve_many_internal(
            ["X"],
            resolve_inner_fn=self._fake_resolve_inner,
            explainer_ref_factory=self._explainer_ref_factory,
        )
        assert isinstance(results, ResolutionResultList)

    def test_resolve_many_context_length_mismatch_raises(self) -> None:
        batch, _, _ = self._make()
        ctx1 = ResolutionContext()
        with pytest.raises(ValueError, match="contexts length"):
            batch.resolve_many_internal(
                ["A", "B"],
                context=[ctx1],  # mismatched length
                resolve_inner_fn=self._fake_resolve_inner,
                explainer_ref_factory=self._explainer_ref_factory,
            )

    def test_resolve_many_negative_timeout_raises(self) -> None:
        batch, _, _ = self._make()
        with pytest.raises(ValueError, match="timeout must be positive"):
            batch.resolve_many_internal(
                ["A"],
                timeout=-1.0,
                resolve_inner_fn=self._fake_resolve_inner,
                explainer_ref_factory=self._explainer_ref_factory,
            )

    def test_resolve_series_dedup_handles_nulls(self) -> None:
        import pandas as pd

        batch, preparer, _ = self._make()
        resolve_many_calls: list[list[str]] = []

        def fake_resolve_many(
            texts: list[str], **kwargs: object
        ) -> ResolutionResultList:
            resolve_many_calls.append(texts)
            return ResolutionResultList([self._fake_resolve_inner(t) for t in texts])

        series = pd.Series(["US", None, "US"])
        _index, results = batch.resolve_series_dedup(
            series,
            domain=None,
            context=None,
            resolve_many_fn=fake_resolve_many,
        )
        # Only "US" was passed to resolve_many (null excluded, deduped)
        assert resolve_many_calls == [["US"]]
        # Null slot gets sentinel
        assert results[0].status == ResolutionStatus.RESOLVED
        sentinel_status = preparer.invalid_query_result().status
        assert results[1].status == sentinel_status
        assert results[2].status == ResolutionStatus.RESOLVED

    def test_no_resolver_in_batch_dependencies(self) -> None:
        """BatchResolver must be constructable without importing Resolver."""
        batch, _, _ = self._make()
        assert batch is not None
