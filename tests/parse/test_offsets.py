"""Tests for normalize_aligned() -- the offset-tracking normalizer.

Return contract: ``normalize_aligned(raw, profile)`` returns
``(normalized, starts, ends)`` where both lists have length
``len(normalized)``:

- ``starts[i]`` -- first raw index for normalized char i.
- ``ends[i]``   -- one-past the last raw index consumed by normalized char i.

Span recovery: ``raw[starts[ns]:ends[ne-1]]`` recovers the exact raw surface
for normalized span ``[ns, ne)``, and re-normalizing that surface returns
``normalized[ns:ne]``.

Battery covers geo and org profiles across: ASCII identity, eszett casefold
expansion, HTML entity decode, markdown strip (embedded + standalone),
NFC combining compose, whitespace collapse, leading whitespace strip, org
punctuation strip, and a mixed multi-transform input.
"""

from __future__ import annotations

import pytest

from resolvekit.core.parse.offsets import normalize_aligned
from resolvekit.core.util.normalization import NormalizationProfile
from resolvekit.packs.geo.pack import GEO_NORMALIZATION_PROFILE
from resolvekit.packs.org.pack import ORG_NORMALIZATION_PROFILE

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def assert_invariants(
    raw: str,
    normalized: str,
    starts: list[int],
    ends: list[int],
    *,
    spans: list[tuple[int, int, str]],
    profile: NormalizationProfile,
) -> None:
    """Assert structural invariants and exact-surface round-trip for *spans*.

    Args:
        raw: Original input string.
        normalized: Normalized output from normalize_aligned.
        starts: Raw-start map from normalize_aligned.
        ends: Raw-end map from normalize_aligned.
        spans: List of ``(ns, ne, expected_raw_surface)`` triples to check.
        profile: The profile used to produce the outputs.
    """
    # Structural: correct lengths.
    assert len(starts) == len(normalized), (
        f"len(starts)={len(starts)} != len(normalized)={len(normalized)}"
    )
    assert len(ends) == len(normalized), (
        f"len(ends)={len(ends)} != len(normalized)={len(normalized)}"
    )
    for i in range(len(normalized)):
        assert ends[i] >= starts[i], f"ends[{i}]={ends[i]} < starts[{i}]={starts[i]}"
    for i in range(1, len(normalized)):
        assert starts[i] >= starts[i - 1], (
            f"starts not non-decreasing at {i}: {starts[i - 1]} > {starts[i]}"
        )

    # Exact-surface recovery and round-trip.
    for ns, ne, expected_surface in spans:
        recovered = raw[starts[ns] : ends[ne - 1]]
        assert recovered == expected_surface, (
            f"span [{ns},{ne}) recovered {recovered!r}, expected {expected_surface!r}"
        )
        re_norm, _, _ = normalize_aligned(recovered, profile)
        assert re_norm == normalized[ns:ne], (
            f"round-trip failed for span [{ns},{ne}): "
            f"re_norm={re_norm!r}, expected={normalized[ns:ne]!r}"
        )


# ---------------------------------------------------------------------------
# Parametrize over both profiles
# ---------------------------------------------------------------------------

PROFILES = [
    pytest.param(GEO_NORMALIZATION_PROFILE, id="geo"),
    pytest.param(ORG_NORMALIZATION_PROFILE, id="org"),
]


# ---------------------------------------------------------------------------
# ASCII identity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", PROFILES)
def test_ascii_identity(profile: NormalizationProfile) -> None:
    raw = "Kenya"
    normalized, starts, ends = normalize_aligned(raw, profile)
    assert normalized == "kenya"
    assert starts == [0, 1, 2, 3, 4]
    assert ends == [1, 2, 3, 4, 5]
    assert_invariants(
        raw, normalized, starts, ends, spans=[(0, 5, "Kenya")], profile=profile
    )


