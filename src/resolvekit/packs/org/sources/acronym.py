"""Acronym source for org entities - first-class acronym handling."""

from resolvekit.core.engine import CandidateSource
from resolvekit.core.engine.tier_utils import REASON_TO_MATCH_TIER
from resolvekit.core.explain import emit_candidates_generated
from resolvekit.core.model import (
    CandidateEvidence,
    GenerationContext,
    ReasonCode,
)
from resolvekit.packs.org._acronym import is_acronym_like

# Acronym scoring constants
ACRONYM_UPPERCASE_SCORE = 1.0
ACRONYM_MIXEDCASE_SCORE = 0.95


class OrgAcronymSource(CandidateSource):
    """First-class acronym source for organizations.

    Treats acronyms as a dedicated index, not fuzzy fallback.
    Critical for org resolution where acronyms are common (EU, UN, IMF, NATO).
    """

    @property
    def name(self) -> str:
        return "org_acronym"

    @property
    def reason_code(self) -> ReasonCode:
        return ReasonCode.ACRONYM_MATCH

    def supports(self, domain_pack_id: str) -> bool:
        return domain_pack_id == "org"

    def generate(self, ctx: GenerationContext) -> list[CandidateEvidence]:
        text = ctx.query.normalized.original  # Use original for case info
        text_norm = ctx.text_norm
        evidence: list[CandidateEvidence] = []

        # Only search acronyms if query looks like an acronym
        if not self._is_acronym_like(text):
            return evidence

        _tier = REASON_TO_MATCH_TIER.get(self.reason_code)
        # Exact acronym match
        entity_ids = ctx.store.lookup_name_exact(text_norm, name_kinds={"acronym"})

        for i, eid in enumerate(entity_ids[: ctx.budget]):
            evidence.append(
                CandidateEvidence(
                    entity_id=eid,
                    source_name=self.name,
                    raw_score=ACRONYM_UPPERCASE_SCORE
                    if text.isupper()
                    else ACRONYM_MIXEDCASE_SCORE,
                    rank=i + 1,
                    matched_field="name.acronym",
                    matched_value=text_norm.upper(),
                    match_tier=_tier,
                )
            )

        emit_candidates_generated(
            ctx.trace,
            self.name,
            len(evidence),
            entity_ids=[e.entity_id for e in evidence],
            query=text_norm,
            is_acronym_like=True,
        )

        return evidence

    def _is_acronym_like(self, text: str) -> bool:
        return is_acronym_like(text)
