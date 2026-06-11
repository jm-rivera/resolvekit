"""SymSpell-based typo-tolerant source for geo entities."""

from typing import Any, override

from resolvekit.core.engine.tier_utils import REASON_TO_MATCH_TIER
from resolvekit.core.model import (
    CandidateEvidence,
    GenerationContext,
    MatchTier,
    ReasonCode,
)
from resolvekit.core.store import EntityStore
from resolvekit.packs.geo.sources._short_input import short_input_blocked
from resolvekit.packs.geo.sources.query_shapes import is_geo_code_like_query
from resolvekit.shared.sources import SymSpellSource
from resolvekit.shared.sources.symspell_base import (
    SYMSPELL_BASE_SCORE,
    SYMSPELL_DISTANCE_PENALTY,
    SYMSPELL_MIN_SCORE,
)

# When SymSpell corrects a typo to an indexed exact-name term within this many
# edits, we treat it as an exact_name hit (with the same raw score the symspell
# evidence would carry). This rescues short obvious typos like "Mexco"->"Mexico"
# from being scored via the weaker fuzzy heuristic.
SYMSPELL_EXACT_NAME_MAX_EDIT_DISTANCE = 1

# Queries shorter than this get ambiguous edit-1 corrections too easily
# (e.g. "Pers"->"Peru", "Turk"->"Turkey"/"Turks", "Neth"->"Niger") — abstain
# from promoting their SymSpell hits to exact_name.
SYMSPELL_EXACT_NAME_MIN_QUERY_LEN = 5

# SymSpell.lookup cache size. Country queries cluster on a small vocabulary,
# so a single-process LRU eliminates most repeat work for hot terms.
_LOOKUP_CACHE_MAX = 8192

# Main symspell evidence tier: FTS-level, not exact — loop-invariant constant.
_SYMSPELL_TIER = REASON_TO_MATCH_TIER.get(ReasonCode.FTS_MATCH)

# Entity-type prefixes that belong to the SMALL index group (countries, admin1,
# regions, continents, continental unions). Used to gate the LARGE index.
_SMALL_ENTITY_TYPE_PREFIXES: frozenset[str] = frozenset(
    {
        "geo.country",
        "geo.admin1",
        "geo.region",
        "geo.subregion",
        "geo.continent",
        "geo.continental_union",
        "geo.organization",
    }
)


def _is_small_only_entity_types(entity_types: frozenset[str] | None) -> bool:
    """Return True when every declared entity type belongs to the SMALL group.

    Used by both GeoSymSpellSource and GeoFuzzyRetrievalSource to skip the LARGE
    index for queries that are typed exclusively to small-tier entities.
    """
    if not entity_types:
        return False
    return all(
        any(et.startswith(prefix) for prefix in _SMALL_ENTITY_TYPE_PREFIXES)
        for et in entity_types
    )


def install_symspell_lookup_cache(sym_spell: Any) -> None:
    """Wrap a SymSpell instance's lookup() in a small LRU cache.

    Most multi-word queries route through symspellpy's lookup_compound, which
    fans out to per-word lookup() calls internally. The same words recur often
    across queries and across sources (geo_symspell + geo_fuzzy_retrieval both
    consult the same SymSpell index), so a cache earns hits on every repeat.
    Idempotent: safe to call multiple times; only the first installs the wrap.
    """
    if sym_spell is None or getattr(sym_spell, "_resolvekit_lookup_cached", False):
        return
    orig_lookup = sym_spell.lookup
    cache: dict[tuple, Any] = {}

    def cached_lookup(text: str, *args: Any, **kwargs: Any) -> Any:
        key = (text, args, tuple(sorted(kwargs.items())))
        cached = cache.get(key)
        if cached is not None:
            return cached
        if len(cache) >= _LOOKUP_CACHE_MAX:
            cache.clear()
        result = orig_lookup(text, *args, **kwargs)
        cache[key] = result
        return result

    sym_spell.lookup = cached_lookup
    sym_spell._resolvekit_lookup_cached = True


