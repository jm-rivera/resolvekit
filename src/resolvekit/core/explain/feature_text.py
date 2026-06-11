"""Human-readable feature evidence text for resolution candidates.

Converts raw feature dicts into short, ordered strings that explain
why a candidate matched.
"""

from __future__ import annotations

from typing import Any


def describe_features(features: dict[str, Any]) -> list[str]:
    """Convert a features dict into ordered human-readable evidence strings.

    Strings are ordered from most to least informative.  At most 6 are
    returned.

    Args:
        features: Raw feature dict from a resolved candidate (e.g. from
            ``CandidateScorecard.key_features`` or the full features dict).

    Returns:
        List of short evidence strings, capped at 6 entries.
    """
    results: list[str] = []

    if features.get("exact_code_hit"):
        results.append("matched code exactly")

    if features.get("exact_name_hit"):
        results.append("matched canonical name exactly")

    fuzzy_sim = features.get("fuzzy_edit_sim")
    if isinstance(fuzzy_sim, int | float):
        if fuzzy_sim >= 0.85:
            results.append("very close edit-distance match")
        elif fuzzy_sim >= 0.6:
            results.append("close edit-distance match")

    bm25 = features.get("fts_bm25_norm")
    if isinstance(bm25, int | float) and bm25 > 0.7:
        results.append("strong full-text match")

    if features.get("acronym_hit"):
        results.append("acronym match")

    return results[:6]
