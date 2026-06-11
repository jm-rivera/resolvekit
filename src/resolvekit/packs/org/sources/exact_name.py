"""Exact name source for org entities."""

from resolvekit.core.engine import CandidateSource
from resolvekit.core.engine.tier_utils import REASON_TO_MATCH_TIER
from resolvekit.core.explain import emit_candidates_generated
from resolvekit.core.model import (
    CandidateEvidence,
    GenerationContext,
    ReasonCode,
)


class OrgExactNameSource(CandidateSource):
    """Exact name lookup for org entities.

    Searches canonical, legal, and short name kinds.
    """

    @property
    def name(self) -> str:
        return "org_exact_name"

    @property
    def reason_code(self) -> ReasonCode:
        return ReasonCode.EXACT_NAME_MATCH

    def supports(self, domain_pack_id: str) -> bool:
        return domain_pack_id == "org"

    def generate(self, ctx: GenerationContext) -> list[CandidateEvidence]:
        text_norm = ctx.text_norm
        evidence: list[CandidateEvidence] = []

        _tier = REASON_TO_MATCH_TIER.get(self.reason_code)
        # Try high-priority name kinds first
        for name_kind, score in [
            ("canonical", 1.0),
            ("legal", 0.98),
            ("short", 0.95),
        ]:
            entity_ids = ctx.store.lookup_name_exact(text_norm, name_kinds={name_kind})
            for eid in entity_ids[: ctx.budget - len(evidence)]:
                evidence.append(
                    CandidateEvidence(
                        entity_id=eid,
                        source_name=self.name,
                        raw_score=score,
                        rank=len(evidence) + 1,
                        matched_field=f"name.{name_kind}",
                        matched_value=text_norm,
                        match_tier=_tier,
                    )
                )

            if evidence:
                break  # Stop at first match tier

        emit_candidates_generated(
            ctx.trace,
            self.name,
            len(evidence),
            entity_ids=[e.entity_id for e in evidence],
            query=text_norm,
        )

        return evidence
