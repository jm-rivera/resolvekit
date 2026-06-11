"""Base normalizer with common normalization logic."""

import re
import unicodedata


class BaseNormalizer:
    """Base class for domain-specific normalizers.

    Provides common normalization utilities:
    - NFKC Unicode normalization
    - Whitespace collapsing
    - System-specific code normalization (casefold by default)

    Subclasses can override methods or extend with domain-specific rules.
    """

    _WHITESPACE = re.compile(r"\s+")

    def normalize_name(self, value: str) -> str:
        """Normalize a name for deduplication.

        Default implementation: NFKC + collapse whitespace + lowercase.
        Override in subclasses for domain-specific rules.

        Args:
            value: Original name value

        Returns:
            Normalized name for comparison
        """
        result = unicodedata.normalize("NFKC", value)
        result = self._WHITESPACE.sub(" ", result).strip()
        return result.lower()

    def normalize_code(self, system: str, value: str) -> str:
        """Normalize a code value for deduplication.

        Default: strip + casefold, then _normalize_code_extra for domain rules.
        Override _normalize_code_extra for additional transforms (e.g., DUNS dash removal).

        Args:
            system: Code system name
            value: Original code value

        Returns:
            Normalized code for comparison
        """
        result = value.strip().casefold()
        return self._normalize_code_extra(system, result)

    def _normalize_code_extra(self, system: str, value: str) -> str:
        """Hook for domain-specific code normalization.

        Override in subclasses for additional rules (e.g., DUNS dash removal).
        Default implementation returns value unchanged.
        """
        return value
