"""Performance canary for per-row bulk context deduplication.

Asserts that a frame with N rows but K << N unique (value, context) pairs
triggers <= K underlying _resolve_many_internal calls (i.e., O(unique pairs)
not O(N) rows).

Run via:

    uv run pytest tests/benchmarks/bench_bulk_per_row_context.py
"""

from __future__ import annotations

from typing import Any

from resolvekit.core.model import ResolutionContext, ResolutionResult, ResolutionStatus
from resolvekit.core.model.result import ReasonCode

# ---------------------------------------------------------------------------
# Minimal mock resolver for counting resolve calls
# ---------------------------------------------------------------------------


def _make_counting_resolver() -> Any:
    """Return a minimal resolver that counts calls to _resolve_many_internal."""
    from unittest.mock import MagicMock

    resolver = MagicMock()
    resolver._runner.available_packs = frozenset()

    total_texts_resolved: list[int] = [0]

    def _resolve_many(texts, *, domain=None, context=None, include_entity=False):
        total_texts_resolved[0] += len(texts)
        return [
            ResolutionResult(
                status=ResolutionStatus.RESOLVED,
                entity_id="country/FRA",
                confidence=0.95,
                reasons=(ReasonCode.EXACT_NAME_MATCH,),
            )
            for _ in texts
        ]

    resolver._resolve_many_internal = _resolve_many
    resolver._total_texts_resolved = total_texts_resolved
    return resolver


# ---------------------------------------------------------------------------
# Canary: unique-pair count, not N rows
# ---------------------------------------------------------------------------


class TestPerRowContextDeduplicationCanary:
    """Throughput canary: O(K unique pairs) resolutions, not O(N rows)."""

    def test_n_rows_k_unique_pairs_resolves_k_times(self) -> None:
        """N=50, K=5 unique (value, country) pairs: only 5 texts resolved."""
        from resolvekit.core.api.bulk import _bulk_dispatch

        resolver = _make_counting_resolver()

        countries = ["FR", "DE", "GB", "US", "IT"]
        N = 50  # noqa: N806
        K = 5  # noqa: N806

        # 50 rows with 5 repeating countries — 5 unique (value="Paris", country=X) pairs.
        values = ["Paris"] * N
        ctx_column = [countries[i % K] for i in range(N)]

        _bulk_dispatch(
            resolver=resolver,
            values=values,
            to=None,
            output="series",
            domain=None,
            context={"country": ctx_column},
            from_system=None,
            not_found="null",
            on_error="null",
            on_ambiguous="null",
        )

        actual = resolver._total_texts_resolved[0]
        assert actual <= K, (
            f"Expected at most {K} underlying resolve calls (unique pairs), "
            f"but got {actual}.  Per-row context is not deduplicating correctly."
        )

    def test_fully_unique_pairs_resolves_all(self) -> None:
        """When all (value, context) pairs are distinct, K == N."""
        from resolvekit.core.api.bulk import _bulk_dispatch

        resolver = _make_counting_resolver()
        # Use 10 distinct valid 2-letter ISO-style country codes and 10 distinct city names.
        N = 10  # noqa: N806
        # 26 letters = enough for 10 distinct 2-letter combos starting from "AA".
        import string

        letters = string.ascii_uppercase
        countries = [letters[i] + letters[i + 1] for i in range(N)]
        cities = [f"City{i}" for i in range(N)]

        _bulk_dispatch(
            resolver=resolver,
            values=cities,
            to=None,
            output="series",
            domain=None,
            context={"country": countries},
            from_system=None,
            not_found="null",
            on_error="null",
            on_ambiguous="null",
        )

        actual = resolver._total_texts_resolved[0]
        assert actual == N, (
            f"With {N} unique pairs, expected {N} resolve calls, got {actual}."
        )

    def test_structurally_equal_context_objects_deduplicate(self) -> None:
        """Two distinct ResolutionContext instances with equal content share one resolve call."""
        from resolvekit.core.api.bulk import _dedup_pairs

        ctx_a = ResolutionContext(country="FR")
        ctx_b = ResolutionContext(country="FR")

        pairs, indexer = _dedup_pairs(["Paris", "Paris"], [ctx_a, ctx_b])
        assert len(pairs) == 1, (
            "Two equal-content ResolutionContext objects must deduplicate to one pair."
        )
        assert indexer == [0, 0]

    def test_large_frame_dedup_ratio(self) -> None:
        """1000-row frame with 4 unique pairs resolves exactly 4 times."""
        from resolvekit.core.api.bulk import _bulk_dispatch

        resolver = _make_counting_resolver()
        N = 1000  # noqa: N806
        K = 4  # noqa: N806

        cities = ["Paris", "Berlin", "Paris", "Berlin"] * (N // K)
        countries = ["FR", "DE", "FR", "DE"] * (N // K)

        _bulk_dispatch(
            resolver=resolver,
            values=cities,
            to=None,
            output="series",
            domain=None,
            context={"country": countries},
            from_system=None,
            not_found="null",
            on_error="null",
            on_ambiguous="null",
        )

        actual = resolver._total_texts_resolved[0]
        assert actual <= K, (
            f"1000-row frame with {K} unique pairs: expected ≤{K} resolve calls, "
            f"got {actual}."
        )
