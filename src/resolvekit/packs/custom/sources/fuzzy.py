"""Fuzzy matching source for custom entities."""

from resolvekit.shared.sources import FuzzySource


class CustomFuzzySource(FuzzySource):
    """Fuzzy matching for custom entities.

    Reranks candidates already collected by FTS/exact sources.
    Uses equal weights (0.5, 0.5) — no domain-specific preference for
    character vs word-level similarity in programmatically-built packs.
    """

    def __init__(self) -> None:
        super().__init__(
            name="custom_fuzzy",
            domain="custom",
            edit_weight=0.5,
            token_weight=0.5,
        )
