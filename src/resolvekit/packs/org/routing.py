"""Org pack routing heuristics.

Exposes ``org_scoring_fn``, declared as ``RoutingHints.scoring_fn`` in
``OrgPack``.  ``AutoRouter`` reads each pack's ``scoring_fn`` and runs it to
score the org domain — the engine carries no hardcoded ``pack_id == "org"``
branch, so all org-specific routing heuristics live here.
"""

from __future__ import annotations

from typing import Final

from resolvekit.packs.org._acronym import is_acronym_like

# Organizational keywords that boost org routing likelihood
_ORG_KEYWORDS: Final = frozenset(
    {"bank", "union", "organization", "foundation", "institute", "fund"}
)


def org_scoring_fn(text: str, text_lower: str) -> float:
    """Score likelihood of org domain.

    Boosts score for acronyms and organizational keywords.

    Args:
        text: Original query text.
        text_lower: Lowercased query text.

    Returns:
        Heuristic score in [0, 1].
    """
    score = 0.4  # Base score (slightly lower than geo)

    if is_acronym_like(text):
        score += 0.35

    if any(keyword in text_lower for keyword in _ORG_KEYWORDS):
        score += 0.2

    return min(score, 1.0)
