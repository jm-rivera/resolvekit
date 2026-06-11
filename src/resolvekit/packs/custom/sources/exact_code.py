"""Exact code source for custom entities."""

from resolvekit.core.engine import CandidateSource
from resolvekit.core.engine.tier_utils import REASON_TO_MATCH_TIER
from resolvekit.core.explain import emit_candidates_generated
from resolvekit.core.model import (
    CandidateEvidence,
    GenerationContext,
    ReasonCode,
)
from resolvekit.shared.sources import evidence_from_code_hits


class CustomExactCodeSource(CandidateSource):
    """Exact code lookup for custom entities.

    Uses a catch-all ``lookup_code_any`` over all systems — custom packs have
    no catalog cross-reference noise, so the geo-style allowlist is unnecessary.
    """

    @property
    def name(self) -> str:
        return "custom_exact_code"

    @property
    def reason_code(self) -> ReasonCode:
        return ReasonCode.EXACT_CODE_MATCH

    def supports(self, domain_pack_id: str) -> bool:
        return domain_pack_id == "custom"

    def generate(self, ctx: GenerationContext) -> list[CandidateEvidence]:
        text_norm = ctx.text_norm
        _tier = REASON_TO_MATCH_TIER.get(self.reason_code)

        hits = ctx.store.lookup_code_any(text_norm)
        evidence = evidence_from_code_hits(
            hits,
            source_name=self.name,
            matched_value=ctx.query.raw_text,
            budget=ctx.budget,
            match_tier=_tier,
        )

        emit_candidates_generated(
            ctx.trace,
            self.name,
            len(evidence),
            entity_ids=[e.entity_id for e in evidence],
            query=text_norm,
        )

        return evidence
