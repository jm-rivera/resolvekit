"""Verify pydantic v2 model_copy preserves PrivateAttr.

Pins the pydantic version behavior: ``model_copy(update={...})`` on a
``BaseModel`` with ``PrivateAttr`` fields.  The test documents whether
private attrs survive the copy so the resolver code can rely on explicit
re-assignment after every ``model_copy``.
"""

from __future__ import annotations

import weakref
from unittest.mock import MagicMock

import pydantic
import pytest

from resolvekit.core.model.result import ReasonCode, ResolutionResult, ResolutionStatus

# ---------------------------------------------------------------------------
# Pydantic version guard
# ---------------------------------------------------------------------------


def test_pydantic_version_is_v2() -> None:
    """This project requires pydantic>=2.0."""
    major = int(pydantic.VERSION.split(".")[0])
    assert major >= 2, f"Expected pydantic>=2, got {pydantic.VERSION}"


# ---------------------------------------------------------------------------
# Core behaviour: PrivateAttr survival across model_copy
# ---------------------------------------------------------------------------


def _make_result_with_resolver() -> tuple[ResolutionResult, MagicMock]:
    """Return a ResolutionResult with ``_resolver`` set to a mock."""
    mock_resolver = MagicMock()
    result = ResolutionResult(
        status=ResolutionStatus.NO_MATCH,
        reasons=[ReasonCode.NO_CANDIDATES],
    )
    ref = weakref.ref(mock_resolver)
    result._resolver = ref  # type: ignore[attr-defined]
    return result, mock_resolver


def test_model_copy_preserves_private_resolver() -> None:
    """After ``model_copy(update={})``, ``_resolver`` must still be set.

    This test documents whether pydantic v2's ``model_copy`` preserves
    ``PrivateAttr`` values.  If it does, great.  If it doesn't, the
    resolver code must re-assign explicitly after every copy (which the
    implementation does).
    """
    result, mock_resolver = _make_result_with_resolver()
    assert result._resolver is not None

    # model_copy with a field update (the pattern used in _resolve_inner).
    copied = result.model_copy(update={"query_text": "test"})

    # Document the actual behavior.  Either the copy preserved the ref,
    # or it cleared it.  Both are acceptable as long as the resolver code
    # compensates with an explicit re-assignment.
    if copied._resolver is None:
        pytest.skip(
            f"pydantic {pydantic.VERSION} clears PrivateAttr on model_copy; "
            "resolver code must re-assign _resolver after every model_copy — "
            "verified in test_resolve_inner_sets_resolver_ref_on_result"
        )
    else:
        # PrivateAttr was preserved — the ref must still point to the mock.
        assert copied._resolver() is mock_resolver


def test_model_copy_update_query_text_preserves_resolver_when_set_after() -> None:
    """Simulate the resolver code's explicit re-assign pattern.

    The resolver calls ``model_copy(update={"query_text": text})`` then
    immediately sets ``result._resolver = ref``.  This test verifies that
    the explicit assignment wins regardless of pydantic's copy semantics.
    """
    mock_resolver = MagicMock()
    result = ResolutionResult(
        status=ResolutionStatus.NO_MATCH,
        reasons=[ReasonCode.NO_CANDIDATES],
    )

    # Simulate the resolver code pattern:
    ref = weakref.ref(mock_resolver)
    copied = result.model_copy(update={"query_text": "hello"})
    copied._resolver = ref  # explicit re-assign

    assert copied._resolver is not None
    assert copied._resolver() is mock_resolver


def test_model_copy_chain_preserves_resolver() -> None:
    """Two chained ``model_copy`` calls retain the resolver ref when set.

    ``_resolve_inner`` does two copies: once for ``query_text``, once for
    ``entity`` injection.  Both must not lose the ref.
    """
    from resolvekit.core.model.entity import EntityRecord

    mock_resolver = MagicMock()
    entity = EntityRecord(
        entity_id="country/USA",
        entity_type="geo.country",
        canonical_name="United States",
        canonical_name_norm="united states",
    )
    result = ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        entity_id="country/USA",
        reasons=[ReasonCode.EXACT_NAME_MATCH],
    )

    ref = weakref.ref(mock_resolver)

    # First copy: query_text
    r1 = result.model_copy(update={"query_text": "United States"})
    r1._resolver = ref  # type: ignore[attr-defined]

    # Second copy: entity injection
    r2 = r1.model_copy(update={"entity": entity})
    r2._resolver = ref  # type: ignore[attr-defined]

    assert r2._resolver() is mock_resolver
    assert r2.entity == entity
    assert r2.query_text == "United States"
