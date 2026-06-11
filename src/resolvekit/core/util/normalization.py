"""Text normalization utilities.

Core primitives for text normalization. Domain packs can create
custom profiles for domain-specific normalization rules.
"""

import html
import re
import unicodedata
from functools import lru_cache
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from resolvekit.core.model.query import NormalizedText

# Cache size for normalization results
NORMALIZATION_CACHE_SIZE: Final[int] = 4096


class NormalizationError(ValueError):
    """Raised when normalization produces an invalid result."""

    pass


class NormalizationProfile(BaseModel):
    """Configuration for text normalization.

    Domain packs can create custom profiles:
    - Geo: conservative diacritics, language-aware rules
    - Org: corporate suffix normalization, acronym handling

    Preset levels:
    - STRICT: Minimal normalization (NFC + casefold only)
    - STANDARD: Default normalization (NFC + casefold + whitespace)
    - AGGRESSIVE: Maximum normalization (all options enabled + diacritics removal)
    """

    model_config = ConfigDict(frozen=True)

    unicode_nfc: bool = Field(default=True, description="Apply NFC normalization")
    casefold: bool = Field(default=True, description="Apply Unicode casefolding")
    strip_whitespace: bool = Field(default=True, description="Normalize whitespace")
    strip_punctuation: bool = Field(default=False, description="Remove punctuation")
    preserve_digits: bool = Field(default=True, description="Keep numeric characters")
    strip_diacritics: bool = Field(
        default=False, description="Remove diacritical marks (accents)"
    )
    strip_markdown_formatting: bool = Field(
        default=False,
        description=(
            "Strip markdown emphasis markers (*/_/~/`) around words and "
            "leading block markers (#/@/>) before normalization."
        ),
    )
    decode_html_entities: bool = Field(
        default=False,
        description="Decode HTML entities (e.g. &amp; → &) before normalization.",
    )


# Preset normalization profiles
STRICT_PROFILE = NormalizationProfile(
    unicode_nfc=True,
    casefold=True,
    strip_whitespace=False,
    strip_punctuation=False,
    preserve_digits=True,
    strip_diacritics=False,
)

STANDARD_PROFILE = NormalizationProfile(
    unicode_nfc=True,
    casefold=True,
    strip_whitespace=True,
    strip_punctuation=False,
    preserve_digits=True,
    strip_diacritics=False,
)

AGGRESSIVE_PROFILE = NormalizationProfile(
    unicode_nfc=True,
    casefold=True,
    strip_whitespace=True,
    strip_punctuation=True,
    preserve_digits=True,
    strip_diacritics=True,
)


# Short-circuit guard: a single cheap search before running html.unescape and
# the markdown subs.  Inputs without any hint character skip the whole branch,
# which is ~10x faster than always running both passes.
_MD_HTML_HINT_RE: Final = re.compile(r"[&#@>*_~`]")

# Strip inline emphasis: *text*, **text**, _text_, ~~text~~, `text`, etc.
_MD_EMPHASIS_RE: Final = re.compile(r"[*_~`]+([^*_~`\n]+)[*_~`]+")

# Strip leading block markers: # heading, > blockquote, @mention at line start.
_MD_LEADING_RE: Final = re.compile(r"^[#@>]\s*", re.MULTILINE)


