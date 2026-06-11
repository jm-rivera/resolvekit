"""One weakref per batch.

Verifies that ``_resolve_many_internal`` allocates exactly one
``weakref.ref`` object for the entire batch, not one per result.
"""

from __future__ import annotations

import weakref
from unittest.mock import MagicMock

from resolvekit.core.api.resolver import Resolver
from resolvekit.core.model.result import ReasonCode, ResolutionResult, ResolutionStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_resolver() -> Resolver:
    runner = MagicMock()
    runner.available_packs = frozenset({"geo"})
    return Resolver(runner=runner, cache_size=0)


def _no_match(query_text: str | None = None) -> ResolutionResult:
    return ResolutionResult(
        status=ResolutionStatus.NO_MATCH,
        reasons=[ReasonCode.NO_CANDIDATES],
        query_text=query_text,
    )


# ---------------------------------------------------------------------------
# Core test: one weakref per batch
# ---------------------------------------------------------------------------


def test_resolver_alloc_per_batch_one_weakref() -> None:
    """A single ``weakref.ref`` object is reused across all results in one batch.

    Implementation note: we intercept ``_resolve_inner`` to capture the
    ``_self_ref`` kwarg passed down from ``_resolve_many_internal``.
    """
    resolver = _make_resolver()

    captured_refs: list[weakref.ref] = []

    def spy(
        text, *, normalized_domain, context, include_entity, timeout, _self_ref=None
    ):
        if _self_ref is not None:
            captured_refs.append(_self_ref)
        return _no_match(text)

    resolver._resolve_inner = spy  # type: ignore[method-assign]

    texts = ["US", "DE", "FR", "GB", "JP"]
    resolver._resolve_many_internal(texts)

    assert len(captured_refs) == len(texts), "Expected one ref captured per call"
    # All captured refs must be the identical object (same id).
    assert len({id(r) for r in captured_refs}) == 1, (
        "Expected the same weakref.ref instance across the whole batch; "
        f"got {len({id(r) for r in captured_refs})} distinct objects"
    )


def test_resolver_alloc_weakref_is_valid_ref() -> None:
    """The shared weakref.ref resolves back to the resolver."""
    resolver = _make_resolver()

    captured_refs: list[weakref.ref] = []

    def spy(
        text, *, normalized_domain, context, include_entity, timeout, _self_ref=None
    ):
        if _self_ref is not None:
            captured_refs.append(_self_ref)
        return _no_match(text)

    resolver._resolve_inner = spy  # type: ignore[method-assign]
    resolver._resolve_many_internal(["US"])

    assert len(captured_refs) == 1
    assert captured_refs[0]() is resolver


def test_resolver_alloc_different_batches_may_share_or_create() -> None:
    """Two separate ``_resolve_many_internal`` calls each get their own ref."""
    resolver = _make_resolver()

    batch_refs: list[list[weakref.ref]] = []
    current_batch: list[weakref.ref] = []

    def spy(
        text, *, normalized_domain, context, include_entity, timeout, _self_ref=None
    ):
        if _self_ref is not None:
            current_batch.append(_self_ref)
        return _no_match(text)

    resolver._resolve_inner = spy  # type: ignore[method-assign]

    resolver._resolve_many_internal(["US", "DE"])
    batch_refs.append(list(current_batch))
    current_batch.clear()

    resolver._resolve_many_internal(["FR", "JP"])
    batch_refs.append(list(current_batch))
    current_batch.clear()

    # Each batch has one distinct ref object used throughout.
    for batch in batch_refs:
        assert len({id(r) for r in batch}) == 1


def test_resolve_inner_sets_resolver_ref_on_result() -> None:
    """``_resolve_inner`` sets ``result._explainer`` after model_copy."""
    from resolvekit.core.model.result import (
        ReasonCode,
        ResolutionResult,
        ResolutionStatus,
    )

    runner = MagicMock()
    runner.available_packs = frozenset({"geo"})
    resolver = Resolver(runner=runner, cache_size=0)

    # Make runner.resolve return a bare result (no _explainer set).
    bare = ResolutionResult(
        status=ResolutionStatus.NO_MATCH,
        reasons=[ReasonCode.NO_CANDIDATES],
    )
    runner.resolve.return_value = bare

    result = resolver._resolve_inner(
        "US",
        normalized_domain=None,
        context=None,
        include_entity=False,
        timeout=None,
    )
    # After _resolve_inner, _explainer should be set.
    assert result._explainer is not None
    assert result._explainer() is resolver
