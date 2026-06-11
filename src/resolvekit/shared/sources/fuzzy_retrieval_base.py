"""Fuzzy retrieval source using per-word SymSpell correction.

Corrects individual words in the query using SymSpell, then looks up the
corrected phrase in the store. Unlike FuzzySource (which reranks existing
candidates), this source retrieves candidates independently.
"""

import logging
import time

from rapidfuzz import fuzz

from resolvekit.core.explain import emit_candidates_generated
from resolvekit.core.model import (
    CandidateEvidence,
    GenerationContext,
    MatchTier,
)
from resolvekit.shared.sources.symspell_base import (
    SymSpellSource,
    _load_symspell_verbosity,
)

logger = logging.getLogger(__name__)


class FuzzyRetrievalSource(SymSpellSource):
    """Fuzzy retrieval source using per-word SymSpell correction.

    Corrects individual words in the query using SymSpell, then looks up
    the corrected phrase in the store. Inherits dictionary loading from
    SymSpellSource but overrides generate() with word-level correction.
    """

    def __init__(
        self,
        name: str,
        domain: str,
        dictionary_path: str | None = None,
        max_edit_distance: int = 2,
        prefix_length: int = 7,
        min_query_length: int = 3,
        name_kinds: set[str] | None = None,
    ) -> None:
        super().__init__(
            name=name,
            domain=domain,
            dictionary_path=dictionary_path,
            max_edit_distance=max_edit_distance,
            prefix_length=prefix_length,
            min_query_length=min_query_length,
            matched_field="fuzzy_retrieval",
            name_kinds=name_kinds,
        )

    def generate(self, ctx: GenerationContext) -> list[CandidateEvidence]:
        """Generate candidates by correcting words and looking up the phrase."""
        deadline = ctx.deadline
        if deadline is not None and time.monotonic() >= deadline:
            return []

        # Trigger the lazy build on first use.
        self._ensure_built()

        if self._sym_spell is None:
            emit_candidates_generated(
                ctx.trace,
                self.name,
                0,
                entity_ids=[],
                query=ctx.text_norm,
                reason="no_symspell",
            )
            return []

        if len(ctx.text_norm) < self._min_query_length:
            return []

        try:
            evidence = self._generate_with_word_correction(ctx, deadline=deadline)
        except Exception as e:
            logger.warning(
                "FuzzyRetrievalSource lookup failed for query '%s': %s",
                ctx.text_norm,
                e,
                exc_info=True,
            )
            return []

        emit_candidates_generated(
            ctx.trace,
            self.name,
            len(evidence),
            entity_ids=[e.entity_id for e in evidence],
            query=ctx.text_norm,
        )

        return evidence

    def _generate_with_word_correction(
        self, ctx: GenerationContext, deadline: float | None = None
    ) -> list[CandidateEvidence]:
        """Correct each word individually and look up the resulting phrase.

        Deadline checks are cooperative — they occur between word iterations,
        not within a single SymSpell lookup call. A blocking C-level lookup
        cannot be preempted mid-call.
        """
        verbosity = _load_symspell_verbosity()
        if verbosity is None or self._sym_spell is None:
            return []

        text_norm = ctx.text_norm
        words = text_norm.split()

        # Correct each word individually
        corrected_words: list[str] = []
        for word in words:
            if deadline is not None and time.monotonic() >= deadline:
                break
            suggestions = self._sym_spell.lookup(
                word,
                verbosity.CLOSEST,
                max_edit_distance=self._max_edit,
            )
            if suggestions:
                corrected_words.append(suggestions[0].term)
            else:
                corrected_words.append(word)

        corrected_phrase = " ".join(corrected_words)

        # No correction was made — other sources handle exact queries
        if corrected_phrase == text_norm:
            return []

        evidence: list[CandidateEvidence] = []
        seen_ids: set[str] = set()

        # Try exact name lookup first
        entity_ids = ctx.store.lookup_name_exact(
            corrected_phrase, name_kinds=self._name_kinds
        )
        # Evidence emitted by fuzzy retrieval is FUZZY-tier (derived from word
        # correction, not an exact name or code lookup).
        _tier = MatchTier.FUZZY
        for entity_id in entity_ids:
            if entity_id not in seen_ids and len(evidence) < ctx.budget:
                seen_ids.add(entity_id)
                score = fuzz.ratio(text_norm, corrected_phrase) / 100.0
                evidence.append(
                    CandidateEvidence(
                        entity_id=entity_id,
                        source_name=self.name,
                        raw_score=score,
                        rank=len(evidence) + 1,
                        matched_field="fuzzy_retrieval",
                        matched_value=corrected_phrase,
                        match_tier=_tier,
                    )
                )

        # Fall back to full-text search if no exact match
        if not entity_ids:
            fts_results = ctx.store.search_fulltext(corrected_phrase, limit=ctx.budget)
            for entity_id, *_ in fts_results:
                if entity_id not in seen_ids and len(evidence) < ctx.budget:
                    seen_ids.add(entity_id)
                    score = fuzz.ratio(text_norm, corrected_phrase) / 100.0
                    evidence.append(
                        CandidateEvidence(
                            entity_id=entity_id,
                            source_name=self.name,
                            raw_score=score,
                            rank=len(evidence) + 1,
                            matched_field="fuzzy_retrieval",
                            matched_value=corrected_phrase,
                            match_tier=_tier,
                        )
                    )

        return evidence
