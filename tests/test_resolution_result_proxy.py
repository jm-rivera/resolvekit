"""Tests for ResolutionResult proxy attributes, explain(), to_dict(), to_json().

Covers result.explain() and proxy attributes on result.
"""

from __future__ import annotations

import json

import pytest

from resolvekit.core.errors_base import ExplainNotAvailableError
from resolvekit.core.model.entity import CodeRecord, EntityRecord
from resolvekit.core.model.result import ResolutionResult, ResolutionStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(
    *,
    entity_id: str = "country/USA",
    canonical_name: str = "United States",
    iso2: str | None = "US",
    iso3: str | None = "USA",
) -> EntityRecord:
    codes: list[CodeRecord] = []
    for system, value in (("iso2", iso2), ("iso3", iso3)):
        if value is not None:
            codes.append(
                CodeRecord(system=system, value=value, value_norm=value.lower())
            )
    return EntityRecord(
        entity_id=entity_id,
        entity_type="geo.country",
        canonical_name=canonical_name,
        canonical_name_norm=canonical_name.lower(),
        codes=codes,
    )


def _resolved_result(*, include_entity: bool = True) -> ResolutionResult:
    entity = _make_entity() if include_entity else None
    return ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        entity_id="country/USA",
        entity=entity,
        confidence=0.99,
        pack_id="geo",
        query_text="United States",
    )


def _no_match_result() -> ResolutionResult:
    return ResolutionResult(
        status=ResolutionStatus.NO_MATCH,
        query_text="Atlantis",
    )


# ---------------------------------------------------------------------------
# Proxy properties
# ---------------------------------------------------------------------------


def test_result_iso3_via_entity_proxy() -> None:
    """When entity is present, result.iso3 == result.entity.iso3."""
    result = _resolved_result(include_entity=True)
    assert result.iso3 == result.entity.iso3  # type: ignore[union-attr]
    assert result.iso3 == "USA"


def test_result_iso2_via_entity_proxy() -> None:
    """When entity is present, result.iso2 == result.entity.iso2."""
    result = _resolved_result(include_entity=True)
    assert result.iso2 == result.entity.iso2  # type: ignore[union-attr]
    assert result.iso2 == "US"


def test_result_name_via_entity_proxy() -> None:
    """When entity is present, result.name == entity.canonical_name."""
    result = _resolved_result(include_entity=True)
    assert result.name == "United States"


def test_result_flag_via_entity_proxy() -> None:
    """When entity is present, result.flag proxies entity.flag."""
    result = _resolved_result(include_entity=True)
    # US flag = regional indicator U + S
    assert result.flag == "\U0001f1fa\U0001f1f8"


def test_result_iso3_none_when_no_entity() -> None:
    """When entity is not populated, result.iso3 is None."""
    result = _resolved_result(include_entity=False)
    assert result.entity is None
    assert result.iso3 is None


def test_result_iso2_none_when_no_entity() -> None:
    """When entity is not populated, result.iso2 is None."""
    result = _resolved_result(include_entity=False)
    assert result.iso2 is None


def test_result_name_none_when_no_entity() -> None:
    """When entity is not populated, result.name is None."""
    result = _resolved_result(include_entity=False)
    assert result.name is None


def test_result_flag_none_when_no_entity() -> None:
    """When entity is not populated, result.flag is None."""
    result = _resolved_result(include_entity=False)
    assert result.flag is None


def test_result_proxies_none_on_no_match() -> None:
    """NO_MATCH results have no entity so all proxies are None."""
    result = _no_match_result()
    assert result.iso2 is None
    assert result.iso3 is None
    assert result.name is None
    assert result.flag is None


# ---------------------------------------------------------------------------
# explain() raises when detached
# ---------------------------------------------------------------------------


def test_result_explain_raises_when_detached() -> None:
    """ResolutionResult().explain() raises ExplainNotAvailableError when no resolver."""
    result = _resolved_result()
    with pytest.raises(ExplainNotAvailableError):
        result.explain()


def test_result_explain_raises_with_default_hint() -> None:
    """ExplainNotAvailableError carries a helpful hint."""
    result = _resolved_result()
    with pytest.raises(ExplainNotAvailableError) as exc_info:
        result.explain()
    assert exc_info.value.hint is not None
    assert "resolver" in exc_info.value.hint


def test_result_explain_raises_when_query_text_none() -> None:
    """explain() raises ExplainNotAvailableError when query_text is None (no resolver)."""
    result = ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        entity_id="country/USA",
        confidence=0.99,
    )
    with pytest.raises(ExplainNotAvailableError):
        result.explain()


# ---------------------------------------------------------------------------
# Serialisation: to_dict() / to_json()
# ---------------------------------------------------------------------------


def test_result_to_dict_contains_status() -> None:
    """to_dict() returns a dict with 'status' key."""
    result = _resolved_result()
    d = result.to_dict()
    assert isinstance(d, dict)
    assert d["status"] == "resolved"


def test_result_to_dict_contains_entity_id() -> None:
    """to_dict() includes entity_id when present."""
    result = _resolved_result()
    assert result.to_dict()["entity_id"] == "country/USA"


def test_result_to_json_round_trip() -> None:
    """to_json() produces valid JSON that round-trips the entity_id."""
    result = _resolved_result()
    raw = result.to_json()
    parsed = json.loads(raw)
    assert parsed["entity_id"] == "country/USA"
    assert parsed["status"] == "resolved"


def test_result_to_json_indent_produces_multiline() -> None:
    """to_json(indent=2) produces indented multi-line JSON."""
    result = _resolved_result()
    raw = result.to_json(indent=2)
    assert "\n" in raw
    parsed = json.loads(raw)
    assert parsed["status"] == "resolved"


def test_result_to_dict_no_mutation() -> None:
    """to_dict() returns a plain dict; modifying it doesn't affect the result."""
    result = _resolved_result()
    d = result.to_dict()
    d["status"] = "mutated"
    assert result.status == ResolutionStatus.RESOLVED


# ---------------------------------------------------------------------------
# _explainer PrivateAttr exists and is not in model_dump
# ---------------------------------------------------------------------------


def test_result_resolver_private_attr_not_in_dump() -> None:
    """_explainer PrivateAttr does not appear in model_dump() output."""
    result = _resolved_result()
    d = result.to_dict()
    assert "_explainer" not in d
    assert "_resolver" not in d
    assert "resolver" not in d


def test_result_resolver_private_attr_default_none() -> None:
    """_explainer defaults to None on a freshly constructed result."""
    result = _resolved_result()
    # Access via private attr — pydantic stores it via __private_attributes__
    assert result._explainer is None
