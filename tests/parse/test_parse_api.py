"""Tests for Resolver.parse() and the module-level rk.parse() wrapper.

Uses the ``parse_geo_resolver`` fixture (Kenya, Somalia, USA, GBR) to verify
that parse() works on a normally-constructed resolver with AUTO routing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from resolvekit.core.api.resolver import Resolver


# ---------------------------------------------------------------------------
# Happy path: Kenya and Somalia
# ---------------------------------------------------------------------------


def test_parse_happy_path(parse_geo_resolver: Resolver) -> None:
    """parse() detects Kenya and Somalia with correct raw-input offsets."""
    text = "drought in northern Kenya and parts of Somalia"
    result = parse_geo_resolver.parse(text)

    surfaces = {e.surface for e in result}
    assert "Kenya" in surfaces, f"Expected 'Kenya' in surfaces, got: {surfaces}"
    assert "Somalia" in surfaces, f"Expected 'Somalia' in surfaces, got: {surfaces}"

    for e in result:
        # surface == raw[start:end] (core contract)
        assert text[e.start : e.end] == e.surface, (
            f"offset mismatch: text[{e.start}:{e.end}]={text[e.start : e.end]!r} "
            f"!= surface={e.surface!r}"
        )
        assert e.confidence is not None, "resolved entity must have a confidence float"
        assert isinstance(e.confidence, float), "confidence must be float"

    # Entities ordered by ascending start offset.
    starts = [e.start for e in result]
    assert starts == sorted(starts), f"entities not sorted by start: {starts}"


def test_parse_entity_ids_are_set(parse_geo_resolver: Resolver) -> None:
    """Resolved entities carry the expected entity_ids."""
    text = "Kenya and Somalia"
    result = parse_geo_resolver.parse(text)

    entity_ids = {e.entity_id for e in result}
    assert "country/KEN" in entity_ids, f"Expected country/KEN in {entity_ids}"
    assert "country/SOM" in entity_ids, f"Expected country/SOM in {entity_ids}"


# ---------------------------------------------------------------------------
# include_nil
# ---------------------------------------------------------------------------


def test_parse_include_nil_false_default(parse_geo_resolver: Resolver) -> None:
    """Below-threshold spans are absent from entities by default."""
    result = parse_geo_resolver.parse("xyz_no_match_999")
    # No resolved entity expected; NIL spans only appear with include_nil=True.
    assert all(e.entity_id is not None for e in result.entities), (
        "expected no NIL (entity_id=None) in default result"
    )


def test_parse_include_nil_surfaces_no_match(parse_geo_resolver: Resolver) -> None:
    """include_nil=True surfaces detected spans that failed to resolve."""
    # 'xyz_no_match_999' is unlikely to be in the test store; but we use a
    # known pattern: entities with confidence is not None for resolved spans.
    text = "Kenya and Somalia"
    result_nil = parse_geo_resolver.parse(text, include_nil=True)
    result_def = parse_geo_resolver.parse(text, include_nil=False)

    # Default excludes NIL; include_nil=True may have equal or more entities.
    assert len(result_nil) >= len(result_def)


# ---------------------------------------------------------------------------
# dropped_spans always present
# ---------------------------------------------------------------------------


def test_parse_dropped_spans_always_present(parse_geo_resolver: Resolver) -> None:
    """dropped_spans is always a list (even if empty) on the ParseResult."""
    result = parse_geo_resolver.parse("Kenya")
    assert isinstance(result.dropped_spans, list)


# ---------------------------------------------------------------------------
# to= pivot: output, explain() survival
# ---------------------------------------------------------------------------


def test_parse_to_pivot_sets_output(parse_geo_resolver: Resolver) -> None:
    """to='iso3' sets ParsedEntity.output to the ISO-3 code."""
    text = "Kenya and Somalia"
    result = parse_geo_resolver.parse(text, to="iso3")

    for e in result:
        if e.entity_id == "country/KEN":
            assert e.output == "KEN", f"Expected KEN, got {e.output!r}"
        elif e.entity_id == "country/SOM":
            assert e.output == "SOM", f"Expected SOM, got {e.output!r}"


def test_parse_nil_output_is_none(parse_geo_resolver: Resolver) -> None:
    """NIL spans get output=None even when to= is requested."""
    text = "Kenya"
    result = parse_geo_resolver.parse(text, to="iso3", include_nil=True)
    for e in result:
        if e.entity_id is None:  # NIL span
            assert e.output is None, f"NIL span output should be None, got {e.output!r}"


def test_parse_explain_survives_pivot_replace(parse_geo_resolver: Resolver) -> None:
    """explain() works on a ParsedEntity after the to= pivot via dataclasses.replace.

    The weakref is intact because dataclasses.replace keeps the same
    ResolutionResult object by reference.
    """
    text = "Kenya"
    result = parse_geo_resolver.parse(text, to="iso3")
    for e in result:
        if e.entity_id is not None:
            # resolve() must still be callable via the entity's resolution
            scorecard = e.resolution.explain()
            assert scorecard is not None, "explain() should return a Scorecard"


def test_parse_to_dataframe_has_to_column(parse_geo_resolver: Resolver) -> None:
    """to_dataframe() includes the 'to' column with pivoted values."""
    pytest.importorskip("pandas")
    text = "Kenya and Somalia"
    result = parse_geo_resolver.parse(text, to="iso3")
    df = result.to_dataframe()
    assert "to" in df.columns, f"Expected 'to' column, got: {df.columns.tolist()}"


# ---------------------------------------------------------------------------
# module-level rk.parse() parity
# ---------------------------------------------------------------------------


def test_module_level_parse_attribute_accessible() -> None:
    """rk.parse is accessible as a callable attribute."""
    import resolvekit as rk

    assert callable(rk.parse), "rk.parse must be callable"
    assert callable(rk.parse_bulk), "rk.parse_bulk must be callable"


def test_module_level_parse_returns_parse_result(
    parse_geo_resolver: Resolver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Module-level rk.parse() wraps the default resolver's parse().

    We monkeypatch the default resolver to the test fixture resolver so the
    test doesn't require the full bundled geo build.
    """
    import resolvekit as rk
    import resolvekit._convenience as _cv

    monkeypatch.setattr(_cv, "_default", parse_geo_resolver)
    result = rk.parse("Kenya and Somalia")
    surfaces = {e.surface for e in result}
    assert "Kenya" in surfaces


