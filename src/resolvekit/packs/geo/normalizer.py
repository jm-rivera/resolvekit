"""Geo-specific normalizer for entity deduplication."""

from resolvekit.core.linking import BaseNormalizer


class GeoNormalizer(BaseNormalizer):
    """Normalizer for geo domain entities.

    - Names: NFKC, lowercase, preserve diacritics, collapse whitespace
    - Codes: casefold (ISO codes stored lowercase; dcid stored lowercase)
    """