# ---------------------------------------------------------------------------
# Eszett casefold expansion (ss -> ss)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", PROFILES)
def test_strasse_casefold_expansion(profile: NormalizationProfile) -> None:
    raw = "Straße"  # S t r a ß e -- 6 raw chars; ß casefoldes to ss
    normalized, starts, ends = normalize_aligned(raw, profile)
    assert normalized == "strasse"  # 7 chars
    assert len(starts) == len(ends) == 7

    # Both 's' chars from ß share ß's raw position (4) and raw-end (5).
    ss_start = normalized.index("ss")
    assert starts[ss_start] == 4
    assert starts[ss_start + 1] == 4
    assert ends[ss_start] == 5
    assert ends[ss_start + 1] == 5

    assert_invariants(
        raw, normalized, starts, ends, spans=[(0, 7, "Straße")], profile=profile
    )


# ---------------------------------------------------------------------------
# HTML entity decode -- geo profile only
# ---------------------------------------------------------------------------


def test_html_entity_geo_profile() -> None:
    raw = "&amp;Spain"
    normalized, starts, ends = normalize_aligned(raw, GEO_NORMALIZATION_PROFILE)
    # &amp; (5 raw chars) -> & (1 output char), then "Spain" casefolds to "spain"
    assert normalized == "&spain"
    assert len(starts) == len(ends) == 6

    # The '&' output char spans the whole entity token in raw.
    assert starts[0] == 0
    assert ends[0] == 5  # one-past ';' of '&amp;'

    # Span for "spain" [1, 6) -> exact raw surface "Spain".
    assert_invariants(
        raw,
        normalized,
        starts,
        ends,
        spans=[(1, 6, "Spain")],
        profile=GEO_NORMALIZATION_PROFILE,
    )


def test_html_entity_org_profile_passthrough() -> None:
    # Org profile does not decode HTML entities; punctuation removal eliminates &
    # so "&amp;" + "Spain" normalizes to "ampspain".
    raw = "&amp;Spain"
    normalized, starts, ends = normalize_aligned(raw, ORG_NORMALIZATION_PROFILE)
    assert "spain" in normalized
    assert len(starts) == len(ends) == len(normalized)


# ---------------------------------------------------------------------------
# Markdown strip -- exact-surface regression tests
# ---------------------------------------------------------------------------


def test_markdown_strip_standalone_exact_surface() -> None:
    """Standalone **Italy** -> exact surface 'Italy' (not 'Italy**')."""
    raw = "**Italy**"
    normalized, starts, ends = normalize_aligned(raw, GEO_NORMALIZATION_PROFILE)
    assert normalized == "italy"
    assert len(starts) == len(ends) == 5

    # Critical: raw[starts[0]:ends[4]] must be exactly "Italy", no trailing asterisks.
    assert raw[starts[0] : ends[4]] == "Italy", (
        f"Expected 'Italy', got {raw[starts[0] : ends[4]]!r}"
    )

    assert_invariants(
        raw,
        normalized,
        starts,
        ends,
        spans=[(0, 5, "Italy")],
        profile=GEO_NORMALIZATION_PROFILE,
    )


def test_markdown_strip_embedded_exact_surface() -> None:
    """'**Kenya** Somalia' -> Kenya surface is exactly 'Kenya', not 'Kenya**'."""
    raw = "**Kenya** Somalia"
    normalized, starts, ends = normalize_aligned(raw, GEO_NORMALIZATION_PROFILE)
    assert "kenya" in normalized
    assert "somalia" in normalized

    kenya_ns = normalized.index("kenya")
    kenya_ne = kenya_ns + 5
    somalia_ns = normalized.index("somalia")
    somalia_ne = somalia_ns + 7

    # Regression guard: exactly "Kenya", NOT "Kenya**".
    assert raw[starts[kenya_ns] : ends[kenya_ne - 1]] == "Kenya", (
        f"Expected 'Kenya', got {raw[starts[kenya_ns] : ends[kenya_ne - 1]]!r}"
    )
    assert raw[starts[somalia_ns] : ends[somalia_ne - 1]] == "Somalia"

    assert_invariants(
        raw,
        normalized,
        starts,
        ends,
        spans=[(kenya_ns, kenya_ne, "Kenya"), (somalia_ns, somalia_ne, "Somalia")],
        profile=GEO_NORMALIZATION_PROFILE,
    )


