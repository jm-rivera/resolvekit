"""Tests for per-row bulk context (Layer 2).

Covers:
- Scalar context broadcasts correctly across all rows
- Per-row context dict (list values) disambiguates each row independently
- Mixed scalar + per-row dict works
- Per-row column length != values length raises ValueError
- crosswalk= + per-row context raises ValueError
- _cache_key equal for two structurally-equal ResolutionContext objects
  (regression: old id() behavior intentionally changed — content-based keying)
- Per-row context does not thrash: two rows, two contexts, both correct
- _dedup_pairs deduplicates by (text, ctx._cache_key()), not by id()

Pandas and polars paths are tested for basic per-row disambiguation parity.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from resolvekit.core.api.bulk import _dedup_pairs
from resolvekit.core.api.cache import _QueryCache
from resolvekit.core.model import ResolutionContext, ResolutionResult, ResolutionStatus
from resolvekit.core.model.result import ReasonCode

# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------


def _resolved(entity_id: str = "country/FRA") -> ResolutionResult:
    return ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        entity_id=entity_id,
        confidence=0.95,
        reasons=(ReasonCode.EXACT_NAME_MATCH,),
    )


def _no_match() -> ResolutionResult:
    return ResolutionResult(
        status=ResolutionStatus.NO_MATCH,
        reasons=(ReasonCode.NO_CANDIDATES,),
    )


# ---------------------------------------------------------------------------
# ResolutionContext._cache_key — content-based identity
# ---------------------------------------------------------------------------


class TestCacheKey:
    def test_equal_contexts_have_equal_cache_key(self) -> None:
        a = ResolutionContext(country="FR")
        b = ResolutionContext(country="FR")
        assert a._cache_key() == b._cache_key()

    def test_distinct_contexts_have_distinct_cache_key(self) -> None:
        a = ResolutionContext(country="FR")
        b = ResolutionContext(country="DE")
        assert a._cache_key() != b._cache_key()

    def test_none_represented_consistently(self) -> None:
        a = ResolutionContext()
        b = ResolutionContext()
        assert a._cache_key() == b._cache_key()

    def test_entity_types_in_key(self) -> None:
        a = ResolutionContext(entity_types=frozenset({"geo.city"}))
        b = ResolutionContext(entity_types=frozenset({"geo.city"}))
        assert a._cache_key() == b._cache_key()

    def test_attributes_sorted_in_key(self) -> None:
        a = ResolutionContext(attributes={"b": 2, "a": 1})
        b = ResolutionContext(attributes={"a": 1, "b": 2})
        assert a._cache_key() == b._cache_key()

    def test_cache_key_is_hashable(self) -> None:
        ctx = ResolutionContext(country="FR", entity_types=frozenset({"geo.city"}))
        key = ctx._cache_key()
        assert hash(key) is not None
        _ = {key: "value"}  # usable as dict key


# ---------------------------------------------------------------------------
# _QueryCache — content-based key replaces id()
# ---------------------------------------------------------------------------


class TestQueryCacheContentKey:
    def test_equal_contexts_share_cache_entry(self) -> None:
        cache = _QueryCache(maxsize=8)
        result = _resolved()
        ctx_a = ResolutionContext(country="FR")
        ctx_b = ResolutionContext(country="FR")

        call_count = 0

        def _inner() -> ResolutionResult:
            nonlocal call_count
            call_count += 1
            return result

        cache.get_or_call(raw_text="Paris", context=ctx_a, domains=None, inner=_inner)
        cache.get_or_call(raw_text="Paris", context=ctx_b, domains=None, inner=_inner)
        # Two structurally-equal contexts must share the cache entry.
        assert call_count == 1

    def test_distinct_contexts_produce_distinct_entries(self) -> None:
        cache = _QueryCache(maxsize=8)
        ctx_fr = ResolutionContext(country="FR")
        ctx_us = ResolutionContext(country="US")
        call_count = 0

        def _inner() -> ResolutionResult:
            nonlocal call_count
            call_count += 1
            return _resolved()

        cache.get_or_call(raw_text="Paris", context=ctx_fr, domains=None, inner=_inner)
        cache.get_or_call(raw_text="Paris", context=ctx_us, domains=None, inner=_inner)
        assert call_count == 2

    def test_none_context_key_is_stable(self) -> None:
        cache = _QueryCache(maxsize=8)
        call_count = 0

        def _inner() -> ResolutionResult:
            nonlocal call_count
            call_count += 1
            return _resolved()

        cache.get_or_call(raw_text="US", context=None, domains=None, inner=_inner)
        cache.get_or_call(raw_text="US", context=None, domains=None, inner=_inner)
        assert call_count == 1


# ---------------------------------------------------------------------------
# _dedup_pairs
# ---------------------------------------------------------------------------


class TestDedupPairs:
    def test_identical_pairs_deduplicated(self) -> None:
        ctx_fr = ResolutionContext(country="FR")
        items = ["Paris", "Paris", "Paris"]
        contexts = [ctx_fr, ctx_fr, ctx_fr]

        pairs, indexer = _dedup_pairs(items, contexts)
        assert len(pairs) == 1
        assert indexer == [0, 0, 0]

    def test_same_text_different_context_not_deduplicated(self) -> None:
        ctx_fr = ResolutionContext(country="FR")
        ctx_us = ResolutionContext(country="US")
        items = ["Paris", "Paris"]
        contexts = [ctx_fr, ctx_us]

        pairs, indexer = _dedup_pairs(items, contexts)
        assert len(pairs) == 2
        assert indexer == [0, 1]

    def test_structurally_equal_contexts_deduplicate(self) -> None:
        # Two distinct object instances, same content — must share the same pair slot.
        ctx_a = ResolutionContext(country="FR")
        ctx_b = ResolutionContext(country="FR")
        items = ["Paris", "Paris"]
        contexts = [ctx_a, ctx_b]

        pairs, indexer = _dedup_pairs(items, contexts)
        assert len(pairs) == 1
        assert indexer == [0, 0]

    def test_null_items_produce_none_indexer(self) -> None:
        items = [None, "Paris", None]
        contexts = [None, ResolutionContext(country="FR"), None]

        pairs, indexer = _dedup_pairs(items, contexts)
        assert len(pairs) == 1
        assert indexer[0] is None
        assert indexer[1] == 0
        assert indexer[2] is None

    def test_none_context_deduplicates(self) -> None:
        items = ["US", "US"]
        contexts = [None, None]

        pairs, indexer = _dedup_pairs(items, contexts)
        assert len(pairs) == 1
        assert indexer == [0, 0]

    def test_preserves_insertion_order(self) -> None:
        ctx_fr = ResolutionContext(country="FR")
        ctx_de = ResolutionContext(country="DE")
        items = ["Paris", "Berlin", "Paris"]
        contexts = [ctx_fr, ctx_de, ctx_fr]

        pairs, indexer = _dedup_pairs(items, contexts)
        assert pairs[0] == ("Paris", ctx_fr)
        assert pairs[1] == ("Berlin", ctx_de)
        assert indexer == [0, 1, 0]


# ---------------------------------------------------------------------------
# _bulk_dispatch — per-row context with mocked resolver
# ---------------------------------------------------------------------------


def _make_mock_resolver(
    results_by_pair: dict[tuple[str, str | None], ResolutionResult] | None = None,
) -> Any:
    """Build a minimal mock resolver that records _resolve_many_internal calls."""
    resolver = MagicMock()
    resolver._runner.available_packs = frozenset()
    call_log: list[tuple[list[str], list[Any]]] = []

    def _resolve_many(texts, *, domain=None, context=None, include_entity=False):
        if context is None:
            ctxs = [None] * len(texts)
        elif isinstance(context, ResolutionContext):
            ctxs = [context] * len(texts)
        else:
            ctxs = list(context)

        call_log.append((list(texts), list(ctxs)))

        if results_by_pair is None:
            return [_resolved() for _ in texts]

        out = []
        for text, ctx in zip(texts, ctxs, strict=True):
            country = ctx.country if ctx is not None else None
            key = (text, country)
            out.append(results_by_pair.get(key, _no_match()))
        return out

    resolver._resolve_many_internal = _resolve_many
    resolver._call_log = call_log
    return resolver


class TestBulkDispatchPerRowContext:
    """Tests for the per-row context path in _bulk_dispatch."""

    def test_scalar_context_broadcasts(self) -> None:
        from resolvekit.core.api.bulk import _bulk_dispatch

        resolver = _make_mock_resolver()
        ctx_fr = ResolutionContext(country="FR")

        result = _bulk_dispatch(
            resolver=resolver,
            values=["Paris", "Lyon"],
            to=None,
            output="series",
            domain=None,
            context=ctx_fr,
            from_system=None,
            not_found="null",
            on_error="null",
            on_ambiguous="null",
        )
        # Scalar context — existing uniform path, no per-row expansion.
        assert len(result.values) == 2

    def test_per_row_list_context_disambiguates(self) -> None:
        from resolvekit.core.api.bulk import _bulk_dispatch

        results_by_pair = {
            ("Paris", "FR"): _resolved("city/PAR_FR"),
            ("Paris", "US"): _resolved("city/PAR_TX"),
        }
        resolver = _make_mock_resolver(results_by_pair)

        result = _bulk_dispatch(
            resolver=resolver,
            values=["Paris", "Paris"],
            to=None,
            output="series",
            domain=None,
            context={"country": ["FR", "US"]},
            from_system=None,
            not_found="null",
            on_error="null",
            on_ambiguous="null",
        )
        values = result.values
        assert values[0].entity_id == "city/PAR_FR"
        assert values[1].entity_id == "city/PAR_TX"

    def test_per_row_context_deduplicates_resolve_calls(self) -> None:
        """A frame with N rows but K unique pairs triggers ≤ K underlying resolve calls."""
        from resolvekit.core.api.bulk import _bulk_dispatch

        resolver = _make_mock_resolver()
        # 4 rows, only 2 unique (text, country) pairs.
        _bulk_dispatch(
            resolver=resolver,
            values=["Paris", "Paris", "Paris", "Paris"],
            to=None,
            output="series",
            domain=None,
            context={"country": ["FR", "US", "FR", "US"]},
            from_system=None,
            not_found="null",
            on_error="null",
            on_ambiguous="null",
        )
        assert len(resolver._call_log) == 1
        call_texts, _call_ctxs = resolver._call_log[0]
        assert len(call_texts) == 2

    def test_per_row_context_length_mismatch_raises(self) -> None:
        from resolvekit.core.api.bulk import _bulk_dispatch

        resolver = _make_mock_resolver()
        with pytest.raises(ValueError, match="context\\['country'\\] length"):
            _bulk_dispatch(
                resolver=resolver,
                values=["Paris", "Lyon", "Berlin"],
                to=None,
                output="series",
                domain=None,
                context={"country": ["FR", "DE"]},  # length 2 != 3
                from_system=None,
                not_found="null",
                on_error="null",
                on_ambiguous="null",
            )

    def test_crosswalk_plus_per_row_context_raises(self) -> None:
        from resolvekit.core.api.bulk import _bulk_dispatch
        from resolvekit.core.model.crosswalk import Crosswalk

        resolver = _make_mock_resolver()
        cw = Crosswalk({"Paris": "city/PAR_FR"})
        with pytest.raises(ValueError, match="crosswalk="):
            _bulk_dispatch(
                resolver=resolver,
                values=["Paris"],
                to=None,
                output="series",
                domain=None,
                context={"country": ["FR"]},
                from_system=None,
                not_found="null",
                on_error="null",
                on_ambiguous="null",
                crosswalk=cw,
            )

    def test_mixed_scalar_and_per_row_context(self) -> None:
        from resolvekit.core.api.bulk import _bulk_dispatch

        resolver = _make_mock_resolver()
        result = _bulk_dispatch(
            resolver=resolver,
            values=["Paris", "Lyon"],
            to=None,
            output="series",
            domain=None,
            context={
                "country": ["FR", "FR"],
                "entity_types": frozenset({"geo.city"}),  # scalar broadcast
            },
            from_system=None,
            not_found="null",
            on_error="null",
            on_ambiguous="null",
        )
        assert len(result.values) == 2
        # Each row context must carry both country and entity_types.
        _, call_ctxs = resolver._call_log[0]
        for ctx in call_ctxs:
            assert ctx.country == "FR"
            assert ctx.entity_types == frozenset({"geo.city"})

    def test_scalar_set_value_does_not_crash_dedup_signature(self) -> None:
        """Scalar set broadcast values (e.g. entity_types) can be dedup'd by string form."""
        from resolvekit.core.api.bulk import _bulk_dispatch

        resolver = _make_mock_resolver()
        # entity_types is a set (scalar broadcast) alongside per-row country column.
        result = _bulk_dispatch(
            resolver=resolver,
            values=["Paris", "Paris"],
            to=None,
            output="series",
            domain=None,
            context={
                "country": ["FR", "US"],
                "entity_types": {"geo.city"},
            },
            from_system=None,
            not_found="null",
            on_error="null",
            on_ambiguous="null",
        )
        assert len(result.values) == 2

    def test_scalar_dict_attributes_does_not_crash_dedup_signature(self) -> None:
        """Scalar dict broadcast values (e.g. attributes) can be dedup'd by string form."""
        from resolvekit.core.api.bulk import _bulk_dispatch

        resolver = _make_mock_resolver()
        result = _bulk_dispatch(
            resolver=resolver,
            values=["Paris", "Lyon"],
            to=None,
            output="series",
            domain=None,
            context={
                "country": ["FR", "FR"],
                "attributes": {"geo_level": "city"},
            },
            from_system=None,
            not_found="null",
            on_error="null",
            on_ambiguous="null",
        )
        assert len(result.values) == 2

    def test_empty_per_row_context_list_allowed(self) -> None:
        """An empty list context value for an empty values list is valid."""
        from resolvekit.core.api.bulk import _bulk_dispatch

        resolver = _make_mock_resolver()
        result = _bulk_dispatch(
            resolver=resolver,
            values=[],
            to=None,
            output="series",
            domain=None,
            context={"country": []},
            from_system=None,
            not_found="null",
            on_error="null",
            on_ambiguous="null",
        )
        assert list(result.values) == []


