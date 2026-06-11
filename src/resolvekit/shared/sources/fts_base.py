"""Shared full-text search source implementation.

Uses FTS5 BM25 for ranked candidate retrieval.
"""

import time
from dataclasses import dataclass

from resolvekit.core.engine import CandidateSource
from resolvekit.core.engine.tier_utils import REASON_TO_MATCH_TIER
from resolvekit.core.explain import emit_candidates_generated
from resolvekit.core.model import (
    CandidateEvidence,
    GenerationContext,
    ReasonCode,
)


@dataclass(frozen=True)
class BM25ScoreTiers:
    """Configuration for BM25 score normalization based on rank.

    Higher ranks (closer to 1) get higher scores.
    """

    rank_1: float = 0.85
    rank_2_3: float = 0.75
    rank_4_10: float = 0.65
    rank_11_20: float = 0.55
    default: float = 0.45

    def score_for_rank(self, rank: int) -> float:
        """Get normalized score for a given rank position."""
        if rank == 1:
            return self.rank_1
        elif rank <= 3:
            return self.rank_2_3
        elif rank <= 10:
            return self.rank_4_10
        elif rank <= 20:
            return self.rank_11_20
        else:
            return self.default


class FTSSource(CandidateSource):
    """Full-text search source using FTS5 BM25.

    Configurable parameters:
    - name: Source name for tracing
    - domain: Domain pack ID this source supports
    - min_query_length: Minimum query length to search (skip codes)
    - score_tiers: BM25 score normalization configuration
    """

    def __init__(
        self,
        name: str,
        domain: str,
        min_query_length: int = 2,
        score_tiers: BM25ScoreTiers | None = None,
    ):
        """Create an FTS source.

        Args:
            name: Unique name for this source (e.g., "org_fts", "geo_fts")
            domain: Domain pack ID this source supports (e.g., "org", "geo")
            min_query_length: Minimum query length to process (default: 2)
            score_tiers: Score tier configuration (default: standard tiers)
        """
        self._name = name
        self._domain = domain
        self._min_query_length = min_query_length
        self._score_tiers = score_tiers or BM25ScoreTiers()

    @property
    def name(self) -> str:
        return self._name

    @property
    def reason_code(self) -> ReasonCode:
        return ReasonCode.FTS_MATCH

    def supports(self, domain_pack_id: str) -> bool:
        return domain_pack_id == self._domain

    def generate(self, ctx: GenerationContext) -> list[CandidateEvidence]:
        """Generate FTS candidates for the query.

        Deadline checks are cooperative — they occur before the store call, not
        within it. A blocking C-level FTS lookup cannot be preempted mid-call.
        """
        deadline = ctx.deadline
        if deadline is not None and time.monotonic() >= deadline:
            return []

        text_norm = ctx.text_norm

        # Skip very short queries (likely codes handled elsewhere)
        if len(text_norm) < self._min_query_length:
            return []

        results = ctx.store.search_fulltext(text_norm, limit=ctx.budget)

        _tier = REASON_TO_MATCH_TIER.get(self.reason_code)
        evidence: list[CandidateEvidence] = []
        for entity_id, bm25_score, rank in results:
            normalized_score = self._score_tiers.score_for_rank(rank)

            evidence.append(
                CandidateEvidence(
                    entity_id=entity_id,
                    source_name=self.name,
                    raw_score=normalized_score,
                    rank=rank,
                    matched_field="fts",
                    matched_value=text_norm,
                    signals={"bm25_raw": bm25_score},
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
