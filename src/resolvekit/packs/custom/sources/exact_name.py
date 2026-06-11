"""Exact name source for custom entities."""

from resolvekit.core.engine import CandidateSource
from resolvekit.core.engine.tier_utils import REASON_TO_MATCH_TIER
from resolvekit.core.explain import emit_candidates_generated
from resolvekit.core.model import (
    CandidateEvidence,
    GenerationContext,
    ReasonCode,
)


class CustomExactNameSource(CandidateSource):
    """Exact name lookup for custom entities.

    Canonical names return raw score 1.0; aliases return 0.95.
    Canonical wins on collision (id-sorted, budget-capped, no hierarchy ordering
    since custom packs have no type specificity).
    """

    @property
    def name(self) -> str:
        return "custom_exact_name"

    @property
    def reason_code(self) -> ReasonCode:
        return ReasonCode.EXACT_NAME_MATCH

    def supports(self, domain_pack_id: str) -> bool:
        return domain_pack_id == "custom"

    def generate(self, ctx: GenerationContext) -> list[CandidateEvidence]:
        text_norm = ctx.text_norm
        _tier = REASON_TO_MATCH_TIER.get(self.reason_code)

        # Merge canonical + alias by entity_id; canonical wins on collision.
        merged: dict[str, tuple[float, str]] = {}

        for eid in ctx.store.lookup_name_exact(text_norm, name_kinds={"canonical"}):
            merged[eid] = (1.0, "name.canonical")

        for eid in ctx.store.lookup_name_exact(
            text_norm, name_kinds={"alias", "endonym", "exonym"}
        ):
            if eid not in merged:  # canonical wins collision
                merged[eid] = (0.95, "name.alias")

        if not merged:
            emit_candidates_generated(
                ctx.trace, self.name, 0, entity_ids=[], query=text_norm
            )
            return []

        # Sort by (name_kind_priority, entity_id) for a deterministic budget cap.
        # No type-specificity ordering — custom packs have no entity hierarchy.
        def _sort_key(eid: str) -> tuple[int, str]:
            _score, field = merged[eid]
            name_kind_rank = 0 if field == "name.canonical" else 1
            return (name_kind_rank, eid)

        ordered = sorted(merged, key=_sort_key)

        evidence: list[CandidateEvidence] = []
        for i, eid in enumerate(ordered[: ctx.budget]):
            raw_score, matched_field = merged[eid]
            evidence.append(
                CandidateEvidence(
                    entity_id=eid,
                    source_name=self.name,
                    raw_score=raw_score,
                    rank=i + 1,
                    matched_field=matched_field,
                    matched_value=text_norm,
                    match_tier=_tier,
                )
            )

        emit_candidates_generated(
            ctx.trace,
            self.name,
            len(evidence),
            entity_ids=[e.entity_id for e in evidence],
            query=text_norm,
        )

        return evidence