def test_markdown_strip_embedded_start_precision() -> None:
    """Start offsets are precise: 'I' of Italy maps to 'I' in raw."""
    raw = "Report on **Italy** today"
    normalized, starts, ends = normalize_aligned(raw, GEO_NORMALIZATION_PROFILE)
    italy_ns = normalized.index("italy")
    italy_ne = italy_ns + 5

    assert raw[starts[italy_ns]] == "I"
    assert raw[starts[italy_ns] : ends[italy_ne - 1]] == "Italy"

    assert_invariants(
        raw,
        normalized,
        starts,
        ends,
        spans=[(italy_ns, italy_ne, "Italy")],
        profile=GEO_NORMALIZATION_PROFILE,
    )


# ---------------------------------------------------------------------------
# NFC combining marks -- "Cafe" with combining acute
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", PROFILES)
def test_nfc_combining_accent(profile: NormalizationProfile) -> None:
    # Pre-composed: NFC fast-path (length unchanged).
    raw = "Café"
    normalized, starts, ends = normalize_aligned(raw, profile)
    assert normalized == "café"
    assert len(starts) == len(ends) == 4
    assert_invariants(
        raw, normalized, starts, ends, spans=[(0, 4, raw)], profile=profile
    )


# ---------------------------------------------------------------------------
# Whitespace collapse -- "New   York"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", PROFILES)
def test_whitespace_collapse(profile: NormalizationProfile) -> None:
    raw = "New   York"
    normalized, starts, ends = normalize_aligned(raw, profile)
    assert normalized == "new york"
    assert len(starts) == len(ends) == 8

    york_ns = normalized.index("york")
    york_ne = york_ns + 4
    assert_invariants(
        raw,
        normalized,
        starts,
        ends,
        spans=[(york_ns, york_ne, "York")],
        profile=profile,
    )


# ---------------------------------------------------------------------------
# Leading strip -- "  Kenya"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", PROFILES)
def test_leading_whitespace_strip(profile: NormalizationProfile) -> None:
    raw = "  Kenya"
    normalized, starts, ends = normalize_aligned(raw, profile)
    assert normalized == "kenya"
    assert len(starts) == 5

    # 'k' maps to raw 'K' at index 2.
    assert starts[0] == 2
    assert_invariants(
        raw, normalized, starts, ends, spans=[(0, 5, "Kenya")], profile=profile
    )


# ---------------------------------------------------------------------------
# Mixed: markdown + HTML entity + whitespace -- geo profile
# ---------------------------------------------------------------------------


def test_mixed_markdown_entity_geo() -> None:
    raw = "drought in **Kenya** &amp; Somalia"
    normalized, starts, ends = normalize_aligned(raw, GEO_NORMALIZATION_PROFILE)
    # After all transforms: "drought in kenya & somalia"
    assert "kenya" in normalized
    assert "somalia" in normalized
    assert len(starts) == len(ends) == len(normalized)

    kenya_ns = normalized.index("kenya")
    kenya_ne = kenya_ns + 5
    somalia_ns = normalized.index("somalia")
    somalia_ne = somalia_ns + 7

    # Critical: exact surfaces -- Kenya must NOT include trailing '**'.
    assert raw[starts[kenya_ns] : ends[kenya_ne - 1]] == "Kenya"
    assert raw[starts[somalia_ns] : ends[somalia_ne - 1]] == "Somalia"

    assert_invariants(
        raw,
        normalized,
        starts,
        ends,
        spans=[
            (kenya_ns, kenya_ne, "Kenya"),
            (somalia_ns, somalia_ne, "Somalia"),
        ],
        profile=GEO_NORMALIZATION_PROFILE,
    )


# ---------------------------------------------------------------------------
# Unsupported flag guard
# ---------------------------------------------------------------------------


def test_strip_diacritics_raises() -> None:
    profile = NormalizationProfile(strip_diacritics=True)
    with pytest.raises(ValueError, match="strip_diacritics"):
        normalize_aligned("Espana", profile)