# ---------------------------------------------------------------------------
# Pandas accessor — per-row context wiring
# ---------------------------------------------------------------------------


pd = pytest.importorskip("pandas")


class TestPandasAccessorPerRowContext:
    def test_context_kwarg_forwarded_to_bulk_dispatch(self) -> None:
        import resolvekit.pandas  # noqa: F401

        with (
            patch("resolvekit.core.api.bulk._bulk_dispatch") as mock_dispatch,
            patch("resolvekit._convenience._get_default", return_value=MagicMock()),
        ):
            mock_dispatch.return_value = pd.Series(["city/PAR_FR", "city/PAR_TX"])
            s = pd.Series(["Paris", "Paris"])
            iso_series = pd.Series(["FR", "US"])
            s.resolvekit.bulk(context={"country": iso_series})

            kwargs = mock_dispatch.call_args.kwargs
            ctx = kwargs["context"]
            assert isinstance(ctx, dict)
            assert "country" in ctx

    def test_resolve_context_kwarg_forwarded(self) -> None:
        import resolvekit.pandas  # noqa: F401

        with (
            patch("resolvekit.core.api.bulk._bulk_dispatch") as mock_dispatch,
            patch("resolvekit._convenience._get_default", return_value=MagicMock()),
        ):
            mock_dispatch.return_value = pd.Series(["city/PAR_FR"])
            s = pd.Series(["Paris"])
            ctx = ResolutionContext(country="FR")
            s.resolvekit.resolve(to="iso3", context=ctx)

            kwargs = mock_dispatch.call_args.kwargs
            assert kwargs["context"] is ctx