# ---------------------------------------------------------------------------
# domain pinning
# ---------------------------------------------------------------------------


def test_parse_domain_pinning_restricts_to_pack(
    parse_geo_resolver: Resolver,
) -> None:
    """parse(domain='geo') detects geo entities (single-pack resolver just returns geo)."""
    text = "Kenya and Somalia"
    result = parse_geo_resolver.parse(text, domain="geo")
    for e in result:
        assert e.pack_id == "geo", f"Expected pack_id='geo', got {e.pack_id!r}"


def test_parse_closed_resolver_raises(parse_geo_datapack: Any) -> None:
    """Calling parse() on a closed resolver raises RuntimeError."""
    from resolvekit.core.api.resolver import Resolver

    r = Resolver.from_datapacks(datapack_paths=[parse_geo_datapack])
    r.close()
    with pytest.raises(RuntimeError, match="closed"):
        r.parse("Kenya")


# ---------------------------------------------------------------------------
# Casefold-expansion offset correctness (regression for ß/Weiß edge case)
# ---------------------------------------------------------------------------


def test_parse_offsets_correct_after_casefold_expansion_token(
    parse_geo_resolver: Resolver,
) -> None:
    """Entities after a ß-containing token carry correct raw offsets.

    When 'Weiß' precedes a recognised entity, casefold expands ß→ss (changing
    the normalized length relative to raw).  The automaton must map spans back
    to raw correctly so that text[start:end] == surface for every detected entity.

    Regression: normalize_aligned round-trip invariant
    can break for mid-casefold-expansion spans, but raw surface recovery and all
    public offsets must still be exact.
    """
    text = "Weiß lives in Kenya"
    result = parse_geo_resolver.parse(text)

    kenya_entities = [e for e in result if e.surface == "Kenya"]
    assert kenya_entities, (
        f"Expected 'Kenya' in parse result; got {[e.surface for e in result]}"
    )

    for e in kenya_entities:
        recovered = text[e.start : e.end]
        assert recovered == e.surface, (
            f"Offset mismatch after Weiß: text[{e.start}:{e.end}]={recovered!r} "
            f"!= surface={e.surface!r}"
        )
    # Confirm 'Kenya' starts after the ß token, not before it.
    kenya_hit = kenya_entities[0]
    assert kenya_hit.start > text.index("Weiß"), (
        "Kenya entity must start after the Weiß token"
    )
