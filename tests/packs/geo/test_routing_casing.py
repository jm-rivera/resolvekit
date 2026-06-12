"""Regression tests for geo routing of dotted and mixed-case inputs.

Finding #1: dotted abbreviations ("U.S.A.", "U.K.") read as acronyms to the
org pack but earned no geo routing boost, so geo was dropped from routing.

Finding #11: 50-74%-uppercase country names ("fRaNcE", "CHIna") triggered the
org acronym boost (>= 0.5 uppercase) but not geo's (which required >= 0.75),
so geo was dropped and the country pack was never consulted.

These tests pin ``geo_scoring_fn`` so geo stays within the AutoRouter's
``SCORE_PREFERENCE_THRESHOLD`` of the org acronym score for both shapes.
"""

from __future__ import annotations

import pytest

from resolvekit.core.engine.router import SCORE_PREFERENCE_THRESHOLD
from resolvekit.packs.geo.routing import geo_scoring_fn
from resolvekit.packs.org.routing import org_scoring_fn


def _geo_stays_in_routing(text: str) -> bool:
    """True when geo survives the AutoRouter threshold against org."""
    geo = geo_scoring_fn(text, text.lower())
    org = org_scoring_fn(text, text.lower())
    max_score = max(geo, org)
    return geo >= max_score - SCORE_PREFERENCE_THRESHOLD


# Finding #1: dotted initialisms.
@pytest.mark.parametrize("text", ["U.S.A.", "U.S.A", "U.K.", "D.C.", "E.U."])
def test_dotted_initialism_keeps_geo_in_routing(text: str) -> None:
    assert _geo_stays_in_routing(text), (
        f"{text!r} dropped geo: geo={geo_scoring_fn(text, text.lower())}, "
        f"org={org_scoring_fn(text, text.lower())}"
    )


# Finding #11: mixed-case (50-74% uppercase) country names.
@pytest.mark.parametrize("text", ["fRaNcE", "CHIna", "SUDan", "FRANce", "KENya"])
def test_mixed_case_name_keeps_geo_in_routing(text: str) -> None:
    assert _geo_stays_in_routing(text), (
        f"{text!r} dropped geo: geo={geo_scoring_fn(text, text.lower())}, "
        f"org={org_scoring_fn(text, text.lower())}"
    )


# Standard casings must be unchanged (already routed correctly pre-fix).
@pytest.mark.parametrize("text", ["France", "FRANCE", "france", "USA", "United States"])
def test_standard_casing_keeps_geo_in_routing(text: str) -> None:
    assert _geo_stays_in_routing(text)


def test_lowercase_acronym_not_over_boosted() -> None:
    """A fully lowercase token is not acronym-shaped; geo stays at base score.

    The fix mirrors org's >= 0.5 uppercase acronym threshold, so all-lowercase
    input ("dprk") must not pick up the acronym boost.
    """
    assert geo_scoring_fn("dprk", "dprk") == pytest.approx(0.5)
