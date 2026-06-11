"""Exact code source for org entities."""

import re

from resolvekit.core.engine import CandidateSource
from resolvekit.core.engine.tier_utils import REASON_TO_MATCH_TIER
from resolvekit.core.explain import emit_candidates_generated
from resolvekit.core.model import (
    CandidateEvidence,
    GenerationContext,
    ReasonCode,
)
from resolvekit.shared.sources import evidence_from_code_hits

# Code patterns for org entities
WIKIDATA_PATTERN = re.compile(r"^q\d+$", re.IGNORECASE)


class OrgExactCodeSource(CandidateSource):
    """Exact code lookup for org entities.

    Supports:
    - Wikidata QID (Q458 for EU)
    - Internal org IDs
    - Registry IDs
    """

    @property
    def name(self) -> str:
        return "org_exact_code"

    @property
    def reason_code(self) -> ReasonCode:
        return ReasonCode.EXACT_CODE_MATCH

    def supports(self, domain_pack_id: str) -> bool:
        return domain_pack_id == "org"

    def generate(self, ctx: GenerationContext) -> list[CandidateEvidence]:
        text = ctx.text_norm
        evidence: list[CandidateEvidence] = []

        _tier = REASON_TO_MATCH_TIER.get(self.reason_code)
        # Try Wikidata
        if WIKIDATA_PATTERN.match(text):
            entity_ids = ctx.store.lookup_code("wikidata", text.lower())
            for i, eid in enumerate(entity_ids[: ctx.budget]):
                evidence.append(
                    CandidateEvidence(
                        entity_id=eid,
                        source_name=self.name,
                        raw_score=1.0,
                        rank=i + 1,
                        matched_field="code.wikidata",
                        matched_value=text.upper(),
                        match_tier=_tier,
                    )
                )

        # Catch-all fallback when prioritized lookups miss
        if not evidence:
            evidence = evidence_from_code_hits(
                ctx.store.lookup_code_any(text),
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
            query=text,
        )

        return evidence
