"""Tests for Resolver.resolve(to=) pivot collapse.

Verifies that:
- ``resolve("US", to="iso3")`` auto-detects iso2 and returns "USA"
- ``resolve("United States", to="iso3")`` returns "USA"
- ``resolve(["US"])`` raises TypeError with hint
- ``resolve(text, to="iso3")`` returns None for NO_MATCH
- AMBIGUOUS + to= raises AmbiguousResolutionError
- get_entity removed, translate removed, resolve_many removed
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from resolvekit.core.api.resolver import Resolver
from resolvekit.core.model.entity import CodeRecord, EntityRecord
from resolvekit.core.model.result import (
    CandidateSummary,
    ReasonCode,
    ResolutionResult,
    ResolutionStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(
    entity_id: str = "country/USA",
    iso2: str = "US",
    iso3: str = "USA",
) -> EntityRecord:
    return EntityRecord(
        entity_id=entity_id,
        entity_type="geo.country",
        canonical_name="United States",
        canonical_name_norm="united states",
        codes=[
            CodeRecord(system="iso3", value=iso3, value_norm=iso3.lower()),
            CodeRecord(system="iso2", value=iso2, value_norm=iso2.lower()),
        ],
    )


def _resolved_result(entity: EntityRecord) -> ResolutionResult:
    return ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        entity_id=entity.entity_id,
        entity=entity,
        reasons=[ReasonCode.EXACT_NAME_MATCH],
    )


def _make_resolver_with_result(result: ResolutionResult) -> Resolver:
    runner = MagicMock()
    runner.available_packs = frozenset({"geo"})
    resolver = Resolver(runner=runner, cache_size=0)
    resolver._resolve_inner = MagicMock(return_value=result)  # type: ignore[method-assign]
    return resolver


# ---------------------------------------------------------------------------
# Collapse: resolve("United States", to="iso3") -> "USA"
# ---------------------------------------------------------------------------


def test_resolve_to_iso3_returns_string() -> None:
    """``resolve("United States", to="iso3")`` returns the ISO 3 string."""
    entity = _make_entity()
    result = _resolved_result(entity)
    resolver = _make_resolver_with_result(result)
    value = resolver.resolve("United States", to="iso3")
    assert value == "USA"


def test_resolve_to_iso2_returns_string() -> None:
    """``resolve("United States", to="iso2")`` returns the ISO 2 string."""
    entity = _make_entity()
    result = _resolved_result(entity)
    resolver = _make_resolver_with_result(result)
    value = resolver.resolve("United States", to="iso2")
    assert value == "US"


def test_resolve_to_none_returns_result_object() -> None:
    """``resolve("United States")`` returns a :class:`ResolutionResult`."""
    entity = _make_entity()
    result = _resolved_result(entity)
    resolver = _make_resolver_with_result(result)
    value = resolver.resolve("United States")
    assert isinstance(value, ResolutionResult)


# ---------------------------------------------------------------------------
# resolve(text, to=) on non-match: returns None
# ---------------------------------------------------------------------------


def test_resolve_to_iso3_no_match_returns_none() -> None:
    """``resolve("Atlantis", to="iso3")`` returns None for NO_MATCH."""
    no_match = ResolutionResult(
        status=ResolutionStatus.NO_MATCH,
        reasons=[ReasonCode.NO_CANDIDATES],
    )
    resolver = _make_resolver_with_result(no_match)
    assert resolver.resolve("Atlantis", to="iso3") is None


# ---------------------------------------------------------------------------
# TypeError on list input
# ---------------------------------------------------------------------------


def test_resolve_with_list_input_raises_typeerror_with_hint() -> None:
    """``resolve(["US"])`` raises ``TypeError`` with a `.hint`."""
    runner = MagicMock()
    runner.available_packs = frozenset({"geo"})
    resolver = Resolver(runner=runner, cache_size=0)
    with pytest.raises(TypeError) as exc_info:
        resolver.resolve(["US"])  # type: ignore[arg-type]
    err = exc_info.value
    assert hasattr(err, "hint")
    assert "bulk" in err.hint  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# AMBIGUOUS + to= raises
# ---------------------------------------------------------------------------


def test_resolve_to_iso3_ambiguous_raises() -> None:
    """``resolve("EU", to="iso3")`` raises ``AmbiguousResolutionError``."""
    from resolvekit.core.errors import AmbiguousResolutionError

    ambiguous = ResolutionResult(
        status=ResolutionStatus.AMBIGUOUS,
        candidates=[
            CandidateSummary(entity_id="country/EU"),
            CandidateSummary(entity_id="org/EU"),
        ],
        reasons=[ReasonCode.AMBIGUOUS_DOMAIN_COLLISION],
    )
    resolver = _make_resolver_with_result(ambiguous)
    with pytest.raises(AmbiguousResolutionError):
        resolver.resolve("EU", to="iso3")


# ---------------------------------------------------------------------------
# Auto-detect from_system via code-shape
# ---------------------------------------------------------------------------


def test_resolve_code_input_auto_detect_iso2_to_iso3() -> None:
    """``resolve("US", to="iso3")`` with no from_system returns "USA"."""
    entity = _make_entity()

    runner = MagicMock()
    runner.available_packs = frozenset({"geo"})
    # CodeLookup calls runner.available_code_systems (not resolver.code_systems)
    # to determine which code systems to probe in priority order.
    runner.available_code_systems = frozenset({"iso2", "iso3"})
    runner.lookup_code.return_value = ["country/USA"]
    runner.get_entity.return_value = entity

    resolver = Resolver(runner=runner, cache_size=0)

    result = resolver.resolve("US", to="iso3")
    assert result == "USA"


# ---------------------------------------------------------------------------
# Removed API assertions
# ---------------------------------------------------------------------------


def test_resolver_get_entity_removed() -> None:
    """``resolver.get_entity`` must NOT exist."""
    runner = MagicMock()
    resolver = Resolver(runner=runner, cache_size=0)
    assert not hasattr(resolver, "get_entity"), (
        "get_entity should be removed; use resolver.entity() instead"
    )


def test_resolver_translate_removed() -> None:
    """``resolver.translate`` must NOT exist."""
    runner = MagicMock()
    resolver = Resolver(runner=runner, cache_size=0)
    assert not hasattr(resolver, "translate"), (
        "translate should be removed; use resolve(text, to=...) instead"
    )


def test_resolver_resolve_many_removed() -> None:
    """``resolver.resolve_many`` must NOT exist as public API."""
    runner = MagicMock()
    resolver = Resolver(runner=runner, cache_size=0)
    public_methods = {name for name in dir(resolver) if not name.startswith("_")}
    assert "resolve_many" not in public_methods, (
        "resolve_many should be removed; use resolver.bulk() instead"
    )


def test_resolver_resolve_explained_exists_and_backs_explainer() -> None:
    """``resolver.resolve_explained`` exists and is documented as backing result.explain()."""
    runner = MagicMock()
    resolver = Resolver(runner=runner, cache_size=0)
    assert hasattr(resolver, "resolve_explained"), (
        "resolve_explained must exist — result.explain() calls it internally"
    )
    doc = getattr(resolver.resolve_explained, "__doc__", "") or ""
    # AX2: docstring must acknowledge it backs result.explain() AND the Explainer protocol.
    assert "result.explain()" in doc, (
        "resolve_explained docstring must reference result.explain() — "
        "callers should use that instead of calling this directly"
    )
    assert "Explainer" in doc, (
        "resolve_explained docstring must acknowledge it satisfies the Explainer protocol"
    )


def test_resolver_resolve_series_removed() -> None:
    """``resolver.resolve_series`` must NOT exist."""
    runner = MagicMock()
    resolver = Resolver(runner=runner, cache_size=0)
    assert not hasattr(resolver, "resolve_series"), (
        "resolve_series should be removed; use resolver.bulk() instead"
    )


def test_resolver_resolve_series_explained_removed() -> None:
    """``resolver.resolve_series_explained`` must NOT exist."""
    runner = MagicMock()
    resolver = Resolver(runner=runner, cache_size=0)
    assert not hasattr(resolver, "resolve_series_explained"), (
        "resolve_series_explained should be removed; use bulk(output='frame') instead"
    )


# ---------------------------------------------------------------------------
# resolve_id with on_ambiguous
# ---------------------------------------------------------------------------


def test_resolve_id_on_ambiguous_null_returns_none() -> None:
    """``resolve_id(text, on_ambiguous='null')`` returns ``None`` on AMBIGUOUS."""
    ambiguous = ResolutionResult(
        status=ResolutionStatus.AMBIGUOUS,
        candidates=[CandidateSummary(entity_id="country/EU")],
        reasons=[ReasonCode.AMBIGUOUS_LOW_GAP],
    )
    resolver = _make_resolver_with_result(ambiguous)
    result = resolver.resolve_id("EU", on_ambiguous="null")
    assert result is None


def test_resolve_id_on_ambiguous_best_returns_top_entity_id() -> None:
    """``resolve_id(text, on_ambiguous='best')`` returns top candidate's ID."""
    ambiguous = ResolutionResult(
        status=ResolutionStatus.AMBIGUOUS,
        candidates=[
            CandidateSummary(entity_id="country/EU", confidence=0.9),
            CandidateSummary(entity_id="org/EU", confidence=0.7),
        ],
        reasons=[ReasonCode.AMBIGUOUS_LOW_GAP],
    )
    resolver = _make_resolver_with_result(ambiguous)
    result = resolver.resolve_id("EU", on_ambiguous="best")
    assert result == "country/EU"


def test_resolve_id_on_ambiguous_raise_default() -> None:
    """``resolve_id(text)`` (default) raises ``AmbiguousResolutionError``."""
    from resolvekit.core.errors import AmbiguousResolutionError

    ambiguous = ResolutionResult(
        status=ResolutionStatus.AMBIGUOUS,
        candidates=[CandidateSummary(entity_id="country/EU")],
        reasons=[ReasonCode.AMBIGUOUS_LOW_GAP],
    )
    resolver = _make_resolver_with_result(ambiguous)
    with pytest.raises(AmbiguousResolutionError):
        resolver.resolve_id("EU")
