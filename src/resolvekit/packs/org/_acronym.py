"""Canonical acronym-detection predicate for the org pack.

Single source of truth for ``is_acronym_like`` used by routing, the acronym
source, the feature extractor, and the decision policy.
"""

from __future__ import annotations

ACRONYM_MIN_LENGTH = 2
ACRONYM_MAX_LENGTH = 10
ACRONYM_UPPERCASE_RATIO = 0.5
ACRONYM_VOWEL_RATIO = 0.5
ACRONYM_SHORT_LENGTH = 5  # treat as acronym if <= this length regardless of vowels

_VOWELS = "aeiou"


def is_acronym_like(text: str) -> bool:
    """Heuristic: short, mostly-uppercase, vowel-sparse string (e.g. "IMF", "NATO").

    Loose semantics: requires upper_ratio >= 0.5, so fully-lowercase "imf"
    returns False. No first-character gate.
    """
    length = len(text)
    if not ACRONYM_MIN_LENGTH <= length <= ACRONYM_MAX_LENGTH:
        return False

    upper_ratio = sum(c.isupper() for c in text) / length
    if upper_ratio < ACRONYM_UPPERCASE_RATIO:
        return False

    vowel_count = sum(c in _VOWELS for c in text.lower())
    return vowel_count / length < ACRONYM_VOWEL_RATIO or length <= ACRONYM_SHORT_LENGTH