# ---------------------------------------------------------------------------
# Empty string
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", PROFILES)
def test_empty_string(profile: NormalizationProfile) -> None:
    normalized, starts, ends = normalize_aligned("", profile)
    assert normalized == ""
    assert starts == []
    assert ends == []


# ---------------------------------------------------------------------------
# Org punctuation stripping
# ---------------------------------------------------------------------------


def test_org_punctuation_strip() -> None:
    # "AT&T" with org profile: & is punctuation -> stripped -> "att"
    raw = "AT&T"
    normalized, starts, ends = normalize_aligned(raw, ORG_NORMALIZATION_PROFILE)
    assert normalized == "att"
    assert len(starts) == len(ends) == 3

    # 'a' <- 'A' (raw 0), first 't' <- 'T' (raw 1), second 't' <- 'T' (raw 3)
    assert starts[0] == 0
    assert starts[1] == 1
    assert starts[2] == 3

    assert_invariants(
        raw,
        normalized,
        starts,
        ends,
        spans=[(0, 3, "AT&T")],
        profile=ORG_NORMALIZATION_PROFILE,
    )


# ---------------------------------------------------------------------------
# Casefold-expansion mid-split: raw surface recovery is clean even when
# the round-trip invariant breaks (ß→ss, span ends between the two s chars).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", PROFILES)
def test_casefold_expansion_raw_surface_always_clean(
    profile: NormalizationProfile,
) -> None:
    """raw[starts[ns]:ends[ne-1]] never splits a raw codepoint for ß expansions.

    Pattern 'weis' (4 normalized chars) fires on 'Weiß' (raw length 4).
    After casefold: normalized='weiss', starts=[0,1,2,3,3], ends=[1,2,3,4,4].
    Span [0,4) ends between the two 's' chars that both map to raw ß (index 3).

    Raw surface recovery: raw[starts[0]:ends[3]] = raw[0:4] = 'Weiß' — clean,
    because both expansion chars share ends[*]=4 (one-past ß).

    Round-trip: normalize_aligned('Weiß')[0] = 'weiss', not 'weis' — the
    invariant does NOT hold for this mid-expansion split, which is expected
    and documented in the module docstring.
    """
    raw = "Weiß"
    normalized, starts, ends = normalize_aligned(raw, profile)
    assert normalized == "weiss", f"Expected 'weiss', got {normalized!r}"
    assert len(starts) == len(ends) == 5

    # Both 's' chars from ß share the same raw position (index 3, ends=4).
    assert starts[3] == 3
    assert starts[4] == 3
    assert ends[3] == 4
    assert ends[4] == 4

    # Span [0,4) = 'weis' — raw surface recovery is always clean.
    ns, ne = 0, 4
    raw_surface = raw[starts[ns] : ends[ne - 1]]
    assert raw_surface == "Weiß", (
        f"Surface recovery must not split ß: got {raw_surface!r}"
    )

    # Documented exception: round-trip does not hold for mid-expansion spans.
    renorm = normalize_aligned(raw_surface, profile)[0]
    assert renorm == "weiss"  # re-normalizes the full ß to ss
    assert normalized[ns:ne] == "weis"  # matched pattern was only 4 chars
    # These differ: invariant violation is expected for this span boundary.
    assert renorm != normalized[ns:ne], (
        "Round-trip invariant should NOT hold for mid-casefold-expansion span — "
        "if this assertion fails the invariant is now fixed, update this test."
    )


@pytest.mark.parametrize("profile", PROFILES)
def test_casefold_expansion_whole_token_round_trips(
    profile: NormalizationProfile,
) -> None:
    """Whole-token spans that include the full casefold expansion do round-trip."""
    raw = "Weiß"
    normalized, starts, ends = normalize_aligned(raw, profile)
    assert normalized == "weiss"

    # Span [0,5) covers all of 'weiss' — round-trip holds.
    ns, ne = 0, 5
    raw_surface = raw[starts[ns] : ends[ne - 1]]
    assert raw_surface == "Weiß"
    renorm = normalize_aligned(raw_surface, profile)[0]
    assert renorm == normalized[ns:ne], (
        f"Whole-token round-trip failed: {renorm!r} != {normalized[ns:ne]!r}"
    )
