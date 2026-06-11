"""Org-specific normalizer for entity deduplication."""

import re

from resolvekit.core.linking import BaseNormalizer


class OrgNormalizer(BaseNormalizer):
    """Normalizer for org domain entities.

    - Names: NFKC, lowercase, strip legal suffixes, collapse whitespace
    - Codes: casefold (LEI/ticker stored lowercase); DUNS also strips dashes
    """

    # Common legal suffixes to strip (case-insensitive)
    _LEGAL_SUFFIXES = re.compile(
        r",?\s*\b(?:"
        r"inc\.?|"
        r"incorporated|"
        r"corp\.?|"
        r"corporation|"
        r"ltd\.?|"
        r"limited|"
        r"llc\.?|"
        r"l\.l\.c\.?|"
        r"plc\.?|"
        r"ag|"
        r"gmbh|"
        r"sa|"
        r"s\.a\.?|"
        r"co\.?|"
        r"company"
        r")\s*$",
        re.IGNORECASE,
    )

    def normalize_name(self, value: str) -> str:
        """Normalize an organization name, stripping legal suffixes."""
        result = super().normalize_name(value)
        # Strip legal suffixes after base normalization
        return self._LEGAL_SUFFIXES.sub("", result).strip()

    def _normalize_code_extra(self, system: str, value: str) -> str:
        """Strip dashes from DUNS codes."""
        if system == "duns":
            return value.replace("-", "")
        return value
