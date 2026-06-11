"""Shared helpers for exact code sources."""

from resolvekit.core.model import CandidateEvidence, MatchTier


def evidence_from_code_hits(
    hits: list[tuple[str, str]],
    source_name: str,
    matched_value: str,
    budget: int,
    match_tier: MatchTier | None = None,
) -> list[CandidateEvidence]:
    """Build CandidateEvidence from lookup_code_any results.

    Args:
        hits: (entity_id, system) pairs from store.lookup_code_any
        source_name: Name of the calling source
        matched_value: Display value for the match (typically raw user input)
        budget: Max candidates to return
        match_tier: Tier to stamp on each evidence record (stamped from the
            source's reason_code at the call site).
    """
    return [
        CandidateEvidence(
            entity_id=eid,
            source_name=source_name,
            raw_score=1.0,
            rank=i + 1,
            matched_field=f"code.{system}",
            matched_value=matched_value,
            match_tier=match_tier,
        )
        for i, (eid, system) in enumerate(hits[:budget])
    ]