# ---------------------------------------------------------------------------
# Polars accessor — per-row context wiring
# ---------------------------------------------------------------------------


pl = pytest.importorskip("polars")


class TestPolarsAccessorPerRowContext:
    def test_resolve_context_kwarg_accepted(self) -> None:
        import resolvekit.polars  # noqa: F401

        mock_resolver = MagicMock()
        mock_resolver.code_systems.return_value = {"iso3"}
        mock_resolver._runner.available_packs = frozenset()

        with (
            patch("resolvekit.core.api.bulk._bulk_dispatch") as mock_dispatch,
            patch("resolvekit._convenience._get_default", return_value=mock_resolver),
        ):
            mock_dispatch.return_value = pl.Series(values=["city/PAR_FR"])

            df = pl.DataFrame({"city": ["Paris"], "iso": ["FR"]})
            ctx_fr = ResolutionContext(country="FR")
            # Scalar context on uniform path: map_batches dispatches once.
            expr = pl.col("city").resolvekit.resolve(to="iso3", context=ctx_fr)
            df.with_columns(expr)

            assert mock_dispatch.called

    def test_per_row_polars_series_context(self) -> None:
        import resolvekit.polars  # noqa: F401

        mock_resolver = MagicMock()
        mock_resolver.code_systems.return_value = {"iso3"}
        mock_resolver._runner.available_packs = frozenset()

        calls: list[dict] = []

        def _fake_dispatch(**kwargs: Any) -> pl.Series:
            calls.append(kwargs)
            return pl.Series(values=["city/PAR_FR", "city/PAR_TX"])

        with (
            patch(
                "resolvekit.core.api.bulk._bulk_dispatch", side_effect=_fake_dispatch
            ),
            patch("resolvekit._convenience._get_default", return_value=mock_resolver),
        ):
            df = pl.DataFrame({"city": ["Paris", "Paris"], "iso": ["FR", "US"]})
            expr = pl.col("city").resolvekit.resolve(
                to="iso3",
                context={"country": pl.col("iso")},
            )
            df.with_columns(expr)

        assert len(calls) == 1
        ctx_arg = calls[0]["context"]
        # Per-row context must be a dict with "country" key expanded to a list.
        assert isinstance(ctx_arg, dict)
        assert "country" in ctx_arg
        assert list(ctx_arg["country"]) == ["FR", "US"]
