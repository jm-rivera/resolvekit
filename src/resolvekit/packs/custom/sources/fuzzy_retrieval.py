"""Brute-force fuzzy retrieval source for custom entities."""

from resolvekit.shared.sources import FuzzyRetrievalBruteSource


class CustomFuzzyRetrievalSource(FuzzyRetrievalBruteSource):
    """Generating fuzzy source for the custom domain.

    Materializes the store's name list once and runs brute-force
    RapidFuzz over it — no prebuilt SymSpell dictionary required.
    Ordered before the rerank ``CustomFuzzySource`` so the engine
    enriches its FUZZY-tier candidates with ``fuzzy_edit_sim`` /
    ``fuzzy_token_sim`` signals before scoring.
    """

    def __init__(self) -> None:
        super().__init__(name="custom_fuzzy_retrieval", domain="custom")
