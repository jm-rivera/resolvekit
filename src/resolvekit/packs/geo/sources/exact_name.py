"""Exact name source for geo entities."""

from resolvekit.core.engine import CandidateSource
from resolvekit.core.engine.tier_utils import REASON_TO_MATCH_TIER
from resolvekit.core.explain import emit_candidates_generated
from resolvekit.core.model import (
    CandidateEvidence,
    GenerationContext,
    ReasonCode,
)
from resolvekit.packs.geo._specificity import geo_candidate_ordering_key
from resolvekit.packs.geo.sources._short_input import short_input_blocked


class GeoExactNameSource(CandidateSource):
    """Exact name lookup for geo entities.

    Searches canonical names and high-quality aliases.
    Returns high confidence (1.0) for exact canonical matches.
    """

    @property
    def name(self) -> str:
        return "geo_exact_name"

    @property
    def reason_code(self) -> ReasonCode:
        return ReasonCode.EXACT_NAME_MATCH

    def supports(self, domain_pack_id: str) -> bool:
        return domain_pack_id == "geo"

    def generate(self, ctx: GenerationContext) -> list[CandidateEvidence]:
        text_norm = ctx.text_norm
        raw_text = ctx.query.raw_text
        _tier = REASON_TO_MATCH_TIER.get(self.reason_code)

        # Evaluate the short-input gate exactly once — both lookups share
        # this single boolean. Gating both paths together prevents canonical
        # matches from hiding alias matches.
        gated = short_input_blocked(raw_text, text_norm, ctx.context)

        # 1. Merge canonical + alias by entity_id; canonical wins on collision.
        #    dict[entity_id -> (name_kind, raw_score, matched_field)]
        merged: dict[str, tuple[str, float, str]] = {}
        if not gated:
            for eid in ctx.store.lookup_name_exact(text_norm, name_kinds={"canonical"}):
                merged[eid] = ("canonical", 1.0, "name.canonical")
            for eid in ctx.store.lookup_name_exact(
                text_norm, name_kinds={"alias", "endonym", "exonym"}
            ):
                if eid not in merged:  # canonical wins collision
                    merged[eid] = ("alias", 0.95, "name.alias")

        if not merged:
            emit_candidates_generated(
                ctx.trace, self.name, 0, entity_ids=[], query=text_norm
            )
            return []

        # 2. Hydrate via the LRU-cached get_entity. Tiny id sets; warms the cache
        #    the downstream GeoFeatureExtractor reads from.
        records = {eid: ctx.store.get_entity(eid) for eid in merged}

        # 3. Sort the id set BEFORE the budget cap. Type-specificity first:
        #    geo.country (rank 0) precedes admin/city (rank 99) regardless of
        #    name_kind or how many same-name owners collide. This ensures
        #    high-specificity entities survive the budget cutoff.
        def sort_key(eid: str) -> tuple[int, int, float, str]:
            name_kind, _score, _field = merged[eid]
            rec = records.get(eid)
            spec = (
                geo_candidate_ordering_key(rec.entity_type) if rec is not None else None
            )
            type_rank = 99 if spec is None else spec
            name_kind_rank = 0 if name_kind == "canonical" else 1
            # Mirror extractor.py prominence coercion: only use the value when
            # it's a real number; malformed/None falls back to the neutral 0.5.
            prom_raw = rec.attributes.get("prominence") if rec is not None else None
            prom = float(prom_raw) if isinstance(prom_raw, int | float) else 0.5
            return (
                type_rank,
                name_kind_rank,
                -prom,
                eid,
            )  # eid = deterministic tiebreak

        ordered = sorted(merged, key=sort_key)

        # 4. Cap AFTER ranking, then build evidence with post-cap rank.
        evidence: list[CandidateEvidence] = []
        for i, eid in enumerate(ordered[: ctx.budget]):
            _name_kind, raw_score, matched_field = merged[eid]
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
