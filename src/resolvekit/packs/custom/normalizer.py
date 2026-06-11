"""Custom-domain normalizer — thin BaseNormalizer subclass.

Build-time and query-time normalization agree for custom data because
both use this class (or its parent, BaseNormalizer, which is identical
in behaviour).  No code-casing overrides are needed: custom packs have
no fixed catalog, so values are stored and queried in the form they
arrived.
"""

from resolvekit.core.linking import BaseNormalizer


class CustomNormalizer(BaseNormalizer):
    """Normalizer for the custom domain.

    Inherits all defaults from BaseNormalizer:
    - Names: NFKC, lowercase, collapse whitespace.
    - Codes: strip surrounding whitespace; preserve case (no system-
      specific uppercase rules — custom packs have no structured catalog).
    """
