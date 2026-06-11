"""Full-text search source for geo entities."""

from resolvekit.core.model import CandidateEvidence, GenerationContext
from resolvekit.packs.geo.sources._short_input import short_input_blocked
from resolvekit.packs.geo.sources.query_shapes import is_geo_code_like_query
from resolvekit.shared.sources import FTSSource


class GeoFTSSource(FTSSource):
    """Full-text search for geo entities using FTS5 BM25.

    Returns ranked candidates with normalized BM25 scores.
    """

    def __init__(self) -> None:
        super().__init__(
            name="geo_fts",
            domain="geo",
            min_query_length=2,  # Geo codes can be short
            # Uses default BM25ScoreTiers
        )

    def generate(self, ctx: GenerationContext) -> list[CandidateEvidence]:
        """Skip expensive FTS for obvious code-like inputs and degenerate
        short/noise inputs.
        """
        if is_geo_code_like_query(ctx.query.raw_text, ctx.text_norm):
            return []
        if short_input_blocked(ctx.query.raw_text, ctx.text_norm, ctx.context):
            return []
        return super().generate(ctx)
