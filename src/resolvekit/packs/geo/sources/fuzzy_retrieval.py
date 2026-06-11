"""Fuzzy retrieval source for geo entities."""

from resolvekit.core.model import CandidateEvidence, GenerationContext, MatchTier
from resolvekit.packs.geo.sources._short_input import short_input_blocked
from resolvekit.packs.geo.sources.symspell import _is_small_only_entity_types
from resolvekit.shared.sources.fuzzy_retrieval_base import FuzzyRetrievalSource


class GeoFuzzyRetrievalSource(FuzzyRetrievalSource):
    """Fuzzy retrieval source for geo entities.

    Corrects individual words in the query using SymSpell and looks up the
    corrected phrase. Unlike GeoFuzzySource (which reranks existing candidates),
    this source retrieves candidates independently for typo-heavy queries where
    no other source finds matches.

    Declares tier=FUZZY so the engine's skip logic can identify this source
    by tier rather than by name suffix.

    When ``large_tier=True``, this source covers admin2-5 / cities and skips
    queries typed exclusively to SMALL-group entity types so the LARGE index is
    never built for country-only resolvers.
    """

    # Source-level tier declaration.
    tier = MatchTier.FUZZY

    def __init__(
        self,
        dictionary_path: str | None = None,
        name: str = "geo_fuzzy_retrieval",
        large_tier: bool = False,
    ):
        super().__init__(
            name=name,
            domain="geo",
            dictionary_path=dictionary_path,
            name_kinds={"canonical", "alias", "endonym", "exonym"},
        )
        self._large_tier = large_tier

    def generate(self, ctx: GenerationContext) -> list[CandidateEvidence]:
        """Skip retrieval for degenerate inputs that should never match a geo
        entity (single letters, lowercase short alpha, ``#N/A``-style noise).

        When this is the LARGE-tier source, also skip if the query context
        declares only SMALL-group entity types.
        """
        if self._large_tier and _is_small_only_entity_types(ctx.context.entity_types):
            return []
        if short_input_blocked(ctx.query.raw_text, ctx.text_norm, ctx.context):
            return []
        return super().generate(ctx)
