"""Tier-rank helpers and candidate-summary builder for the resolution pipeline.

These utilities are consumed by sources (to stamp match_tier on evidence),
by the decision policy (to build candidate summaries), and by the pipeline
runner (to check stop conditions).  Factoring them here keeps sources from
importing the full runner module.
"""

from resolvekit.core.model import (
    Candidate,
    CandidateEvidenceSummary,
    CandidateSummary,
    MatchTier,
    ReasonCode,
)

MATCH_TIER_PRIORITY: dict[MatchTier, int] = {
    MatchTier.EXACT_CODE: 5,
    MatchTier.EXACT_NAME: 4,
    MatchTier.ACRONYM: 3,
    MatchTier.FTS: 2,
    MatchTier.FUZZY: 1,
    MatchTier.FALLBACK: 0,
}

REASON_TO_MATCH_TIER: dict[ReasonCode, MatchTier] = {
    ReasonCode.EXACT_CODE_MATCH: MatchTier.EXACT_CODE,
    ReasonCode.EXACT_NAME_MATCH: MatchTier.EXACT_NAME,
    ReasonCode.ACRONYM_MATCH: MatchTier.ACRONYM,
    ReasonCode.ACRONYM_MATCH_AMBIGUOUS: MatchTier.ACRONYM,
    ReasonCode.FTS_MATCH: MatchTier.FTS,
    ReasonCode.FUZZY_MATCH: MatchTier.FUZZY,
}


def match_tier_rank(tier: MatchTier | None) -> int:
    """Return an ordinal rank for match tiers."""
    if tier is None:
        return -1
    return MATCH_TIER_PRIORITY[tier]


def reason_to_match_tier(reason: ReasonCode | None) -> MatchTier | None:
    """Map a reason code to a match tier when possible."""
    if reason is None:
        return None
    return REASON_TO_MATCH_TIER.get(reason)


_SOURCE_TIER_TOKENS: tuple[tuple[str, MatchTier], ...] = (
    ("exact_code", MatchTier.EXACT_CODE),
    ("exact_name", MatchTier.EXACT_NAME),
    ("acronym", MatchTier.ACRONYM),
    ("fuzzy", MatchTier.FUZZY),
    ("fts", MatchTier.FTS),
)


def _source_name_tier_fallback(source_name: str) -> MatchTier | None:
    """Infer tier from source_name substring — fallback for evidence without match_tier.

    Used only when ``CandidateEvidence.match_tier`` is None (e.g. legacy mocks or
    sources not yet migrated to stamp match_tier at emission).  New sources should
    stamp ``match_tier`` directly; this fallback is not part of the public API.
    """
    for token, tier in _SOURCE_TIER_TOKENS:
        if token in source_name:
            return tier
    return None


def derive_candidate_match_tier(candidate: Candidate) -> MatchTier:
    """Infer a candidate's strongest tier from its evidence.

    Prefers ``CandidateEvidence.match_tier`` (stamped at emission by the source's
    reason_code via ``REASON_TO_MATCH_TIER``).  Falls back to source-name substring
    matching for evidence that predates the stamp (backward compatibility).
    """
    best_tier = MatchTier.FALLBACK
    for evidence in candidate.sources:
        tier = evidence.match_tier or _source_name_tier_fallback(evidence.source_name)
        if tier is not None and match_tier_rank(tier) > match_tier_rank(best_tier):
            best_tier = tier
    return best_tier


def build_candidate_summary(
    candidate: Candidate,
    max_evidence: int = 3,
    max_features: int = 5,
) -> CandidateSummary:
    """Build a CandidateSummary with evidence and features from a full Candidate."""
    # Top evidence: sorted by score, capped
    sorted_evidence = sorted(
        candidate.sources, key=lambda e: e.raw_score or 0.0, reverse=True
    )
    top_evidence = [
        CandidateEvidenceSummary(
            source_name=ev.source_name,
            matched_field=getattr(ev, "matched_field", None) or "",
            matched_value=ev.matched_value,
        )
        for ev in sorted_evidence[:max_evidence]
    ]

    # Key features: extract from feature vector if available
    key_features: dict[str, float | bool | None] = {}
    if candidate.features is not None and hasattr(candidate.features, "to_dict"):
        feat_dict = candidate.features.to_dict()
        for k, v in feat_dict.items():
            if k == "schema_version" or v is None:
                continue
            if k.startswith("query_"):
                continue  # Skip query-level features (redundant)
            if isinstance(v, float | int | bool):
                key_features[k] = v
            if len(key_features) >= max_features:
                break

    return CandidateSummary(
        entity_id=candidate.entity_id,
        confidence=candidate.scores.calibrated_score,
        match_tier=derive_candidate_match_tier(candidate),
        top_evidence=top_evidence,
        key_features=key_features,
    )


# Decision thresholds - extracted as constants for configurability
DEFAULT_FALLBACK_SCORE = 0.5
DEFAULT_BUDGET = 50
DEFAULT_TOP_K_RESULTS = 5


__all__ = [
    "DEFAULT_BUDGET",
    "DEFAULT_FALLBACK_SCORE",
    "DEFAULT_TOP_K_RESULTS",
    "MATCH_TIER_PRIORITY",
    "REASON_TO_MATCH_TIER",
    "_SOURCE_TIER_TOKENS",
    "_source_name_tier_fallback",
    "build_candidate_summary",
    "derive_candidate_match_tier",
    "match_tier_rank",
    "reason_to_match_tier",
]
