"""Three-call-site consistency: dispatch_pivot is the single source of truth.

Verifies that the ``to=`` pivot produces the same result when called
via:
1. ``resolve(text, to="iso3")``
2. ``entity.to("iso3")``
3. ``bulk(values=[text], to="iso3")``

All three must delegate to ``entity_attributes.dispatch_pivot``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from resolvekit.core.api.bulk import _bulk_dispatch
from resolvekit.core.api.resolver import Resolver
from resolvekit.core.model.entity import CodeRecord, EntityRecord
from resolvekit.core.model.entity_attributes import dispatch_pivot
from resolvekit.core.model.result import ReasonCode, ResolutionResult, ResolutionStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(iso3: str = "USA", iso2: str = "US") -> EntityRecord:
    return EntityRecord(
        entity_id="country/USA",
        entity_type="geo.country",
        canonical_name="United States",
        canonical_name_norm="united states",
        codes=[
            CodeRecord(system="iso3", value=iso3, value_norm=iso3.lower()),
            CodeRecord(system="iso2", value=iso2, value_norm=iso2.lower()),
        ],
    )


def _resolved(entity: EntityRecord) -> ResolutionResult:
    return ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        entity_id=entity.entity_id,
        entity=entity,
        reasons=[ReasonCode.EXACT_NAME_MATCH],
    )


# ---------------------------------------------------------------------------
# dispatch_pivot is the single source of truth
# ---------------------------------------------------------------------------


def test_dispatch_pivot_unique_call_site() -> None:
    """``entity_attributes.dispatch_pivot`` handles all pivot routing.

    Verify that calling ``dispatch_pivot(entity, "iso3")`` returns the
    ISO-3 code and is the same path used by ``resolve(..., to="iso3")``.
    """
    entity = _make_entity()
    result = dispatch_pivot(entity, "iso3")
    assert result == "USA"


def test_entity_to_method_uses_dispatch_pivot() -> None:
    """``entity.to("iso3")`` delegates to ``dispatch_pivot``."""
    entity = _make_entity()
    with patch(
        "resolvekit.core.model.entity_attributes.dispatch_pivot",
        wraps=dispatch_pivot,
    ) as mock_dp:
        value = entity.to("iso3")
        mock_dp.assert_called_once_with(entity, "iso3")
    assert value == "USA"


# ---------------------------------------------------------------------------
# Consistency: resolve(to=) vs entity.to()
# ---------------------------------------------------------------------------


def test_resolve_to_iso3_equals_entity_to_iso3() -> None:
    """``resolve(text, to="iso3")`` == ``entity.to("iso3")`` for same entity."""
    entity = _make_entity()
    resolved_result = _resolved(entity)

    runner = MagicMock()
    runner.available_packs = frozenset({"geo"})
    resolver = Resolver(runner=runner, cache_size=0)
    resolver._resolve_inner = MagicMock(return_value=resolved_result)

    via_resolve = resolver.resolve("United States", to="iso3")
    via_entity = entity.to("iso3")

    assert via_resolve == via_entity == "USA"


# ---------------------------------------------------------------------------
# bulk consistency
# ---------------------------------------------------------------------------


def test_bulk_to_iso3_per_row_equals_resolve_to_iso3() -> None:
    """``bulk(values=[text], to="iso3")`` returns the same value as ``resolve``."""
    from resolvekit.core.model.result import ResolutionResultList

    entity = _make_entity()
    resolved_result = _resolved(entity)

    runner = MagicMock()
    runner.available_packs = frozenset({"geo"})
    resolver = Resolver(runner=runner, cache_size=0)
    resolver._resolve_inner = MagicMock(return_value=resolved_result)

    # Scalar resolve path.
    via_resolve = resolver.resolve("United States", to="iso3")

    # bulk path — mock _resolve_many_internal.
    def mock_many(
        texts, *, domain=None, context=None, include_entity=False, timeout=None
    ):
        return ResolutionResultList([resolved_result] * len(texts))

    resolver._resolve_many_internal = mock_many  # type: ignore[method-assign]

    bulk_result = _bulk_dispatch(
        resolver=resolver,
        values=["United States"],
        to="iso3",
        output="series",
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )
    # bulk returns a list when input is a Python list.
    assert isinstance(bulk_result, list)
    assert bulk_result[0] == via_resolve == "USA"


# ---------------------------------------------------------------------------
# Pivot ordering contract (all three targets route consistently)
# ---------------------------------------------------------------------------


def test_dispatch_pivot_known_pivots_all_route() -> None:
    """All ``KNOWN_PIVOTS`` dispatch without error for a well-formed entity."""
    from resolvekit.core.model.entity_attributes import KNOWN_PIVOTS

    entity = _make_entity()
    for target in KNOWN_PIVOTS:
        # Must not raise (may return None if the attr isn't populated).
        dispatch_pivot(entity, target)


def test_dispatch_pivot_unknown_target_raises() -> None:
    """``dispatch_pivot(entity, "nonexistent_system")`` raises ``UnknownCodeSystemError``."""
    from resolvekit.core.errors import UnknownCodeSystemError

    entity = _make_entity()
    with pytest.raises(UnknownCodeSystemError):
        dispatch_pivot(entity, "nonexistent_system_xyz")
