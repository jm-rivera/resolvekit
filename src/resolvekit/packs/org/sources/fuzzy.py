"""Fuzzy matching source for org entities."""

from resolvekit.shared import FuzzySource


class OrgFuzzySource(FuzzySource):
    """Fuzzy matching for org entities.

    Uses token_set_ratio which is better for org names
    (handles word order variations like "Bank World" vs "World Bank").
    """

    def __init__(self) -> None:
        super().__init__(
            name="org_fuzzy",
            domain="org",
            edit_weight=0.4,  # Less weight on character similarity
            token_weight=0.6,  # More weight on word-level matching
        )
