"""Offset-tracking normalizer for raw-to-normalized character mapping.

``normalize_aligned`` applies the same transforms in the same order as
``TextNormalizer._normalize_impl`` but maintains per-character raw provenance
so that every normalized span maps back to the exact raw surface.

Return shape
------------
``normalize_aligned`` returns ``(normalized, starts, ends)`` where both
``starts`` and ``ends`` are ``list[int]`` of length ``len(normalized)``:

- ``starts[i]`` — first raw index that contributed to normalized char ``i``.
- ``ends[i]``   — one-past the last raw index consumed by normalized char ``i``
  (i.e. the raw end is *exclusive*, matching Python slice convention).

A normalized span ``[ns, ne)`` recovers the raw surface as::

    raw_start = starts[ns]
    raw_end   = ends[ne - 1]
    surface   = raw[raw_start:raw_end]

This two-anchor design ensures that trailing dropped characters (e.g. closing
``**`` after an emphasis group) are absorbed into the *preceding* char's
``ends`` value and do NOT bleed into the following span's ``starts``.

Raw surface recovery is always clean: ``raw[starts[ns]:ends[ne-1]]`` never
splits a raw codepoint even when a casefold expansion (e.g. ``ß`` → ``ss``)
maps multiple normalized chars to the same raw position, because all expansion
chars share the same ``ends`` value (the one-past position of that codepoint).

Round-trip invariant: holds for spans whose boundary does not fall
mid-expansion (i.e. ``ne`` does not land between two normalized chars that
both originated from the same raw codepoint).  When a gazetteer pattern like
``weis`` fires on raw ``Weiß``, the recovered surface ``Weiß`` re-normalizes
to ``weiss``, not ``weis`` — the invariant breaks at ``ne``, but the raw
slice itself is a valid token and ``link_span`` resolves through the full
pipeline independently, so no offset corruption occurs in practice.

Supported profile flags (geo and org today):
  - unicode_nfc
  - casefold
  - strip_whitespace
  - strip_punctuation
  - preserve_digits
  - decode_html_entities
  - strip_markdown_formatting

Unsupported flag:
  - strip_diacritics=True — neither geo nor org sets this; if passed, the
    function raises rather than silently emitting wrong offsets.  Add the
    NFD→filter-Mn→NFC mapping rule when a shipped profile needs it.
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Callable

from resolvekit.core.util.normalization import (
    _MD_EMPHASIS_RE,
    _MD_HTML_HINT_RE,
    _MD_LEADING_RE,
    NormalizationProfile,
)

# Whitespace / punctuation / digit patterns — mirrors TextNormalizer exactly.
_WHITESPACE: re.Pattern[str] = re.compile(r"\s+")
_PUNCTUATION: re.Pattern[str] = re.compile(r"[^\w\s\-']")
_DIGITS: re.Pattern[str] = re.compile(r"\d")


def _assert_supported_profile(profile: NormalizationProfile) -> None:
    """Raise ValueError if *profile* sets a flag this function cannot handle.

    Adding a new transform later is intentional; this guard makes the omission
    visible the moment a profile exercises an unsupported path.
    """
    if profile.strip_diacritics:
        raise ValueError(
            "normalize_aligned does not support strip_diacritics=True. "
            "Add the NFD->filter-Mn->NFC mapping rule when a shipped profile needs it."
        )


# ---------------------------------------------------------------------------
# Internal state type: (text, starts, ends)
# Each transform takes and returns this triple.
# starts[i] = first raw index that produced normalized char i.
# ends[i]   = one-past the last raw index consumed by normalized char i.
# ---------------------------------------------------------------------------

_State = tuple[str, list[int], list[int]]


def _seed(raw: str) -> _State:
    """Build the identity state for a raw string.

    Each char is its own raw source: starts[i] = i, ends[i] = i+1.
    """
    n = len(raw)
    starts = list(range(n))
    ends = list(range(1, n + 1))
    return raw, starts, ends


# ---------------------------------------------------------------------------
# Per-transform helpers
# ---------------------------------------------------------------------------


def _apply_regex_sub(
    text: str,
    starts: list[int],
    ends: list[int],
    pattern: re.Pattern[str],
    replacement_fn: Callable[[re.Match[str]], str],
) -> _State:
    """Apply a regex substitution while tracking (starts, ends).

    Replacement characters all inherit the match's raw start (``starts``) and
    the match's raw end (``ends``) — the match is treated as a single unit so
    leading/trailing dropped chars are absorbed correctly.  Characters outside
    matches are copied 1:1.
    """
    out_chars: list[str] = []
    out_starts: list[int] = []
    out_ends: list[int] = []
    cursor = 0

    for m in pattern.finditer(text):
        # Copy verbatim chars before this match.
        for i in range(cursor, m.start()):
            out_chars.append(text[i])
            out_starts.append(starts[i])
            out_ends.append(ends[i])

        # All replacement chars inherit the match's raw span.
        raw_start = starts[m.start()]
        raw_end = ends[m.end() - 1]
        repl: str = replacement_fn(m)
        for ch in repl:
            out_chars.append(ch)
            out_starts.append(raw_start)
            out_ends.append(raw_end)

        cursor = m.end()

    # Copy tail.
    for i in range(cursor, len(text)):
        out_chars.append(text[i])
        out_starts.append(starts[i])
        out_ends.append(ends[i])

    return "".join(out_chars), out_starts, out_ends


def _apply_html_unescape(text: str, starts: list[int], ends: list[int]) -> _State:
    """Decode HTML entities while tracking raw provenance.

    Each entity (``&amp;``, ``&#39;``, etc.) decodes to one or more chars that
    all carry the raw span of the whole entity token.
    """
    _entity_re = re.compile(r"&(?:[a-zA-Z][a-zA-Z0-9]*|#[0-9]+|#x[0-9a-fA-F]+);")

    def _decode(m: re.Match[str]) -> str:
        return html.unescape(m.group(0))

    return _apply_regex_sub(text, starts, ends, _entity_re, _decode)


def _apply_markdown_strip(text: str, starts: list[int], ends: list[int]) -> _State:
    """Strip leading block markers and inline emphasis, tracking (starts, ends).

    Leading block markers (``#``, ``>``, ``@``): the marker chars are dropped,
    chars after them are shifted left but keep their raw source 1:1.

    Inline emphasis (``**x**``, ``*x*``, ``_x_``, etc.): the wrapping marker
    chars are dropped.  Each kept char in group(1) maps to its own raw position
    precisely (per-char ``ends`` copy — no absorption step).  Closing markers
    produce no output entry; they are simply skipped.  A span ending at the last
    kept char uses that char's ``ends`` value, which correctly stops before the
    closing markers.
    """
    # Leading block markers: dropped entirely via regex_sub (replacement = "").
    text, starts, ends = _apply_regex_sub(
        text, starts, ends, _MD_LEADING_RE, lambda m: ""
    )

    # Inline emphasis: keep group(1) chars with per-char raw-start precision,
    # but set the last kept char's raw-end to absorb the closing markers.
    out_chars: list[str] = []
    out_starts: list[int] = []
    out_ends: list[int] = []
    cursor = 0
    for m in _MD_EMPHASIS_RE.finditer(text):
        # Copy verbatim chars before this match.
        for i in range(cursor, m.start()):
            out_chars.append(text[i])
            out_starts.append(starts[i])
            out_ends.append(ends[i])

        g1 = m.group(1)
        g1_start_in_text = m.start(1)

        for k, ch in enumerate(g1):
            out_chars.append(ch)
            out_starts.append(starts[g1_start_in_text + k])
            out_ends.append(ends[g1_start_in_text + k])

        cursor = m.end()

    for i in range(cursor, len(text)):
        out_chars.append(text[i])
        out_starts.append(starts[i])
        out_ends.append(ends[i])

    return "".join(out_chars), out_starts, out_ends


def _apply_nfc(text: str, starts: list[int], ends: list[int]) -> _State:
    """Apply NFC normalization while tracking raw provenance.

    Fast path: NFC doesn't change length -> identity (starts, ends) still
    correct because character boundaries are preserved.

    Slow path: composing N raw chars into M normalized chars (typically 2->1
    for base+combining).  Each output NFC char's raw span covers all the raw
    input chars that composed it.
    """
    nfc = unicodedata.normalize("NFC", text)
    if len(nfc) == len(text):
        return nfc, starts, ends

    # Slow path: align nfc <-> text window by window.
    out_starts: list[int] = []
    out_ends: list[int] = []
    raw_i = 0  # cursor into text / starts / ends
    nfc_i = 0  # cursor into nfc

    while nfc_i < len(nfc):
        w = 1
        w2 = 1
        while True:
            fragment = unicodedata.normalize("NFC", text[raw_i : raw_i + w])
            if fragment == nfc[nfc_i : nfc_i + len(fragment)]:
                w2 = len(fragment)
                break
            w += 1
            if raw_i + w > len(text):
                w2 = len(nfc) - nfc_i
                break

        # The window text[raw_i:raw_i+w] maps to nfc[nfc_i:nfc_i+w2].
        # All output chars in the window share the raw span of the input window.
        raw_span_start = starts[raw_i]
        raw_span_end = ends[raw_i + w - 1]
        for _ in range(w2):
            out_starts.append(raw_span_start)
            out_ends.append(raw_span_end)

        raw_i += w
        nfc_i += w2

    return nfc, out_starts, out_ends


def _apply_whitespace_collapse(text: str, starts: list[int], ends: list[int]) -> _State:
    """Collapse whitespace runs to a single space and strip leading/trailing.

    A run of whitespace chars collapses to one space; its raw span covers the
    whole run (start of first char -> end of last char in the run).  Leading
    and trailing spaces are dropped entirely.
    """
    out_chars: list[str] = []
    out_starts: list[int] = []
    out_ends: list[int] = []
    i = 0

    while i < len(text):
        if text[i].isspace():
            # Start of a whitespace run.
            run_start = starts[i]
            run_end = ends[i]
            while i < len(text) and text[i].isspace():
                run_end = ends[i]
                i += 1
            out_chars.append(" ")
            out_starts.append(run_start)
            out_ends.append(run_end)
        else:
            out_chars.append(text[i])
            out_starts.append(starts[i])
            out_ends.append(ends[i])
            i += 1

    # Strip leading/trailing spaces.
    joined = "".join(out_chars)
    stripped = joined.strip()
    lead = len(joined) - len(joined.lstrip())
    s = out_starts[lead : lead + len(stripped)]
    e = out_ends[lead : lead + len(stripped)]
    return stripped, s, e


def _apply_punctuation_strip(text: str, starts: list[int], ends: list[int]) -> _State:
    """Remove punctuation characters (keeps \\w, \\s, hyphens, apostrophes)."""
    out_chars: list[str] = []
    out_starts: list[int] = []
    out_ends: list[int] = []
    for i, ch in enumerate(text):
        if not _PUNCTUATION.match(ch):
            out_chars.append(ch)
            out_starts.append(starts[i])
            out_ends.append(ends[i])
    return "".join(out_chars), out_starts, out_ends


def _apply_digit_strip(text: str, starts: list[int], ends: list[int]) -> _State:
    """Remove digit characters."""
    out_chars: list[str] = []
    out_starts: list[int] = []
    out_ends: list[int] = []
    for i, ch in enumerate(text):
        if not _DIGITS.match(ch):
            out_chars.append(ch)
            out_starts.append(starts[i])
            out_ends.append(ends[i])
    return "".join(out_chars), out_starts, out_ends


def _apply_casefold(text: str, starts: list[int], ends: list[int]) -> _State:
    """Apply str.casefold() while tracking raw provenance.

    Casefold can expand: ß->ss, ff->ff, etc.  All output chars from one input
    codepoint share that codepoint's raw (start, end).
    """
    out_chars: list[str] = []
    out_starts: list[int] = []
    out_ends: list[int] = []

    for i, ch in enumerate(text):
        folded = ch.casefold()
        for fc in folded:
            out_chars.append(fc)
            out_starts.append(starts[i])
            out_ends.append(ends[i])

    return "".join(out_chars), out_starts, out_ends


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_aligned(
    raw: str, profile: NormalizationProfile
) -> tuple[str, list[int], list[int]]:
    """Normalize ``raw`` per ``profile`` while tracking raw-char provenance.

    Returns ``(normalized, starts, ends)`` where both ``starts`` and ``ends``
    are ``list[int]`` of length ``len(normalized)``:

    - ``starts[i]`` -- first raw index that produced normalized char ``i``.
    - ``ends[i]``   -- one-past the last raw index consumed by normalized
      char ``i`` (exclusive, matching Python slice convention).

    For a normalized span ``[ns, ne)`` produced by automaton matching::

        raw_start = starts[ns]
        raw_end   = ends[ne - 1]
        surface   = raw[raw_start:raw_end]

    Raw surface recovery is always clean: the slice ``raw[starts[ns]:ends[ne-1]]``
    never splits a raw codepoint.  The round-trip invariant
    ``normalize_aligned(raw[starts[ns]:ends[ne-1]], profile)[0] == normalized[ns:ne]``
    holds for spans whose ``ne`` boundary does not fall between two normalized
    chars produced by the same raw codepoint (e.g. mid-casefold-expansion of
    ``ß`` → ``ss``).

    Supported flags: unicode_nfc, casefold, strip_whitespace,
    strip_punctuation, preserve_digits, decode_html_entities,
    strip_markdown_formatting.

    Raises:
        ValueError: If ``profile`` sets an unsupported flag
            (e.g. ``strip_diacritics=True``) -- never silently emits wrong
            offsets.
        ValueError: If the structural invariants of the returned maps are
            violated (guards against internal bugs in the transform chain).
    """
    _assert_supported_profile(profile)

    if not raw:
        return "", [], []

    text, s, e = _seed(raw)

    # --- Step 1: Markdown / HTML preprocessing ---
    # Replicate the _MD_HTML_HINT_RE short-circuit exactly (I2).
    if (
        profile.decode_html_entities or profile.strip_markdown_formatting
    ) and _MD_HTML_HINT_RE.search(text) is not None:
        if profile.decode_html_entities:
            text, s, e = _apply_html_unescape(text, s, e)
        if profile.strip_markdown_formatting:
            text, s, e = _apply_markdown_strip(text, s, e)

    # --- Step 2: NFC ---
    if profile.unicode_nfc:
        text, s, e = _apply_nfc(text, s, e)

    # (strip_diacritics + second NFC pass rejected above; not implemented.)

    # --- Step 3: Whitespace collapse ---
    if profile.strip_whitespace:
        text, s, e = _apply_whitespace_collapse(text, s, e)

    # --- Step 4: Punctuation strip ---
    if profile.strip_punctuation:
        text, s, e = _apply_punctuation_strip(text, s, e)
        if profile.strip_whitespace:
            text, s, e = _apply_whitespace_collapse(text, s, e)

    # --- Step 5: Digit strip ---
    if not profile.preserve_digits:
        text, s, e = _apply_digit_strip(text, s, e)
        if profile.strip_whitespace:
            text, s, e = _apply_whitespace_collapse(text, s, e)

    # --- Step 6: Casefold ---
    if profile.casefold:
        text, s, e = _apply_casefold(text, s, e)

    # --- Guardrail: assert structural invariants ---
    if len(s) != len(text) or len(e) != len(text):
        raise ValueError(
            f"normalize_aligned: map length mismatch -- "
            f"len(text)={len(text)}, len(starts)={len(s)}, len(ends)={len(e)}"
        )
    for j in range(len(text)):
        if e[j] < s[j]:
            raise ValueError(
                f"normalize_aligned: ends[{j}] < starts[{j}]: {e[j]} < {s[j]}"
            )
    for j in range(1, len(text)):
        if s[j] < s[j - 1]:
            raise ValueError(
                f"normalize_aligned: starts not non-decreasing at {j}: "
                f"starts[{j - 1}]={s[j - 1]}, starts[{j}]={s[j]}"
            )

    return text, s, e
