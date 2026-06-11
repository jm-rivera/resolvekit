"""Integration tests for continental_union alias coverage.

Verifies that the v4 eval rows and canonical-name query forms all resolve
correctly after the alias-coverage fix.  These tests require the
geo.continental_unions data pack to be present locally.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Module-level guard
# ---------------------------------------------------------------------------


def _pack_available() -> bool:
    try:
        from resolvekit import Resolver

        r = Resolver.from_modules(module_ids=["geo.continental_unions"])
        try:
            return len(r.known_groups()) > 0
        finally:
            r.close()
    except Exception:
        return False


_PACK_AVAILABLE = _pack_available()
pytestmark = pytest.mark.skipif(
    not _PACK_AVAILABLE,
    reason="geo.continental_unions pack not available locally",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cu_resolver():  # type: ignore[no-untyped-def]
    from resolvekit import Resolver

    r = Resolver.from_modules(module_ids=["geo.continental_unions"])
    yield r
    r.close()


@pytest.fixture(scope="module")
def full_resolver():  # type: ignore[no-untyped-def]
    """Full stack: countries + regions + continental_unions."""
    from resolvekit import Resolver

    try:
        r = Resolver.from_modules(
            module_ids=["geo.countries", "geo.regions", "geo.continental_unions"]
        )
        yield r
        r.close()
    except Exception:
        pytest.skip("geo.countries or geo.regions not available")


# ---------------------------------------------------------------------------
# V4 eval rows — continental_union category (12 rows)
# Comma-separated expected = ANY one of those IDs counts as correct.
# ---------------------------------------------------------------------------

_V4_CONTINENTAL_UNION_CASES = [
    # (query_text, acceptable_entity_ids)
    ("European Union", {"EuropeanUnion", "groups/EU27_2020"}),
    ("EU", {"EuropeanUnion", "groups/EU27_2020"}),
    ("African Union", {"groups/AU"}),
    ("ASEAN", {"groups/ASEAN"}),
    ("NATO", {"groups/NATO"}),
    ("OPEC", {"groups/OPEC"}),
    ("BRICS", {"groups/BRICS"}),
    ("G7", {"groups/G7"}),
    ("G20", {"groups/G20"}),
    ("MERCOSUR", {"groups/MERCOSUR"}),
    ("Commonwealth", {"groups/Commonwealth"}),
]


@pytest.mark.integration
@pytest.mark.parametrize(
    "query,expected_ids",
    _V4_CONTINENTAL_UNION_CASES,
    ids=[c[0] for c in _V4_CONTINENTAL_UNION_CASES],
)
def test_v4_eval_continental_union_cu_only(
    cu_resolver,  # type: ignore[no-untyped-def]
    query: str,
    expected_ids: set[str],
) -> None:
    """V4 eval continental_union rows resolve correctly (continental_unions only)."""
    result = cu_resolver.resolve(query)
    assert result.is_resolved, (
        f"{query!r}: expected RESOLVED but got {result.status.value!r}"
    )
    assert result.entity_id in expected_ids, (
        f"{query!r}: got {result.entity_id!r}, expected one of {expected_ids}"
    )


# ---------------------------------------------------------------------------
# World-region rows that target continental_union entities (3 rows)
# ---------------------------------------------------------------------------

_V4_WORLD_REGION_CU_CASES = [
    ("LDCs", "groups/UN.LDC"),
    ("Least Developed Countries", "groups/UN.LDC"),
    ("SIDS", "groups/UN.SIDS"),
]


@pytest.mark.integration
@pytest.mark.parametrize(
    "query,expected_id",
    _V4_WORLD_REGION_CU_CASES,
    ids=[c[0] for c in _V4_WORLD_REGION_CU_CASES],
)
def test_v4_world_region_cu_entities(
    cu_resolver,  # type: ignore[no-untyped-def]
    query: str,
    expected_id: str,
) -> None:
    """World-region rows that target continental_union entities resolve correctly."""
    result = cu_resolver.resolve(query)
    assert result.is_resolved, (
        f"{query!r}: expected RESOLVED but got {result.status.value!r}"
    )
    assert result.entity_id == expected_id, (
        f"{query!r}: got {result.entity_id!r}, expected {expected_id!r}"
    )


# ---------------------------------------------------------------------------
# Canonical full-name queries
# ---------------------------------------------------------------------------

_CANONICAL_NAME_CASES = [
    ("North Atlantic Treaty Organization", "groups/NATO"),
    ("Association of Southeast Asian Nations", "groups/ASEAN"),
    ("Organization of the Petroleum Exporting Countries", "groups/OPEC"),
    ("Organisation for Economic Co-operation and Development", "groups/OECD"),
    ("Organization for Economic Co-operation and Development", "groups/OECD"),
    ("Southern Common Market", "groups/MERCOSUR"),
    ("European Economic Area", "groups/EEA"),
    ("OECD Development Assistance Committee", "groups/OECD.DAC"),
    ("World Bank High-Income Countries", "groups/WB.IncomeGroup.High"),
    ("World Bank Low-Income Countries", "groups/WB.IncomeGroup.Low"),
    ("World Bank Lower-Middle-Income Countries", "groups/WB.IncomeGroup.LowerMiddle"),
    ("World Bank Upper-Middle-Income Countries", "groups/WB.IncomeGroup.UpperMiddle"),
]


@pytest.mark.integration
@pytest.mark.parametrize(
    "query,expected_id",
    _CANONICAL_NAME_CASES,
    ids=[c[0] for c in _CANONICAL_NAME_CASES],
)
def test_canonical_name_resolves(
    cu_resolver,  # type: ignore[no-untyped-def]
    query: str,
    expected_id: str,
) -> None:
    """Canonical full names (now added as aliases) resolve correctly."""
    result = cu_resolver.resolve(query)
    assert result.is_resolved, (
        f"{query!r}: expected RESOLVED but got {result.status.value!r}"
    )
    assert result.entity_id == expected_id, (
        f"{query!r}: got {result.entity_id!r}, expected {expected_id!r}"
    )


# ---------------------------------------------------------------------------
# Alternate spelling variants
# ---------------------------------------------------------------------------

_ALT_SPELLING_CASES = [
    # OECD alternate with American 'z' spelling
    ("Organization for Economic Co-operation and Development", "groups/OECD"),
    # OPEC British spelling variant
    ("Organisation of the Petroleum Exporting Countries", "groups/OPEC"),
    # EU historical snapshots
    ("EU27_2020", "groups/EU27_2020"),
    ("EU28", "groups/EU28"),
    ("EU27", "groups/EU27_2020"),
    # Dot-separated NATO (already worked before)
    ("N.A.T.O.", "groups/NATO"),
    # A.S.E.A.N.
    ("A.S.E.A.N.", "groups/ASEAN"),
]


@pytest.mark.integration
@pytest.mark.parametrize(
    "query,expected_id",
    _ALT_SPELLING_CASES,
    ids=[c[0] for c in _ALT_SPELLING_CASES],
)
def test_alt_spelling_resolves(
    cu_resolver,  # type: ignore[no-untyped-def]
    query: str,
    expected_id: str,
) -> None:
    """Alternative spelling forms resolve correctly."""
    result = cu_resolver.resolve(query)
    assert result.is_resolved, (
        f"{query!r}: expected RESOLVED but got {result.status.value!r}"
    )
    assert result.entity_id == expected_id, (
        f"{query!r}: got {result.entity_id!r}, expected {expected_id!r}"
    )


# ---------------------------------------------------------------------------
# AU resolves correctly in continental_unions-only context
# (full-stack collision with Australia/ISO2 is a separate known issue)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_au_resolves_in_cu_only_context(cu_resolver) -> None:  # type: ignore[no-untyped-def]
    """'AU' resolves to groups/AU when only the continental_unions pack is loaded."""
    result = cu_resolver.resolve("AU")
    assert result.is_resolved, f"expected RESOLVED but got {result.status.value!r}"
    assert result.entity_id == "groups/AU", (
        f"expected groups/AU but got {result.entity_id!r}"
    )