class TextNormalizer:
    """Core text normalizer with configurable profile.

    Provides shared normalization primitives used by all domain packs.
    Features LRU caching for improved batch performance.
    """

    # Whitespace pattern
    _WHITESPACE = re.compile(r"\s+")
    # Punctuation pattern (preserves hyphens and apostrophes by default)
    _PUNCTUATION = re.compile(r"[^\w\s\-']")
    # Digits pattern
    _DIGITS = re.compile(r"\d")

    def __init__(self, profile: NormalizationProfile | None = None) -> None:
        self._profile = profile or NormalizationProfile()
        # Create cached version of the core normalization logic
        self._cached_normalize = lru_cache(maxsize=NORMALIZATION_CACHE_SIZE)(
            self._normalize_impl
        )

    def _strip_diacritics(self, text: str) -> str:
        """Remove diacritical marks (accents) from text.

        Uses NFD normalization to decompose characters, then filters
        out combining diacritical marks.

        Args:
            text: Input text

        Returns:
            Text with diacritics removed
        """
        # Decompose to base char + combining marks
        decomposed = unicodedata.normalize("NFD", text)
        # Filter out combining diacritical marks (category 'Mn')
        return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")

    def _normalize_impl(self, text: str) -> str:
        """Core normalization implementation (cacheable).

        Args:
            text: Input text (must be non-empty)

        Returns:
            Normalized text
        """
        result = text

        # Markdown / HTML preprocessing — applied BEFORE NFC so that entity
        # decoding and stripped markers don't interfere with Unicode composition.
        # Short-circuit: one cheap regex.search before the heavier unescape/sub calls.
        if (
            self._profile.decode_html_entities
            or self._profile.strip_markdown_formatting
        ) and _MD_HTML_HINT_RE.search(result) is not None:
            if self._profile.decode_html_entities:
                result = html.unescape(result)
            if self._profile.strip_markdown_formatting:
                result = _MD_LEADING_RE.sub("", result)
                result = _MD_EMPHASIS_RE.sub(r"\1", result)

        # Unicode NFC normalization
        if self._profile.unicode_nfc:
            result = unicodedata.normalize("NFC", result)

        # Diacritics removal (before casefolding for better results)
        if self._profile.strip_diacritics:
            result = self._strip_diacritics(result)
            # Re-normalize to NFC after diacritics removal
            if self._profile.unicode_nfc:
                result = unicodedata.normalize("NFC", result)

        # Whitespace normalization
        if self._profile.strip_whitespace:
            result = self._WHITESPACE.sub(" ", result).strip()

        # Punctuation stripping
        if self._profile.strip_punctuation:
            result = self._PUNCTUATION.sub("", result)
            # Re-strip whitespace after punctuation removal
            if self._profile.strip_whitespace:
                result = self._WHITESPACE.sub(" ", result).strip()

        # Digit stripping (when preserve_digits is False)
        if not self._profile.preserve_digits:
            result = self._DIGITS.sub("", result)
            # Re-strip whitespace after digit removal
            if self._profile.strip_whitespace:
                result = self._WHITESPACE.sub(" ", result).strip()

        # Casefolding (more aggressive than lower())
        if self._profile.casefold:
            result = result.casefold()

        return result

    def normalize(self, text: str) -> str:
        """Normalize text according to profile.

        Results are cached for improved batch performance.

        Args:
            text: Input text (must be non-empty)

        Returns:
            Normalized text (guaranteed non-empty)

        Raises:
            NormalizationError: If input is empty or normalization produces empty result
        """
        if not text:
            raise NormalizationError("Cannot normalize empty string")

        result = self._cached_normalize(text)

        # Validate non-empty result
        if not result:
            raise NormalizationError(
                f"Normalization produced empty result from input: {text!r}"
            )

        return result

    def normalize_with_original(self, text: str) -> NormalizedText:
        """Normalize and return both original and normalized forms.

        Args:
            text: Input text (must be non-empty)

        Returns:
            NormalizedText with both forms

        Raises:
            NormalizationError: If input is empty or normalization produces empty result
        """
        return NormalizedText(
            original=text,
            normalized=self.normalize(text),
        )

    def tokenize(self, text: str) -> list[str]:
        """Split normalized text into tokens.

        Args:
            text: Normalized text

        Returns:
            List of tokens
        """
        return text.split()

    def cache_info(self) -> Any:
        """Return cache statistics for monitoring."""
        return self._cached_normalize.cache_info()

    def cache_clear(self) -> None:
        """Clear the normalization cache."""
        self._cached_normalize.cache_clear()


def fold_for_match(text: str) -> str:
    """Fold ``text`` for diacritic-insensitive matching.

    Applies NFC normalization, Unicode casefolding, and strips combining
    diacritical marks (Unicode category ``Mn``).  The result is suitable for
    ``str.startswith`` / ``str.find`` comparisons against a folded query.

    Example::

        fold_for_match("São Paulo") == "sao paulo"
        fold_for_match("Côte d'Ivoire") == "cote d'ivoire"

    Args:
        text: Input string.

    Returns:
        Folded string with diacritics removed.
    """
    nfc = unicodedata.normalize("NFC", text)
    casefolded = nfc.casefold()
    decomposed = unicodedata.normalize("NFD", casefolded)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def fold_with_offsets(text: str) -> tuple[str, list[int]]:
    """Fold ``text`` and return a code-point offset map.

    Applies the same folding as :func:`fold_for_match` but also builds
    ``offset_map`` where ``offset_map[i]`` is the original code-point index
    for folded index ``i``.  This handles casefold expansions (e.g.
    ``"ß"`` → ``"ss"``, both mapping back to original index 0) so that
    highlight span detection can round-trip across the normalization boundary.

    Example::

        folded, offsets = fold_with_offsets("Côte")
        # folded == "cote", offsets == [0, 1, 2, 3]

        folded, offsets = fold_with_offsets("ß")
        # folded == "ss", offsets == [0, 0]

    Args:
        text: Input string.

    Returns:
        A 2-tuple ``(folded_str, offset_map)`` where ``offset_map`` has
        one entry per code point in ``folded_str``.
    """
    nfc = unicodedata.normalize("NFC", text)
    folded_chars: list[str] = []
    offset_map: list[int] = []

    for orig_idx, orig_char in enumerate(nfc):
        # Casefold may expand one char into multiple (e.g. "ß" → "ss").
        expanded = orig_char.casefold()
        # Strip diacritics from the expanded form.
        decomposed = unicodedata.normalize("NFD", expanded)
        for c in decomposed:
            if unicodedata.category(c) != "Mn":
                folded_chars.append(c)
                offset_map.append(orig_idx)

    return "".join(folded_chars), offset_map
