"""Full-text search source for custom entities."""

from resolvekit.shared.sources import BM25ScoreTiers, FTSSource

# Score tiers match the org pack defaults; custom data has no special BM25 tuning.
_CUSTOM_SCORE_TIERS = BM25ScoreTiers(
    rank_1=0.85,
    rank_2_3=0.75,
    rank_4_10=0.65,
    rank_11_20=0.55,
    default=0.45,
)


class CustomFTSSource(FTSSource):
    """Full-text search for custom entities."""

    def __init__(self) -> None:
        super().__init__(
            name="custom_fts",
            domain="custom",
            min_query_length=2,
            score_tiers=_CUSTOM_SCORE_TIERS,
        )
