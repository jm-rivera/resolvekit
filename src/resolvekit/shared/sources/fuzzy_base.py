"""Shared fuzzy matching source implementation.

Uses edit distance and token similarity to rerank existing candidates.
"""

import time

from rapidfuzz import fuzz

from resolvekit.core.engine import CandidateSource
from resolvekit.core.engine.tier_utils import REASON_TO_MATCH_TIER
from resolvekit.core.explain import emit_candidates_generated
from resolvekit.core.model import (
    CandidateEvidence,
    GenerationContext,
    ReasonCode,
)


class FuzzySource(CandidateSource):
    """Fuzzy matching source for reranking existing candidates.

    Uses a weighted combination of:
    - Edit distance similarity (character-level)
    - Token set ratio (word-level, handles word order variations)

    This is a "lazy" source - it only refines candidates from other sources.

    Configurable parameters:
    - name: Source name for tracing
    - domain: Domain pack ID this source supports
    - edit_weight: Weight for edit distance similarity (default: 0.5)
    - token_weight: Weight for token set ratio (default: 0.5)
    """

    def __init__(
        self,
        name: str,
        domain: str,
        edit_weight: float = 0.5,
        token_weight: float = 0.5,
    ):
        """Create a fuzzy source.

        Args:
            name: Unique name for this source
            domain: Domain pack ID this source supports
            edit_weight: Weight for edit distance similarity
            token_weight: Weight for token set ratio

        Note:
            - Orgs typically use (0.4, 0.6) to prefer word order flexibility
            - Geos typically use (0.6, 0.4) to prefer strict character similarity
        """
        self._name = name
        self._domain = domain
        self._edit_weight = edit_weight
        self._token_weight = token_weight

    @property
    def name(self) -> str:
        return self._name

    @property
    def reason_code(self) -> ReasonCode:
        return ReasonCode.FUZZY_MATCH

    def supports(self, domain_pack_id: str) -> bool:
        return domain_pack_id == self._domain

    @property
    def requires_existing_candidates(self) -> bool:
        return True

    def generate(self, ctx: GenerationContext) -> list[CandidateEvidence]:
        """Generate fuzzy evidence for existing candidates.

        Deadline checks are cooperative — they occur between candidate
        iterations, not within a single rapidfuzz call.
        """
        if not ctx.existing_candidates:
            return []

        deadline = ctx.deadline
        if deadline is not None and time.monotonic() >= deadline:
            return []
        text_norm = ctx.text_norm
        _tier = REASON_TO_MATCH_TIER.get(self.reason_code)
        evidence: list[CandidateEvidence] = []

        # Get entities for candidates
        entity_ids = [c.entity_id for c in ctx.existing_candidates[: ctx.budget]]
        entities = ctx.store.bulk_get_entities(entity_ids)

        for i, candidate in enumerate(ctx.existing_candidates[: ctx.budget]):
            if i % 4 == 0 and deadline is not None and time.monotonic() >= deadline:
                break
            entity = entities.get(candidate.entity_id)
            if not entity:
                continue

            # Build deduplicated list of all name variants to score against
            seen: set[str] = set()
            all_name_norms: list[str] = []
            for name_norm in [entity.canonical_name_norm] + [
                nr.value_norm for nr in entity.names
            ]:
                if name_norm not in seen:
                    seen.add(name_norm)
                    all_name_norms.append(name_norm)

            # Find the best-matching variant
            best_combined = -1.0
            best_edit_sim = 0.0
            best_token_sim = 0.0
            best_name_norm = entity.canonical_name_norm

            for name_norm in all_name_norms:
                edit_sim = fuzz.ratio(text_norm, name_norm) / 100.0
                token_sim = fuzz.token_set_ratio(text_norm, name_norm) / 100.0
                combined = (self._edit_weight * edit_sim) + (
                    self._token_weight * token_sim
                )
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
