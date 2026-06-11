"""Geo pack routing heuristics.

Exposes ``geo_scoring_fn``, declared as ``RoutingHints.scoring_fn`` in
``GeoPack``.  ``AutoRouter`` reads each pack's ``scoring_fn`` and runs it to
score the geo domain — the engine carries no hardcoded ``pack_id == "geo"``
branch, so all geo-specific routing heuristics live here.
"""

from __future__ import annotations

import re
from typing import Final

# ISO code patterns (2-letter and 3-letter country codes)
_ISO2_PATTERN: Final = re.compile(r"^[A-Za-z]{2}$")
_ISO3_PATTERN: Final = re.compile(r"^[A-Za-z]{3}$")

# 4-10 character mostly-uppercase alphabetic tokens (DPRK, NATO, ASEAN, LDCs…).
# Many geo group entities (continental unions, world regions, country alliances)
# use acronyms of this shape.  A moderate boost ensures these route to geo so
# the geo pack can compete against org, which already boosts acronyms heavily.
_GEO_ACRONYM_PATTERN: Final = re.compile(r"^[A-Za-z]{4,10}$")

# Geo snapshot group alias pattern: 1-5 uppercase letters followed by 1-2 digits
# (EU28, EU27, EU25, EU15, EU12, G7, G8, G20, G77 …).  These entities live in
# the geo pack but contain digits that exclude them from _GEO_ACRONYM_PATTERN.
_GEO_SNAPSHOT_ALIAS_PATTERN: Final = re.compile(r"^[A-Z]{1,5}[0-9]{1,2}$")

# Period-delimited letter initialism (U.S.A., U.K., D.C.).  These alias real
# geo entities but contain only single letters and periods, so they miss every
# alphabetic-token pattern above.  Matched case-insensitively.
_DOTTED_INITIALISM_PATTERN: Final = re.compile(r"^(?:[A-Za-z]\.){1,5}[A-Za-z]?$")

# Uppercase ratio at/above which an alphabetic token reads as an acronym-shaped
# token.  Mirrors the org pack's ``ACRONYM_UPPERCASE_RATIO`` so that whenever
# org boosts a mixed/upper-case token as an acronym, geo boosts it too and stays
# in multi-pack routing — otherwise mixed-case names ("fRaNcE", "CHIna") drop
# geo entirely and never reach the country pack.
_ACRONYM_UPPERCASE_RATIO: Final = 0.5

# Geographic name suffixes (e.g., Finland, Pakistan, California)
_GEO_SUFFIXES: Final = frozenset(
    {"land", "stan", "ia", "ica", "nia", "ria", "ey", "ay"}
)


def geo_scoring_fn(text: str, text_lower: str) -> float:
    """Score likelihood of geo domain.

    Boosts score for ISO codes, geographic suffixes, multi-word names,
    snapshot group aliases (EU28, G7, G8 …), and uppercase acronyms that
    could be geo group entities (NATO, ASEAN, DPRK…).

    Args:
        text: Original query text.
        text_lower: Lowercased query text.

    Returns:
        Heuristic score in [0, 1].
    """
    score = 0.5  # Base score

    if _ISO2_PATTERN.match(text):
        score += 0.3
    elif _ISO3_PATTERN.match(text):
        score += 0.2
    elif _GEO_SNAPSHOT_ALIAS_PATTERN.match(text):
        # Snapshot group aliases (EU28, G7, G8 …): uppercase letters + digits.
        # These are geo entities; the same +0.15 as long alphabetic acronyms is
        # enough to include geo in multi-pack routing alongside org.
        score += 0.15
    elif _DOTTED_INITIALISM_PATTERN.match(text):
        # Period-delimited initialisms (U.S.A., U.K., D.C.) alias real geo
        # entities and read as acronyms to the org pack; match its boost so geo
        # stays in routing instead of conceding to org.
        score += 0.15
    elif _GEO_ACRONYM_PATTERN.match(text) and (
        sum(c.isupper() for c in text) / len(text) >= _ACRONYM_UPPERCASE_RATIO
    ):
        # Boost alphabetic acronym-shaped tokens: many geo group entities (DPRK,
        # NATO, ASEAN, BRICS, OPEC, MENA, SIDS, LDCs…) use this pattern, and
        # mixed-case country names ("fRaNcE", "CHIna") land here too.  The org
        # pack treats any token with >= 0.5 uppercase as an acronym; matching
        # that threshold keeps geo in multi-pack routing for those casings so
        # the higher-confidence geo resolution can win when the entity exists.
        score += 0.15

    if any(text_lower.endswith(suffix) for suffix in _GEO_SUFFIXES):
        score += 0.25

    # Multi-word names that aren't all caps (e.g., "United States" vs "USA")
    if " " in text and not text.isupper():
        score += 0.1

    return min(score, 1.0)
