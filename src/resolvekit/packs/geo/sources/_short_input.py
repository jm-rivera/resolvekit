"""Shared short-input gates for geo candidate sources.

A user typing a degenerate input ("us", "i", "NULL", "#N/A", "NA") into a
notebook should not get back a high-confidence country resolution. The
heuristics in this module identify those degenerate shapes so each source
can suppress itself when no opt-in context is supplied.

The principle: short alpha inputs are only treated as country codes when
the raw text is all-uppercase ASCII (the conventional ISO/UIC casing) OR
the caller has explicitly asked for a geo resolution via
``ResolutionContext.entity_types``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resolvekit.core.model import ResolutionContext


# Geo entity types that signal the caller explicitly wants a country/region
# match. When any of these appear in ``ResolutionContext.entity_types``, the
# short-input gates are bypassed (single letters and lowercase short alpha
# inputs are allowed to resolve via codes/aliases).
_GEO_CODE_CONTEXT_TYPES = frozenset(
    {
        "geo.country",
        "geo.dependency",
        "geo.region",
        "geo.subregion",
        "geo.subdivision",
        "geo.continent",
        "geo.continental_union",
    }
)

_SHORT_ALPHA_MAX_LEN = 3

# Common spreadsheet/dataframe missing-value markers. These should never resolve
# to a geo entity even when the casing/length looks code-like (e.g. "NA" reads
# as ISO2 for Namibia, but in real-world tabular data it almost always means
# "not available"). Compared casefolded.
_DEGENERATE_TOKENS = frozenset(
    {
        "na",
        "n/a",
        "n.a.",
        "n.a",
        "n/k",
        "null",
        "none",
        "nan",
        "nil",
        "tbd",
        "tba",
        "unknown",
        "<null>",
        "#n/a",
        "?",
        "-",
        "--",
        "---",
        ".",
    }
)


def is_degenerate_token(raw_text: str) -> bool:
    """Return True for known missing-value markers (``NA``, ``#N/A``, ``--`` …).

    The check is casefolded so ``NA``, ``Na``, ``na`` are all treated alike.
    Pure-ASCII whitespace is stripped first; surrounding punctuation is left
    intact (we want ``#N/A`` to match the ``#n/a`` entry).
    """
    return raw_text.strip().casefold() in _DEGENERATE_TOKENS


def has_geo_code_context(context: ResolutionContext) -> bool:
    """True when the caller passed a geo entity_type hint."""
    types = context.entity_types
    if not types:
        return False
    return bool(types & _GEO_CODE_CONTEXT_TYPES)


def short_alpha_code_allowed(raw_text: str) -> bool:
    """Return False when ``raw_text`` is a short lowercase / mixed-case
    alpha input that should not auto-resolve as a country code.

    True (allowed) for:
      - empty strings (caller will already short-circuit)
      - any input longer than 3 characters
      - non-alphabetic short inputs (numeric, with punctuation, etc.)
      - all-uppercase ASCII letter inputs (e.g. "US", "GBR")

    False (suppress) for:
      - lowercase or mixed-case short alpha (``us``, ``Na``, ``it``, ``cd``)
    """
    raw = raw_text.strip()
    if not raw or len(raw) > _SHORT_ALPHA_MAX_LEN:
        return True
    if not raw.isascii() or not raw.isalpha():
        return True
    return raw.isupper()


def single_letter_code_allowed(raw_text: str) -> bool:
    """Return False when ``raw_text`` is a single ASCII letter.

    Single-letter ITU/UIC codes (``I`` = Italy, ``F`` = France) are real but
    too ambiguous to auto-resolve. The caller must opt in via context.
    """
    raw = raw_text.strip()
    return not (len(raw) == 1 and raw.isascii() and raw.isalpha())


def is_dotted_initialism(normalized_text: str) -> bool:
    """Return True for period-delimited letter initialisms (``U.S.A.``, ``U.K.``).

    Shape: one or more single letters, each separated and/or trailed by
    periods, with no other punctuation (``u.s.a.``, ``u.s.a``, ``u.k.``,
    ``d.c.``). These are conventional abbreviations that alias real geo
    entities, so they must not be treated as missing-value noise.

    Null markers are excluded because they either carry non-period
    punctuation (``#n/a``, ``n/a`` use ``#``/``/``) or have no letters at
    all (``.``, ``--``, ``?``).
    """
    raw = normalized_text.strip()
    if "." not in raw:
        return False
    segments = raw.split(".")
    has_letter = False
    for segment in segments:
        if not segment:
            continue  # interior/trailing separator
        if len(segment) != 1 or not segment.isascii() or not segment.isalpha():
            return False
        has_letter = True
    return has_letter


def is_punctuation_noise(normalized_text: str) -> bool:
    """Return True for short tokens dominated by punctuation/symbols.

    Captures null-marker shapes like ``#N/A``, ``N/A``, ``-``, ``--``, ``.``
    that data scientists encode missing values with. These should never
    resolve to a country, even via fuzzy matching.

    Heuristic: after stripping common spreadsheet punctuation
    (``# / \\ - _ . , ; : ! ? * | ( ) [ ] { } ' " `` whitespace), the
    remaining alphanumeric content must be either empty or a short alpha
    fragment that ``short_alpha_code_allowed`` would already block.

    Period-delimited initialisms (``U.S.A.``, ``U.K.``) are exempt: they are
    real abbreviations aliasing geo entities, not missing-value markers.
    """
    if not normalized_text:
        return True
    if is_dotted_initialism(normalized_text):
        return False
    stripped = normalized_text
    for ch in "#/\\-_.,;:!?*|()[]{}'\"`":
        stripped = stripped.replace(ch, "")
    stripped = stripped.strip()
    if not stripped:
        return True
    # Return True only if punctuation was present AND the residual is short
    # alpha that short_alpha_code_allowed would reject.
    had_punctuation = stripped != normalized_text.strip()
    if not had_punctuation:
        return False
    return len(stripped) <= _SHORT_ALPHA_MAX_LEN and stripped.isalpha()


def short_input_blocked(
    raw_text: str, normalized_text: str, context: ResolutionContext
) -> bool:
    """Combined short-input gate used by every geo source.

    Returns True when the source should suppress itself entirely. False when
    the source should run as normal.

    Precedence (earlier checks win):
      1. Degenerate missing-value markers (``NA``, ``#N/A``, ``--``, …) — blocked
         even with a geo entity-type hint; they never represent real geo entities.
      2. Single lowercase letter — blocked even with a hint.  A bare ``"i"`` or
         ``"a"`` is too ambiguous regardless of caller intent.  Uppercase single
         letters (``"I"``, ``"A"``) remain admitted under a hint because they are
         the conventional ITU/UIC casing for those codes.
         Why ``"chad"`` is unaffected: it is 4 chars, not a single letter.
         Why ``"AND"`` is unaffected: it is uppercase — handled upstream by the
         case channel before this gate is even reached.
      3. Geo entity-type hint present — admits ≥2-char inputs (including lowercase
         ISO codes like ``"us"`` and uppercase codes like ``"US"``).
      4. Short lowercase / mixed-case alpha — blocked without a hint.
      5. Punctuation-noise tokens.
    """
    if is_degenerate_token(raw_text):
        return True
    # Block single lowercase letters even when the caller supplied a geo hint.
    # A bare "i" or "a" is never unambiguous enough to auto-resolve; uppercase
    # single letters ("I" → Italy, "F" → France) retain the hint unlock below.
    raw = raw_text.strip()
    if len(raw) == 1 and raw.isascii() and raw.isalpha() and raw.islower():
        return True
    if has_geo_code_context(context):
        return False
    if not short_alpha_code_allowed(raw_text):
        return True
    if not single_letter_code_allowed(raw_text):
        return True
    return is_punctuation_noise(normalized_text)