class GeoSymSpellSource(SymSpellSource):
    """SymSpell-based typo tolerance for geo entities.

    Uses edit distance to find candidates for misspelled queries.
    Optional artifact per DataPack - only active if symspell dict exists.
    Falls back to prefix search when dictionary is unavailable.

    The SymSpell index is built lazily on first use (see ``SymSpellSource``).
    After the build, an LRU lookup cache is installed automatically.

    When ``large_tier=True``, this source covers admin2-5 / cities.  Queries
    whose ``ResolutionContext.entity_types`` contain only SMALL-group types
    (countries, admin1, regions, continents, continental unions) are skipped so
    the LARGE index is never built for country-only resolvers.
    """

    def __init__(
        self,
        dictionary_path: str | None = None,
        max_edit_distance: int = 2,
        prefix_length: int = 7,
        discount_factor: float = 0.8,
        name: str = "geo_symspell",
        large_tier: bool = False,
    ):
        super().__init__(
            name=name,
            domain="geo",
            dictionary_path=dictionary_path,
            max_edit_distance=max_edit_distance,
            prefix_length=prefix_length,
        )
        self._discount = discount_factor
        self._large_tier = large_tier

    def _do_build(self) -> None:
        """Build the index and install the lookup cache afterwards."""
        super()._do_build()
        install_symspell_lookup_cache(self._sym_spell)

    def _generate_fallback(
        self, text_norm: str, store: EntityStore, budget: int
    ) -> list[CandidateEvidence]:
        """Fallback: generate candidates using prefix search."""
        evidence: list[CandidateEvidence] = []

        prefix = text_norm[:4] if len(text_norm) >= 4 else text_norm

        results = store.search_prefix(prefix, "name", limit=budget)

        for entity_id, score, rank in results:
            # Apply discount to prefix matches (less confident than exact)
            edit_score = score * self._discount

            evidence.append(
                CandidateEvidence(
                    entity_id=entity_id,
                    source_name=self.name,
                    raw_score=edit_score,
                    rank=rank,
                    matched_field="symspell",
                    matched_value=text_norm,
                )
            )

        return evidence

    @override
    def _process_suggestion(
        self,
        *,
        corrected: str,
        edit_distance: int,
        entity_id: str,
        text_norm: str,
        rank: int,
    ) -> list[CandidateEvidence]:
        """Emit tier-stamped evidence; promote near-distance corrections to exact_name tier.

        When the SymSpell-corrected term is within SYMSPELL_EXACT_NAME_MAX_EDIT_DISTANCE
        edits and the query is at least SYMSPELL_EXACT_NAME_MIN_QUERY_LEN characters,
        an additional synthetic evidence record is emitted with match_tier=EXACT_NAME.
        This rescues short obvious typos like "Mexco"->"Mexico" from the weaker fuzzy path.
        """
        score = max(
            SYMSPELL_MIN_SCORE,
            SYMSPELL_BASE_SCORE - (edit_distance * SYMSPELL_DISTANCE_PENALTY),
        )
        signals = {"symspell_edit_distance": float(edit_distance)}
        records: list[CandidateEvidence] = [
            CandidateEvidence(
                entity_id=entity_id,
                source_name=self.name,
                raw_score=score,
                rank=rank,
                matched_field=self._matched_field,
                matched_value=corrected,
                signals=signals,
                match_tier=_SYMSPELL_TIER,
            )
        ]
        if (
            edit_distance <= SYMSPELL_EXACT_NAME_MAX_EDIT_DISTANCE
            and len(text_norm) >= SYMSPELL_EXACT_NAME_MIN_QUERY_LEN
        ):
            records.append(
                CandidateEvidence(
                    entity_id=entity_id,
                    source_name=f"{self.name}_exact_name",
                    raw_score=score,
                    rank=rank,
                    matched_field="exact_name",
                    matched_value=corrected,
                    signals=signals,
                    match_tier=MatchTier.EXACT_NAME,
                )
            )
        return records

    def generate(self, ctx: GenerationContext) -> list[CandidateEvidence]:
        """Skip typo correction for obvious code-like inputs and degenerate
        short/noise inputs (single letters, ``#N/A``).

        When this is the LARGE-tier source, also skip if the query context
        declares only SMALL-group entity types — the LARGE index is never built
        for country/admin1-only resolvers.
        """
        if self._large_tier and _is_small_only_entity_types(ctx.context.entity_types):
            return []
        if is_geo_code_like_query(ctx.query.raw_text, ctx.text_norm):
            return []
        if short_input_blocked(ctx.query.raw_text, ctx.text_norm, ctx.context):
            return []
        return super().generate(ctx)
