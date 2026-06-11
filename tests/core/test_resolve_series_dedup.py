"""Characterization tests for _run_resolve_series_dedup null/empty/dtype handling.

Pins the NaN-masking, pd.unique dedup, broadcast-back, and sentinel logic.
_resolve_many_internal is monkeypatched to a simple echo stub
so the test asserts dedup semantics, not actual resolution.
"""

import pandas as pd
import pytest

from resolvekit.core.api.resolver import Resolver
from resolvekit.core.model import ReasonCode, ResolutionResultList, ResolutionStatus
from resolvekit.core.model.result import ResolutionResult
from tests.api.test_group_preference_tiebreak import _StubBackend


def _resolved_result(text: str) -> ResolutionResult:
    """Synthetic RESOLVED result that echoes *text* as the entity_id."""
    return ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        entity_id=f"entity/{text}",
        confidence=0.9,
        reasons=[ReasonCode.FTS_MATCH],
    )


def _make_resolver() -> Resolver:
    return Resolver(runner=_StubBackend(), routing_mode=None)  # type: ignore[arg-type]


class TestResolveSeriesDedup:
    """Boundary characterization of ``_run_resolve_series_dedup``."""

    def _sentinel_status(self, resolver: Resolver) -> ResolutionStatus:
        """Read the sentinel status directly from the live impl (pins actual behavior)."""
        return resolver._invalid_query_result(ReasonCode.INVALID_QUERY).status

    def test_all_null_series(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """All-null series → every slot is the INVALID_QUERY sentinel; _resolve_many_internal
        is called with an empty list (no uniques after masking nulls).
        """
        resolver = _make_resolver()
        calls: list[list[str]] = []

        def fake(texts: list[str], **_kw: object) -> ResolutionResultList:
            calls.append(list(texts))
            return ResolutionResultList([_resolved_result(t) for t in texts])

        monkeypatch.setattr(resolver, "_resolve_many_internal", fake)

        series = pd.Series([None, None], dtype=object)
        _index, results = resolver._resolve_series_dedup(
            series, domain=None, context=None
        )

        assert calls == [[]], (
            "unique list passed to _resolve_many_internal must be empty"
        )
        sentinel_status = self._sentinel_status(resolver)
        assert all(r.status == sentinel_status for r in results)
        assert len(results) == 2

    def test_empty_series(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty series → empty result list, index preserved."""
        resolver = _make_resolver()
        calls: list[list[str]] = []

        def fake(texts: list[str], **_kw: object) -> ResolutionResultList:
            calls.append(list(texts))
            return ResolutionResultList([])

        monkeypatch.setattr(resolver, "_resolve_many_internal", fake)

        series = pd.Series([], dtype=object)
        index, results = resolver._resolve_series_dedup(
            series, domain=None, context=None
        )

        assert list(index) == list(series.index)
        assert results == []

    def test_mixed_null_and_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """["US", None, "US"] → slots 0 & 2 get the "US" result, slot 1 is the sentinel.

        _resolve_many_internal is called exactly once with the single unique ["US"].
        """
        resolver = _make_resolver()
        calls: list[list[str]] = []

        def fake(texts: list[str], **_kw: object) -> ResolutionResultList:
            calls.append(list(texts))
            return ResolutionResultList([_resolved_result(t) for t in texts])

        monkeypatch.setattr(resolver, "_resolve_many_internal", fake)

        series = pd.Series(["US", None, "US"])
        index, results = resolver._resolve_series_dedup(
            series, domain=None, context=None
        )

        assert calls == [["US"]], "dedup must produce exactly one unique"
        sentinel_status = self._sentinel_status(resolver)
        assert results[0].status == ResolutionStatus.RESOLVED
        assert results[0].entity_id == "entity/US"
        assert results[1].status == sentinel_status
        assert results[2].status == ResolutionStatus.RESOLVED
        assert results[2].entity_id == "entity/US"
        assert list(index) == list(series.index)

    def test_non_string_dtype(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Integer series [1, 2, 1] is coerced via str() before dedup.

        Pins the astype(object).map(str) coercion path: expects exactly two
        uniques ("1" and "2"), broadcast back to three slots.
        """
        resolver = _make_resolver()
        calls: list[list[str]] = []

        def fake(texts: list[str], **_kw: object) -> ResolutionResultList:
            calls.append(list(texts))
            return ResolutionResultList([_resolved_result(t) for t in texts])

        monkeypatch.setattr(resolver, "_resolve_many_internal", fake)

        series = pd.Series([1, 2, 1])
        index, results = resolver._resolve_series_dedup(
            series, domain=None, context=None
        )

        assert len(calls) == 1
        assert set(calls[0]) == {"1", "2"}
        assert len(results) == 3
        # slots 0 and 2 both map to "1"
        assert results[0].entity_id == results[2].entity_id
        # slot 1 maps to "2"
        assert results[1].entity_id != results[0].entity_id
        assert list(index) == list(series.index)
