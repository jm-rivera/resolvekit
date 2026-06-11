"""Full-text search source for org entities."""

from resolvekit.shared import BM25ScoreTiers, FTSSource

# Org-specific score tiers (slightly lower than geo due to more ambiguous names)
_ORG_SCORE_TIERS = BM25ScoreTiers(
    rank_1=0.80,
    rank_2_3=0.70,
    rank_4_10=0.60,
    rank_11_20=0.50,
    default=0.50,
)


class OrgFTSSource(FTSSource):
    """Full-text search for org entities."""

    def __init__(self) -> None:
        super().__init__(
            name="org_fts",
            domain="org",
            min_query_length=3,  # Org names tend to be longer
            score_tiers=_ORG_SCORE_TIERS,
        )
