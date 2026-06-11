"""Normalizer protocol for domain-specific normalization.

The Normalizer protocol defines how names and codes are normalized
for deduplication during entity merging. Each domain pack provides
its own Normalizer with domain-specific rules.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class Normalizer(Protocol):
    """Protocol for domain-specific normalization.

    Normalization is used during entity merging to identify duplicates
    in names, codes, and relations lists. The normalizer provides
    domain-specific rules for what constitutes "the same" name or code.

    Example implementations:
    - GeoNormalizer: NFKC, lowercase, preserve diacritics
    - OrgNormalizer: NFKC, lowercase, strip legal suffixes (Inc, Ltd, GmbH)
    """

    def normalize_name(self, value: str) -> str:
        """Normalize a name for deduplication comparison.

        Typical operations: lowercase, Unicode NFKC, whitespace collapse,
        diacritic handling (domain-dependent).

        Args:
            value: Original name value

        Returns:
            Normalized name for comparison
        """
        ...

    def normalize_code(self, system: str, value: str) -> str:
        """Normalize a code value for deduplication comparison.

        May apply system-specific rules (e.g., ISO codes uppercase,
        LEI checksums stripped).

        Args:
            system: Code system name (e.g., "iso3", "lei")
            value: Original code value

        Returns:
            Normalized code for comparison
        """
        ...
