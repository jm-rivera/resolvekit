"""Result enrichment for pipeline outputs.

`ResultEnricher` is constructed once per `PipelineRunner` (not per call) and
holds all post-decision enrichment logic.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from resolvekit.core.engine.tier_utils import (
    DEFAULT_TOP_K_RESULTS,
    build_candidate_summary,
    derive_candidate_match_tier,
    match_tier_rank,
    reason_to_match_tier,
)
from resolvekit.core.model import (
    Candidate,
    CandidateSummary,
    ConstraintRole,
    EntityRecord,
    MatchTier,
    Query,
    ReasonCode,
    RefinementHint,
    ResolutionContext,
    ResolutionResult,
    ResolutionStatus,
)
from resolvekit.core.store import EntityStore

if TYPE_CHECKING:
    from resolvekit.core.engine.interfaces import CandidateSource

logger = logging.getLogger(__name__)

PARENT_RELATION_TYPES = frozenset(
    {"contained_in", "part_of", "member_of", "subsidiary_of"}
)


class ResultEnricher:
    """Attaches user-facing metadata to a raw pipeline result.

    Constructed once per `PipelineRunner` in its `__init__` — not per resolve call.
    All domain knowledge is expressed through the declared
    `country_scoped_type_prefixes` and `country_relation_prefixes`; no literal
    pack-name or entity-type strings appear here.
    """

    def __init__(
        self,
        store: EntityStore | None,
        sources: list[CandidateSource],
        pack_id: str | None,
        candidate_ordering_key: Callable[[str], int | None] | None,
        country_scoped_type_prefixes: frozenset[str],
        country_relation_prefixes: frozenset[str],
    ) -> None:
        self._store = store
        self._sources = sources
        self._pack_id = pack_id
        self._candidate_ordering_key = candidate_ordering_key
        self._country_scoped_type_prefixes = country_scoped_type_prefixes
        self._country_relation_prefixes = country_relation_prefixes

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def finalize_result(
        self,
        result: ResolutionResult,
        final_candidates: list[Candidate] | None,
        context: ResolutionContext,
        query: Query | None,
        *,
        derive_hints_fn: Callable[
            [
                ResolutionResult,
                list[Candidate],
                dict[str, EntityRecord],
                ResolutionContext,
                Query | None,
            ],
            list[RefinementHint],
        ]
        | None = None,
    ) -> ResolutionResult:
        """Attach user-facing metadata to a pipeline result.

        Args:
            result: Raw result from the decision policy.
            final_candidates: Full internal candidate list (may be None on early exit).
            context: Resolution context for the call.
            query: Original query (used for spelling hints).
            derive_hints_fn: Optional override for ``_derive_refinement_hints``; when
                provided (e.g. by a ``PipelineRunner`` subclass that overrides the method),
                this callable is used instead of the enricher's own implementation.  This
                allows ``_SpyRunner``-style test subclasses to intercept hint derivation
                even after the logic has moved to ``ResultEnricher``.
        """
        hints_fn = derive_hints_fn or self._derive_refinement_hints

        result = self._attach_recovery_candidates(result, final_candidates)
        candidate_map = {
            candidate.entity_id: candidate for candidate in (final_candidates or [])
        }

        # On a bare NO_MATCH with no pipeline candidates, check for spelling
        # suggestions before loading entities so enrichment picks them up.
        # The first-pass hint derivation is intentionally cheap (entities={}) and
        # only runs on this narrow path to avoid a double-call on RESOLVED/AMBIGUOUS.
        query_text = query.normalized.normalized if query is not None else ""
        did_you_mean_active = False
        refinement_hints: list[RefinementHint] = []
        if result.status == ResolutionStatus.NO_MATCH and not result.candidates:
            close_candidates_pre = self._close_candidates(result, candidate_map)
            first_pass_hints = hints_fn(
                result,
                close_candidates_pre,
                {},
                context,
                query,
            )
            if RefinementHint.DID_YOU_MEAN in first_pass_hints:
                did_you_mean_candidates = self._spelling_suggestions(query_text)
                if did_you_mean_candidates:
                    result = result.model_copy(
                        update={"candidates": tuple(did_you_mean_candidates)}
                    )
                    did_you_mean_active = True
                    refinement_hints = first_pass_hints

        entities = self._load_result_entities(result)
        result = self._enrich_result_candidates(result, entities, candidate_map)
        close_candidates = self._close_candidates(result, candidate_map)
        reasons = self._refine_result_reasons(result, close_candidates, context)
        match_tier = self._derive_result_match_tier(result, candidate_map)
        if not did_you_mean_active:
            refinement_hints = hints_fn(
                result,
                close_candidates,
                entities,
                context,
                query,
            )

        return result.model_copy(
            update={
                "pack_id": result.pack_id or self._pack_id,
                "match_tier": result.match_tier or match_tier,
                "reasons": tuple(reasons),
                "refinement_hints": tuple(
                    dict.fromkeys(result.refinement_hints or refinement_hints)
                ),
            }
        )

    # ------------------------------------------------------------------
    # Recovery / enrichment helpers
    # ------------------------------------------------------------------

    def _attach_recovery_candidates(
        self,
        result: ResolutionResult,
        final_candidates: list[Candidate] | None,
    ) -> ResolutionResult:
        """Populate candidate summaries for recovery-oriented outcomes."""
        if result.candidates or not final_candidates:
            return result
        if result.status not in {
            ResolutionStatus.RESOLVED,
            ResolutionStatus.AMBIGUOUS,
            ResolutionStatus.NO_MATCH,
        }:
            return result

        summaries = tuple(
            build_candidate_summary(candidate)
            for candidate in final_candidates[:DEFAULT_TOP_K_RESULTS]
        )
        return result.model_copy(update={"candidates": summaries})

    def _load_result_entities(
        self,
        result: ResolutionResult,
    ) -> dict[str, EntityRecord]:
        """Load entities referenced by the public result payload.

        Result candidates are capped at DEFAULT_TOP_K_RESULTS (5), so a few
        cached single-entity fetches are cheaper than a 4-statement bulk
        query that re-pays parse, fetchall, and pydantic validation cost
        for the same entities the scoring path likely just touched.
        """
        if not result.candidates:
            return {}
        store = self._require_store()
        ids = [summary.entity_id for summary in result.candidates]
        if len(ids) <= DEFAULT_TOP_K_RESULTS:
            entities: dict[str, EntityRecord] = {}
            for eid in ids:
                ent = store.get_entity(eid)
                if ent is not None:
                    entities[eid] = ent
            return entities
        return store.bulk_get_entities(ids)

    def _enrich_result_candidates(
        self,
        result: ResolutionResult,
        entities: dict[str, EntityRecord],
        candidate_map: dict[str, Candidate],
    ) -> ResolutionResult:
        """Populate display metadata on result candidates using loaded entities."""
        if not result.candidates:
            return result

        enriched = []
        for summary in result.candidates:
            entity = entities.get(summary.entity_id)
            candidate = candidate_map.get(summary.entity_id)
            match_tier = summary.match_tier
            if match_tier is None and candidate is not None:
                match_tier = derive_candidate_match_tier(candidate)
            enriched.append(
                summary.model_copy(
                    update={
                        "canonical_name": (
                            entity.canonical_name if entity is not None else None
                        ),
                        "entity_type": entity.entity_type
                        if entity is not None
                        else None,
                        "pack_id": summary.pack_id or self._pack_id,
                        "match_tier": match_tier,
                    }
                )
            )

        # Re-order so specific types precede aggregating ones when confidence buckets
        # are equal. Guard fires only when both specificity classes are present.
        if self._candidate_ordering_key is not None:
            ordering_key = self._candidate_ordering_key

            def rank_of(c: CandidateSummary) -> int:
                r = ordering_key(c.entity_type) if c.entity_type else None
                return 99 if r is None else r

            ranks: dict[str, int] = {c.entity_id: rank_of(c) for c in enriched}
            has_specific = any(r <= 1 for r in ranks.values())
            has_aggregating = any(2 <= r <= 3 for r in ranks.values())
            if has_specific and has_aggregating:
                enriched = sorted(
                    enriched,
                    key=lambda c: (-round(c.confidence or 0.0, 3), ranks[c.entity_id]),
                )

        return result.model_copy(update={"candidates": tuple(enriched)})

    def _derive_result_match_tier(
        self,
        result: ResolutionResult,
        candidate_map: dict[str, Candidate],
    ) -> MatchTier | None:
        """Determine the tier associated with the public result."""
        if result.match_tier is not None:
            return result.match_tier
        if result.entity_id:
            winning_candidate = candidate_map.get(result.entity_id)
            if winning_candidate is not None:
                return derive_candidate_match_tier(winning_candidate)
        if result.candidates:
            ranked_tiers = [summary.match_tier for summary in result.candidates]
            return max(
                ranked_tiers,
                key=match_tier_rank,
                default=None,
            )
        if result.reasons:
            return reason_to_match_tier(result.reasons[0])
        return None

    def _refine_result_reasons(
        self,
        result: ResolutionResult,
        close_candidates: list[Candidate],
        context: ResolutionContext,
    ) -> list[ReasonCode]:
        """Replace generic ambiguity reasons with actionable collision reasons."""
        reasons = list(result.reasons)
        if result.status != ResolutionStatus.AMBIGUOUS or not reasons:
            return reasons
        if reasons[0] != ReasonCode.AMBIGUOUS_LOW_GAP:
            return reasons

        if self._has_parent_conflict(close_candidates, context):
            return [ReasonCode.CONTEXT_PARENT_CONFLICT]
        if self._has_country_conflict(close_candidates, context):
            return [ReasonCode.CONTEXT_COUNTRY_CONFLICT]
        if self._looks_like_sibling_collision(result):
            return [ReasonCode.AMBIGUOUS_SIBLING_ENTITIES]
        return reasons

    def _derive_refinement_hints(
        self,
        result: ResolutionResult,
        close_candidates: list[Candidate],
        entities: dict[str, EntityRecord],
        context: ResolutionContext,
        query: Query | None = None,
    ) -> list[RefinementHint]:
        """Suggest which ResolutionContext fields would best improve the next attempt."""
        if result.status not in {
            ResolutionStatus.AMBIGUOUS,
            ResolutionStatus.NO_MATCH,
        }:
            return list(result.refinement_hints)

        if result.status == ResolutionStatus.NO_MATCH and not result.candidates:
            query_text = query.normalized.normalized if query is not None else ""
            return self._spelling_hints(result, query_text=query_text)

        hints: list[RefinementHint] = []
        candidate_entities = [
            entities[summary.entity_id]
            for summary in result.candidates
            if summary.entity_id in entities
        ]

        if not context.entity_types and self._should_hint_types(result):
            hints.append(RefinementHint.ENTITY_TYPES)
        if not context.parent_ids and self._should_hint_parent(
            candidate_entities, close_candidates
        ):
            hints.append(RefinementHint.PARENT_IDS)
        if not context.country and self._should_hint_country(candidate_entities):
            hints.append(RefinementHint.COUNTRY)
        if not context.languages and self._should_hint_languages(candidate_entities):
            hints.append(RefinementHint.LANGUAGES)
        return hints[:4]

    def _spelling_hints(
        self,
        result: ResolutionResult,
        query_text: str | None,
    ) -> list[RefinementHint]:
        """Return DID_YOU_MEAN hint when any source offers spelling suggestions."""
        hints = list(result.refinement_hints)
        if not query_text:
            return hints

        for source in self._sources:
            suggest = getattr(source, "spelling_suggestions", None)
            if not callable(suggest):
                continue
            try:
                suggestions = suggest(query_text)
            except Exception:
                logger.debug("spelling_suggestions failed", exc_info=True)
                continue
            if suggestions:
                if RefinementHint.DID_YOU_MEAN not in hints:
                    hints.append(RefinementHint.DID_YOU_MEAN)
                return hints
        return hints

    def _spelling_suggestions(
        self,
        query_text: str,
    ) -> list[CandidateSummary]:
        """Build CandidateSummary entries from spelling suggestions.

        Walks each source's spelling_suggestions(), looks up entity IDs for each
        corrected term, deduplicates by entity_id, and caps at 3 candidates.
        Skips zero-edit suggestions (term == query_text) and terms with no
        entity match.
        """
        seen: set[str] = set()
        candidates: list[CandidateSummary] = []
        store = self._require_store()

        for source in self._sources:
            suggest = getattr(source, "spelling_suggestions", None)
            if not callable(suggest):
                continue
            try:
                suggestions = suggest(query_text)
            except Exception:
                logger.debug("spelling_suggestions failed", exc_info=True)
                continue
            for suggestion in suggestions:
                if suggestion.term == query_text:
                    continue  # zero-edit suggestion — useless
                entity_ids = store.lookup_name_exact(
                    suggestion.term,
                    name_kinds=getattr(source, "_name_kinds", None),
                )
                for entity_id in entity_ids:
                    if entity_id in seen:
                        continue
                    seen.add(entity_id)
                    candidates.append(
                        CandidateSummary(
                            entity_id=entity_id, match_tier=MatchTier.FUZZY
                        )
                    )
                    if len(candidates) >= 3:
                        return candidates
            if len(candidates) >= 3:
                return candidates
        return candidates

    def _should_hint_types(self, result: ResolutionResult) -> bool:
        """Type hints help when candidate domains or entity types diverge."""
        candidate_pack_ids = {
            summary.pack_id for summary in result.candidates if summary.pack_id
        }
        if len(candidate_pack_ids) > 1:
            return True
        entity_types = {
            summary.entity_type for summary in result.candidates if summary.entity_type
        }
        return len(entity_types) > 1

    def _should_hint_parent(
        self,
        entities: list[EntityRecord],
        close_candidates: list[Candidate],
    ) -> bool:
        """Parent hints help for sibling entities or parent-scoped orgs/places."""
        if self._has_parent_constraint_data(close_candidates):
            return True
        return any(
            relation.relation_type in PARENT_RELATION_TYPES
            for entity in entities
            for relation in entity.relations
        )

    def _should_hint_country(self, entities: list[EntityRecord]) -> bool:
        """Country hints help when entities carry country-specific metadata.

        Uses the pack-declared ``country_scoped_type_prefixes`` and
        ``country_relation_prefixes`` to detect whether an entity is a
        country-scoped type or points to a country-scoped relation target.
        Packs that declare neither only trigger the ``country_code`` attribute
        check, so non-geographic domains (e.g. orgs) are not offered a country
        hint they cannot act on.
        """
        for entity in entities:
            if "country_code" in entity.attributes:
                return True
            # Check if entity type starts with any country-scoped type prefix
            if self._country_scoped_type_prefixes and any(
                entity.entity_type.startswith(f"{prefix}.")
                or entity.entity_type == prefix
                for prefix in self._country_scoped_type_prefixes
            ):
                return True
            # Check if any relation target starts with a declared country relation prefix
            if self._country_relation_prefixes and any(
                any(
                    rel.target_id.startswith(pfx)
                    for pfx in self._country_relation_prefixes
                )
                for rel in entity.relations
            ):
                return True
        return False

    def _should_hint_languages(self, entities: list[EntityRecord]) -> bool:
        """Language hints help when candidate names span multiple languages."""
        languages = {
            name.lang
            for entity in entities
            for name in entity.names
            if name.lang is not None
        }
        return len(languages) > 1

    def _close_candidates(
        self,
        result: ResolutionResult,
        candidate_map: dict[str, Candidate],
    ) -> list[Candidate]:
        """Return internal candidates corresponding to public candidates in order."""
        if not candidate_map or not result.candidates:
            return []
        return [
            candidate_map[summary.entity_id]
            for summary in result.candidates
            if summary.entity_id in candidate_map
        ]

    def _has_parent_constraint_data(self, candidates: list[Candidate]) -> bool:
        """Return True when candidates include parent-related constraint outcomes.

        Uses ``outcome.role`` (ConstraintRole.PARENT_SCOPE / CONTAINMENT_SCOPE)
        instead of ``outcome.constraint_name`` string checks.
        """
        for candidate in candidates:
            for outcome in candidate.constraint_outcomes:
                if outcome.role in {
                    ConstraintRole.PARENT_SCOPE,
                    ConstraintRole.CONTAINMENT_SCOPE,
                }:
                    return True
        return False

    def _has_parent_conflict(
        self,
        candidates: list[Candidate],
        context: ResolutionContext,
    ) -> bool:
        """Return True when provided parent context does not isolate a winner.

        Uses ``outcome.role`` instead of ``outcome.constraint_name`` string checks.
        """
        if not context.parent_ids or not candidates:
            return False
        parent_outcomes = [
            outcome.passed
            for candidate in candidates
            for outcome in candidate.constraint_outcomes
            if outcome.role
            in {ConstraintRole.PARENT_SCOPE, ConstraintRole.CONTAINMENT_SCOPE}
        ]
        if not parent_outcomes:
            return False
        true_count = sum(outcome is True for outcome in parent_outcomes)
        return true_count != 1

    def _has_country_conflict(
        self,
        candidates: list[Candidate],
        context: ResolutionContext,
    ) -> bool:
        """Return True when provided country context still leaves a collision.

        Uses ``outcome.role == ConstraintRole.COUNTRY_SCOPE`` instead of
        constraint-name string comparisons.
        """
        if not context.country or not candidates:
            return False
        country_outcomes = [
            outcome.passed
            for candidate in candidates
            for outcome in candidate.constraint_outcomes
            if outcome.role == ConstraintRole.COUNTRY_SCOPE
        ]
        if not country_outcomes:
            return False
        true_count = sum(outcome is True for outcome in country_outcomes)
        return true_count != 1

    def _looks_like_sibling_collision(self, result: ResolutionResult) -> bool:
        """Return True when ambiguous candidates appear to be sibling entities."""
        if len(result.candidates) < 2:
            return False
        entity_types = {
            summary.entity_type for summary in result.candidates if summary.entity_type
        }
        if len(entity_types) == 1:
            return True
        return all(
            summary.pack_id == result.candidates[0].pack_id
            for summary in result.candidates
            if summary.pack_id is not None
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_store(self) -> EntityStore:
        """Return the configured store or raise if missing."""
        if self._store is None:
            raise ValueError("Pipeline requires a store to be configured")
        return self._store
