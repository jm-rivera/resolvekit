"""Fuzzy matching source for geo entities."""

import time

from rapidfuzz import fuzz

from resolvekit.core.engine.tier_utils import REASON_TO_MATCH_TIER
from resolvekit.core.explain import emit_candidates_generated
from resolvekit.core.model import CandidateEvidence, GenerationContext
from resolvekit.packs.geo.sources._short_input import short_input_blocked
from resolvekit.shared.sources import FuzzySource

# Below this many existing candidates, fall back to per-entity cached fetches
# instead of the bulk_get_entities query that hits SQLite for entities, names,
# codes, and relations. Most queries have 1-3 candidates and benefit from the
# per-instance LRU cache on get_entity.
_BULK_FETCH_THRESHOLD = 8


class GeoFuzzySource(FuzzySource):
    """Fuzzy matching source for geo entities.

    Uses edit distance and token similarity to rerank existing candidates.
    This is a "lazy" source - it only refines candidates from other sources.
    """

    def __init__(self, edit_weight: float = 0.6, token_weight: float = 0.4):
        super().__init__(
            name="geo_fuzzy",
            domain="geo",
            edit_weight=edit_weight,
            token_weight=token_weight,
        )

    def generate(self, ctx: GenerationContext) -> list[CandidateEvidence]:
        """Generate fuzzy evidence for existing candidates.

        Specialised over the shared FuzzySource: when the candidate set is
        small (the common case for geo lookups), individual cached
        get_entity calls beat the 4-statement bulk_get_entities query.
        """
        if not ctx.existing_candidates:
            return []

        # Don't rerank candidates produced for degenerate inputs. If a
        # punctuation-noise token like "#N/A" survived to this point because
        # an upstream source mis-fired, suppress the rerank rather than
        # propagate confidence.
        if short_input_blocked(ctx.query.raw_text, ctx.text_norm, ctx.context):
            return []

        deadline = ctx.deadline
        if deadline is not None and time.monotonic() >= deadline:
            return []

        text_norm = ctx.text_norm
        evidence: list[CandidateEvidence] = []
        candidates = ctx.existing_candidates[: ctx.budget]

        # Pick the cheaper fetch path based on candidate count.
        if len(candidates) <= _BULK_FETCH_THRESHOLD:
            entities = {}
            for c in candidates:
                ent = ctx.store.get_entity(c.entity_id)
                if ent is not None:
                    entities[c.entity_id] = ent
        else:
            entities = ctx.store.bulk_get_entities([c.entity_id for c in candidates])

        edit_w = self._edit_weight
        token_w = self._token_weight
        _tier = REASON_TO_MATCH_TIER.get(self.reason_code)

        for i, candidate in enumerate(candidates):
            if i % 4 == 0 and deadline is not None and time.monotonic() >= deadline:
                break
            entity = entities.get(candidate.entity_id)
            if not entity:
                continue

            # Build deduplicated list of all name variants to score against
            seen: set[str] = set()
            all_name_norms: list[str] = []
            canon = entity.canonical_name_norm
            seen.add(canon)
            all_name_norms.append(canon)
            for nr in entity.names:
                nv = nr.value_norm
                if nv not in seen:
                    seen.add(nv)
                    all_name_norms.append(nv)

            # Find the best-matching variant
            best_combined = -1.0
            best_edit_sim = 0.0
            best_token_sim = 0.0
            best_name_norm = canon

            for name_norm in all_name_norms:
                edit_sim = fuzz.ratio(text_norm, name_norm) / 100.0
                token_sim = fuzz.token_set_ratio(text_norm, name_norm) / 100.0
                combined = (edit_w * edit_sim) + (token_w * token_sim)
                if combined > best_combined:
                    best_combined = combined
                    best_edit_sim = edit_sim
                    best_token_sim = token_sim
                    best_name_norm = name_norm

            evidence.append(
                CandidateEvidence(
                    entity_id=candidate.entity_id,
                    source_name=self.name,
                    raw_score=best_combined,
                    rank=len(evidence) + 1,
                    matched_field="fuzzy",
                    matched_value=best_name_norm,
                    signals={
                        "fuzzy_edit_sim": best_edit_sim,
                        "fuzzy_token_sim": best_token_sim,
                    },
                    match_tier=_tier,
                )
            )

        emit_candidates_generated(
            ctx.trace,
            self.name,
            len(evidence),
            entity_ids=[e.entity_id for e in evidence],
        )

        return evidence
