"""Cascade ranker and fuzzy pool helper for the suggest() autocomplete path.

All ranking state lives here — both ``PipelineRunner.suggest_prefix`` (single-pack)
and ``MultiPackRunner.suggest_prefix`` (cross-pack) sort the same ``SuggestCandidate``
struct with the same ``sort_key``, so there is one comparator with no per-pack
duplication.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from resolvekit.core.model.result import MatchClass

# ---------------------------------------------------------------------------
# Policy constants
# ---------------------------------------------------------------------------

# Fuzzy brute-force is only run when the materialized name count is at or
# below this ceiling.  Bundled tiers (countries + admin1 + regions +
# continental_unions, excluding denylist types) total ~20.5 k names;
# cities/admin2+ would push that past the latency budget.
FUZZY_AUTO_MAX_NAMES: Final[int] = 25_000

# Entity-type prefixes for which fuzzy ranking is unreliable even if the
# name count stays under FUZZY_AUTO_MAX_NAMES (absent/broken prominence makes
# fuzzy hits rank poorly in practice).
FUZZY_DENYLIST_PREFIXES: Final[frozenset[str]] = frozenset(
    {
        "geo.city",
        "geo.admin2",
        "geo.admin3",
        "geo.admin4",
        "geo.admin5",
    }
)

# Entity-type prefixes for which live prominence data exists.  The
# ``ranking_quality`` field reports ``"ranked"`` for these tiers regardless
# of whether a specific candidate carries a prominence value — the hint is
# tier-based, not per-candidate.
PROMINENCE_LIVE_TYPE_PREFIXES: Final[frozenset[str]] = frozenset(
    {
        "geo.country",
        # Region tiers carry containment-derived prominence (sum of member-
        # country prominence, normalized per tier). Continents and groups
        # have no presence data and are not enriched.
        "geo.subregion",
        "geo.region",
        "geo.continental_union",
        # City and admin2 tiers gain live Wikidata sitelink / DC population
        # prominence once the full geo build includes those tiers.  The prefix
        # is added here so ``ranking_quality`` reports ``"ranked"`` as soon as
        # the data ships, without a follow-on code change.
        "geo.city",
        "geo.admin2",
    }
)

# Numeric rank for each MatchClass (lower = better).
MATCH_CLASS_RANK: Final[dict[MatchClass, int]] = {
    MatchClass.EXACT_PREFIX: 0,
    MatchClass.TOKEN_PREFIX: 1,
    MatchClass.INFIX: 2,
    MatchClass.FUZZY: 3,
}

# Name-kind rank: preferred/canonical > acronym/abbr > alias > other.
# Lower is better.
_NAME_KIND_RANK: Final[dict[str, int]] = {
    "canonical": 0,
    "preferred": 0,
    "acronym": 1,
    "abbr": 1,
    "alias": 2,
}
_NAME_KIND_RANK_DEFAULT: Final[int] = 3


# ---------------------------------------------------------------------------
# Working struct
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SuggestCandidate:
    """Intermediate working struct passed between suggest pipeline stages.

    This is NOT a public result — it is promoted to ``SuggestionResult`` by
    ``SuggestFlow``.  All fields must be set before sorting.

    Attributes:
        entity_id: Stable entity identifier.
        match_class: Best match class for this entity.
        exact_match: True when the query equals the matched name in full
            (``matched_value_norm == query_norm``).  Ranks ahead of
            prominence so that an entity whose complete short name the user
            typed (e.g. "EU", "NATO") surfaces before longer-named entities
            that merely *start with* those letters.
        typo_count: Damerau-Levenshtein distance between the query and the
            matched name (0 for non-fuzzy hits).
        prominence: Float in [0, 1]; absent → 0.0.
        name_kind_rank: 0 = preferred/canonical, 1 = acronym/abbr, 2 = alias,
            3 = other.
        matched_value_norm: Normalized form of the matched name string.
        match_score: Raw ``partial_ratio`` score (0-100) from RapidFuzz when
            ``match_class == FUZZY``; ``None`` otherwise.
        pack_id: Pack that produced this candidate.
        entity_type: Entity type string (e.g. ``"geo.country"``).
        canonical_name: Best display name for this entity.
        matched_value: Original-cased matched name string.
    """

    entity_id: str
    match_class: MatchClass
    exact_match: bool
    typo_count: int
    prominence: float
    name_kind_rank: int
    matched_value_norm: str
    match_score: float | None
    pack_id: str | None
    entity_type: str | None
    canonical_name: str | None
    matched_value: str


# ---------------------------------------------------------------------------
# Cascade sort key
# ---------------------------------------------------------------------------


def sort_key(
    c: SuggestCandidate,
) -> tuple[int, int, int, float, int, int, str]:
    """Return an ascending 7-tuple sort key for *c*.

    Lower is better.  The tuple is:
    ``(match_class_rank, exact_match_rank, typo_count, -prominence,
    name_kind_rank, len(matched_value_norm), entity_id)``

    ``exact_match_rank`` is 0 when the user's query equals the matched name in
    full (``exact_match=True``) and 1 otherwise.  This lifts entities whose
    complete short name was typed (e.g. "EU", "NATO") above longer-named
    entities that merely *start with* those letters, even when those entities
    carry higher prominence scores.

    The final ``entity_id`` field gives a total order so that equal inputs
    always produce the same sequence.
    """
    return (
        MATCH_CLASS_RANK[c.match_class],
        0 if c.exact_match else 1,
        c.typo_count,
        -c.prominence,
        c.name_kind_rank,
        len(c.matched_value_norm),
        c.entity_id,
    )


# ---------------------------------------------------------------------------
# ranking_quality derivation
# ---------------------------------------------------------------------------


def ranking_quality(entity_type: str | None) -> Literal["ranked", "unranked"]:
    """Return ``"ranked"`` when the entity_type belongs to a tier with live prominence.

    The check is tier-based (prefix match against
    ``PROMINENCE_LIVE_TYPE_PREFIXES``), not per-candidate — a country with no
    stored prominence value still returns ``"ranked"`` because the tier has
    coverage.

    Args:
        entity_type: Entity type string (e.g. ``"geo.country"``), or ``None``.

    Returns:
        ``"ranked"`` or ``"unranked"``.
    """
    if entity_type is None:
        return "unranked"
    for prefix in PROMINENCE_LIVE_TYPE_PREFIXES:
        if entity_type == prefix or entity_type.startswith(f"{prefix}."):
            return "ranked"
    return "unranked"


# ---------------------------------------------------------------------------
# name_kind_rank helper
# ---------------------------------------------------------------------------


def name_kind_rank(name_kind: str, *, is_preferred: bool) -> int:
    """Map a name record's kind and preferred flag to a numeric rank.

    Args:
        name_kind: Name kind string (e.g. ``"canonical"``, ``"alias"``).
        is_preferred: Whether the name record carries ``is_preferred=True``.

    Returns:
        0 for preferred/canonical, 1 for acronym/abbr, 2 for alias,
        3 for everything else.
    """
    if is_preferred:
        return 0
    return _NAME_KIND_RANK.get(name_kind, _NAME_KIND_RANK_DEFAULT)


# ---------------------------------------------------------------------------
# Fuzzy candidate pool
# ---------------------------------------------------------------------------


def fuzzy_candidates(
    query_norm: str,
    names: list[tuple[str, str, str, bool, str]],
    *,
    top_k: int,
) -> list[SuggestCandidate]:
    """Run brute-force RapidFuzz over a pre-materialized name list.

    Uses ``fuzz.partial_ratio`` with ``score_cutoff=70`` for the candidate
    pool (gives the C++ early-exit), then ``DamerauLevenshtein.distance`` for
    the ``typo_count`` cascade key on the surviving pool.

    ``fuzzy_pool = min(max(top_k * 5, 50), 500)`` controls how many raw fuzzy
    hits are collected before deduplication back in the caller.

    Args:
        query_norm: Normalized query string.
        names: List of ``(value_norm, entity_id, name_kind, is_preferred,
            value)`` 5-tuples — typically the memoized output of
            ``store.iter_suggest_names()``.
        top_k: Number of results the caller ultimately wants.

    Returns:
        List of ``SuggestCandidate`` objects (one per distinct matched name row,
        not deduped by entity_id — the caller handles that).  ``pack_id``,
        ``entity_type``, ``canonical_name``, and ``prominence`` are left at
        sentinel values (``None`` / 0.0) and filled in by the caller once the
        entity is fetched.
    """
    if not query_norm or not names:
        return []

    from rapidfuzz import fuzz, process
    from rapidfuzz.distance import DamerauLevenshtein

    fuzzy_pool = min(max(top_k * 5, 50), 500)

    # Extract just the value_norm strings for RapidFuzz.
    choices = [row[0] for row in names]

    raw_hits = process.extract(
        query_norm,
        choices,
        scorer=fuzz.partial_ratio,
        score_cutoff=70,
        limit=fuzzy_pool,
    )
    # raw_hits: list of (matched_string, score, index)

    # Guard against spurious short-substring hits (e.g. 2-3 char ISO-code rows
    # that score 100 because they are a substring of the query string).
    # Require the candidate's value_norm to be at least half the query length,
    # so short codes don't flood the fuzzy pool budget.
    min_candidate_len = max(1, len(query_norm) // 2)

    candidates: list[SuggestCandidate] = []
    for matched_norm, score, idx in raw_hits:
        if len(matched_norm) < min_candidate_len:
            continue
        value_norm, entity_id, nk, is_pref, value = names[idx]
        typo = DamerauLevenshtein.distance(query_norm, matched_norm)
        candidates.append(
            SuggestCandidate(
                entity_id=entity_id,
                match_class=MatchClass.FUZZY,
                exact_match=value_norm == query_norm,
                typo_count=typo,
                prominence=0.0,
                name_kind_rank=name_kind_rank(nk, is_preferred=is_pref),
                matched_value_norm=value_norm,
                match_score=float(score),
                pack_id=None,
                entity_type=None,
                canonical_name=None,
                matched_value=value,
            )
        )

    return candidates
