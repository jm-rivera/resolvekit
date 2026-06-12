"""Store-backed brute-force fuzzy retrieval source.

Retrieves candidates by running RapidFuzz ``partial_ratio`` over the store's
materialized name list, reusing the same ``fuzzy_candidates`` / ``iter_suggest_names``
mechanism the ``suggest()`` path already uses.  Unlike the SymSpell-backed
``FuzzyRetrievalSource``, this source needs no prebuilt dictionary — it operates
directly over whatever names are in the store, making it suitable for
programmatically-built packs (``Resolver.from_records``, ``domain="custom"``).

The engine's fuzzy-skip guard (``should_skip_source``) bypasses this source
when a confident exact-name match is already present, so the always-on
registration is free on clean canonical-name queries.

Short-input guard
-----------------
The self-contained guard helper at the bottom of this module rejects degenerate
inputs before the name list is built.  It is intentionally domain-agnostic:
no geo entity-type hint logic, no ISO-code unlocking.  Add domain-specific
unlocking in a subclass override if needed.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from resolvekit.core.engine import CandidateSource
from resolvekit.core.engine.suggest_rank import FUZZY_AUTO_MAX_NAMES, fuzzy_candidates
from resolvekit.core.explain import emit_candidates_generated
from resolvekit.core.model import (
    CandidateEvidence,
    GenerationContext,
    MatchTier,
    ReasonCode,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Short-input guard (domain-agnostic)
# ---------------------------------------------------------------------------

# Common spreadsheet / dataframe missing-value markers.  Compared casefolded.
_DEGENERATE_TOKENS: frozenset[str] = frozenset(
    {
        "na",
        "n/a",
        "n.a.",
        "n.a",
        "n/k",
        "null",
        "none",
        "nan",
        "nil",
        "tbd",
        "tba",
        "unknown",
        "<null>",
        "#n/a",
        "?",
        "-",
        "--",
        "---",
        ".",
    }
)


def _is_degenerate_token(text: str) -> bool:
    """Return True for known missing-value markers (``NA``, ``#N/A``, ``--`` …).

    The check is casefolded; surrounding ASCII whitespace is stripped first.
    """
    return text.strip().casefold() in _DEGENERATE_TOKENS


def _is_punctuation_noise(text: str) -> bool:
    """Return True for short tokens dominated by punctuation or symbols.

    Strips common spreadsheet punctuation and checks whether the residual
    is empty or a very short alpha fragment (≤ 3 chars).  Does not need a
    dotted-initialism exemption because those pass the ``min_query_length``
    gate upstream (``U.S.A.`` is 5 chars with dots).
    """
    if not text:
        return True
    stripped = text
    for ch in "#/\\-_.,;:!?*|()[]{}'\"`":
        stripped = stripped.replace(ch, "")
    stripped = stripped.strip()
    if not stripped:
        return True
    had_punctuation = stripped != text.strip()
    if not had_punctuation:
        return False
    return len(stripped) <= 3 and stripped.isalpha()


def _is_single_letter(text: str) -> bool:
    """Return True for a bare single ASCII letter (any case)."""
    raw = text.strip()
    return len(raw) == 1 and raw.isascii() and raw.isalpha()


def _short_input_blocked(query_norm: str) -> bool:
    """Domain-agnostic short-input gate.

    Returns True when the source should suppress itself for this query.

    Checks (earlier wins):
      1. Degenerate missing-value markers — always blocked.
      2. Single ASCII letter (any case) — too ambiguous for brute-force fuzzy.
      3. Punctuation-noise tokens.

    ``min_query_length`` is checked separately in ``generate()`` before this
    helper is called so callers that relax the default minimum still get the
    degenerate-token and single-letter blocks.
    """
    if _is_degenerate_token(query_norm):
        return True
    if _is_single_letter(query_norm):
        return True
    return _is_punctuation_noise(query_norm)


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------


class FuzzyRetrievalBruteSource(CandidateSource):
    """Store-backed generating fuzzy source using brute-force RapidFuzz.

    Materializes the store's name list once, lazily on the first
    ``generate()`` call (``warm()`` cannot pre-build it because
    ``CandidateSource.warm()`` receives no store reference), then runs
    ``fuzzy_candidates`` over it on every query that is not short-circuited by
    the short-input guard or the engine's skip logic.

    ``tier = MatchTier.FUZZY`` is declared as a **class attribute** so that
    ``should_skip_source`` (``core/engine/_stages.py``) can read it before
    ``generate()`` is called — this is the mechanism that makes the always-on
    registration free on exact-name queries.

    The name list is keyed by the fixed ``entity_type_prefixes`` passed at
    construction time.  For a custom pack (``entity_type_prefixes=None``) there
    is exactly one cache entry per instance.  The store is treated as immutable
    for the resolver's lifetime, so no invalidation is performed.

    Both ``_names_cache`` and ``_choices_cache`` (the extracted ``value_norm``
    strings) are memoized to avoid rebuilding the ``choices`` list on every
    call to ``fuzzy_candidates``.

    Configurable parameters
    -----------------------
    name : str
        Unique name for this source (e.g. ``"custom_fuzzy_retrieval"``).
    domain : str
        Domain pack ID this source supports (e.g. ``"custom"``).
    min_query_length : int
        Minimum normalized query length to process.  Shorter queries return
        ``[]`` immediately.  Default 3.
    max_names : int
        Cap on the name-list size.  When ``len(names) > max_names`` the
        brute-force pass is skipped and ``[]`` is returned.  Default
        ``FUZZY_AUTO_MAX_NAMES`` (25 000).
    top_k : int
        Maximum candidates requested from ``fuzzy_candidates``.  Default 25.
    entity_type_prefixes : frozenset[str] | None
        When given, only names whose entity type starts with one of these
        prefixes are included in the name list.  ``None`` = all types.
    """

    # Class-level declaration — read by should_skip_source BEFORE generate() runs.
    tier: MatchTier = MatchTier.FUZZY  # type: ignore[assignment]

    def __init__(
        self,
        *,
        name: str,
        domain: str,
        min_query_length: int = 3,
        max_names: int = FUZZY_AUTO_MAX_NAMES,
        top_k: int = 25,
        entity_type_prefixes: frozenset[str] | None = None,
    ) -> None:
        self._name = name
        self._domain = domain
        self._min_query_length = min_query_length
        self._max_names = max_names
        self._top_k = top_k
        self._entity_type_prefixes = entity_type_prefixes

        # Memoized name list and choices, keyed by entity_type_prefixes.
        # Built lazily on first generate() / warm(); never invalidated.
        self._names_cache: list[tuple[str, str, str, bool, str]] | None = None
        self._choices_cache: list[str] | None = None

        # Guards the one-time build (mirrors SymSpellSource pattern).
        self._build_lock = threading.Lock()
        self._built = False

    # ------------------------------------------------------------------
    # CandidateSource properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def reason_code(self) -> ReasonCode:
        return ReasonCode.FUZZY_MATCH

    def supports(self, domain_pack_id: str) -> bool:
        return domain_pack_id == self._domain

    @property
    def requires_existing_candidates(self) -> bool:
        return False

    # ------------------------------------------------------------------
    # Cache build (thread-safe)
    # ------------------------------------------------------------------

    def _ensure_built(self, store: Any) -> None:
        """Build name and choices caches if not already built.

        Double-checked locking: cheap lock-free fast-path once built.
        Any exception during build is swallowed so ``generate()`` can
        return ``[]`` gracefully (never raise contract).
        """
        if self._built:
            return
        with self._build_lock:
            if self._built:
                return
            try:
                names = list(
                    store.iter_suggest_names(
                        entity_type_prefixes=self._entity_type_prefixes
                    )
                )
                choices = [row[0] for row in names]
                self._names_cache = names
                self._choices_cache = choices
            except Exception as exc:
                logger.debug(
                    "FuzzyRetrievalBruteSource '%s': iter_suggest_names failed: %s",
                    self._name,
                    exc,
                )
                # Leave _built=False so callers see None caches and return [].
                return
            self._built = True

    def warm(self) -> None:
        """No-op: cache is built on first ``generate()`` call.

        ``CandidateSource.warm()`` receives no store reference, so the name
        list cannot be pre-built here.  The build is deferred to the first
        ``generate()`` call, which receives the store via ``ctx.store``.

        Subclasses that have access to the store at warm time can override
        ``warm()`` to call ``_ensure_built(store)`` directly.
        """
        # ``CandidateSource.warm()`` has no store parameter — actual build
        # deferred to first generate() call.  The warm() contract still holds:
        # if the runner calls warm() and then generate(), the first generate()
        # call will build and subsequent calls skip the lock.

    # ------------------------------------------------------------------
    # generate
    # ------------------------------------------------------------------

    def generate(self, ctx: GenerationContext) -> list[CandidateEvidence]:
        """Generate FUZZY-tier evidence via brute-force RapidFuzz.

        Returns ``[]`` (never raises) on any internal failure.
        """
        try:
            return self._generate_inner(ctx)
        except Exception as exc:
            logger.debug(
                "FuzzyRetrievalBruteSource '%s': unexpected error for query '%s': %s",
                self._name,
                ctx.text_norm,
                exc,
            )
            emit_candidates_generated(
                ctx.trace,
                self._name,
                0,
                entity_ids=[],
                query=ctx.text_norm,
                reason="error",
            )
            return []

    def _generate_inner(self, ctx: GenerationContext) -> list[CandidateEvidence]:  # noqa: PLR0911
        # 1. Cooperative deadline check.
        if ctx.deadline is not None and time.monotonic() >= ctx.deadline:
            return []

        query_norm = ctx.text_norm

        # 2. Min-length gate.
        if len(query_norm) < self._min_query_length:
            return []

        # 3. Degenerate-token / punctuation-noise / single-letter check.
        if _short_input_blocked(query_norm):
            return []

        # 4. Build / load caches.
        self._ensure_built(ctx.store)

        names = self._names_cache
        choices = self._choices_cache
        if names is None or choices is None:
            # Build failed (iter_suggest_names raised or is not implemented).
            emit_candidates_generated(
                ctx.trace,
                self._name,
                0,
                entity_ids=[],
                query=query_norm,
                reason="no_names",
            )
            return []

        # 5. Cap check — skip brute-force on very large stores.
        if len(names) > self._max_names:
            emit_candidates_generated(
                ctx.trace,
                self._name,
                0,
                entity_ids=[],
                query=query_norm,
                reason="cap_exceeded",
            )
            return []

        # 6. Brute-force fuzzy candidates.
        raw = fuzzy_candidates(
            query_norm,
            names,
            top_k=self._top_k,
            choices=choices,
        )

        if not raw:
            emit_candidates_generated(
                ctx.trace,
                self._name,
                0,
                entity_ids=[],
                query=query_norm,
            )
            return []

        # 7. Dedupe: keep best hit per entity_id (lowest typo_count wins, then
        #    highest match_score, mirroring runner.suggest_prefix dedup logic).
        best: dict[str, Any] = {}
        for cand in raw:
            eid = cand.entity_id
            if eid not in best:
                best[eid] = cand
            else:
                prev = best[eid]
                if (cand.typo_count, -(cand.match_score or 0.0)) < (
                    prev.typo_count,
                    -(prev.match_score or 0.0),
                ):
                    best[eid] = cand

        # 8. Map to CandidateEvidence, stamping match_tier=FUZZY explicitly.
        evidence: list[CandidateEvidence] = []
        for rank, cand in enumerate(best.values(), start=1):
            evidence.append(
                CandidateEvidence(
                    entity_id=cand.entity_id,
                    source_name=self._name,
                    raw_score=(cand.match_score or 0.0) / 100.0,
                    rank=rank,
                    matched_field="fuzzy_retrieval",
                    matched_value=cand.matched_value,
                    match_tier=MatchTier.FUZZY,
                )
            )

        emit_candidates_generated(
            ctx.trace,
            self._name,
            len(evidence),
            entity_ids=[e.entity_id for e in evidence],
            query=query_norm,
        )

        return evidence
