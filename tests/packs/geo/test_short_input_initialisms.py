"""Regression tests for the short-input gate (dotted-abbreviation handling).

The punctuation-noise gate used to classify dotted abbreviations ("U.S.A.",
"U.K.", "D.C.") as missing-value noise and suppress every geo source. These
unit tests pin the gate-level predicates so a dotted initialism passes the
gate while genuine null markers stay blocked.
"""

from __future__ import annotations

import pytest

from resolvekit.packs.geo.sources._short_input import (
    is_degenerate_token,
    is_dotted_initialism,
    is_punctuation_noise,
)

# Dotted letter initialisms must pass the punctuation-noise gate.
_DOTTED_INITIALISMS = ["u.s.a.", "u.s.a", "u.k.", "d.c.", "e.u.", "n.z."]

# Genuine null markers / punctuation noise must stay blocked.
_NULL_MARKERS = ["#n/a", "n/a", "--", "---", ".", "?", "-", ""]


@pytest.mark.parametrize("text", _DOTTED_INITIALISMS)
def test_dotted_initialism_recognized(text: str) -> None:
    assert is_dotted_initialism(text) is True


@pytest.mark.parametrize("text", _NULL_MARKERS)
def test_null_marker_not_a_dotted_initialism(text: str) -> None:
    assert is_dotted_initialism(text) is False


@pytest.mark.parametrize("text", _DOTTED_INITIALISMS)
def test_dotted_initialism_passes_punctuation_gate(text: str) -> None:
    assert is_punctuation_noise(text) is False


@pytest.mark.parametrize("text", _NULL_MARKERS)
def test_null_marker_stays_blocked_by_punctuation_gate(text: str) -> None:
    assert is_punctuation_noise(text) is True


@pytest.mark.parametrize("text", ["n.a.", "n.a", "N.A.", "N.A"])
def test_dotted_na_still_caught_by_degenerate_token(text: str) -> None:
    """'N.A.' reads as a dotted initialism but is an explicit null marker.

    ``is_degenerate_token`` runs ahead of the punctuation gate in
    ``short_input_blocked``, so the null-marker classification still wins.
    """
    assert is_degenerate_token(text) is True


@pytest.mark.parametrize("text", ["usa.", ".usa", "u.sa", "a.b.cd"])
def test_non_initialism_dotted_shapes_not_treated_as_initialism(text: str) -> None:
    """Multi-letter runs around periods are not single-letter initialisms."""
    assert is_dotted_initialism(text) is False
