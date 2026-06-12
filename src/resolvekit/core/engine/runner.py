"""Pipeline runner - the core resolution engine."""

from __future__ import annotations

import logging
import time
import traceback
from collections import defaultdict
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from resolvekit.core.engine.suggest_rank import SuggestCandidate

from resolvekit.core.engine import _stages
from resolvekit.core.engine.config import PipelineConfig
from resolvekit.core.engine.interfaces import (
    _TIMEOUT_RESULT,
    CandidateSource,
    Constraint,
    DecisionPolicy,
    FeatureExtractor,
    PipelineResult,
    Scorer,
)
from resolvekit.core.engine.tier_utils import (
    DEFAULT_BUDGET,
)
from resolvekit.core.explain import NullTraceSink, TraceSink
from resolvekit.core.explain.events import EventType, TraceEvent
from resolvekit.core.linking import BaseNormalizer, Normalizer
from resolvekit.core.model import (
    Candidate,
    CandidateEvidence,
    EntityRecord,
    Query,
    ReasonCode,
    RefinementHint,
    ResolutionContext,
    ResolutionResult,
    ResolutionStatus,
)
from resolvekit.core.store import EntityStore
from resolvekit.core.store.store_view import StoreView

logger = logging.getLogger(__name__)


class PipelineRunner:
    """The core resolution pipeline runner.

    Executes a resolution pipeline:
    1. Generate candidates from ALL sources (including rerankers)
    2. Merge candidates (dedup by entity_id)
    3. Apply constraints
    4. Extract features
    5. Score and calibrate
    6. Decide final result
    """

    def __init__(
        self,
        trace_sink: TraceSink | None = None,
        store: EntityStore | None = None,
        sources: list[CandidateSource] | None = None,
        constraints: list[Constraint] | None = None,
        feature_extractor: FeatureExtractor | None = None,
        scorer: Scorer | None = None,
        config: PipelineConfig | None = None,
        budget: int = DEFAULT_BUDGET,
        pack_id: str | None = None,
        candidate_ordering_key: Callable[[str], int | None] | None = None,
        code_normalizer: Normalizer | None = None,
        *,
        decision_policy: DecisionPolicy,
        group_entity_types: frozenset[str] = frozenset(),
        type_prefixes: frozenset[str] = frozenset(),
        country_relation_prefixes: frozenset[str] = frozenset(),
        country_scoped_type_prefixes: frozenset[str] = frozenset(),
    ) -> None:
        self._trace = trace_sink or NullTraceSink()
        self._store = store
        self._sources = sources or []
        self._constraints = constraints or []
        self._feature_extractor = feature_extractor
        self._scorer = scorer
        self._decision_policy = decision_policy
        self._config = config
        self._budget = budget
        self._pack_id = pack_id
        self._candidate_ordering_key = candidate_ordering_key
        self._code_normalizer: Normalizer = (
            code_normalizer if code_normalizer is not None else BaseNormalizer()
        )
        self._group_entity_types = group_entity_types
        self._type_prefixes = type_prefixes
        self._country_relation_prefixes = country_relation_prefixes
        self._country_scoped_type_prefixes = country_scoped_type_prefixes
        # Map source names to their reason codes for decision logic
        self._source_reason_codes: dict[str, ReasonCode] = {
            source.name: source.reason_code for source in self._sources
        }
        from resolvekit.core.engine.enrichment import (
            ResultEnricher,
        )  # local to avoid circular

        self._enricher = ResultEnricher(
            store=store,
            sources=self._sources,
            pack_id=pack_id,
            candidate_ordering_key=candidate_ordering_key,
            country_scoped_type_prefixes=country_scoped_type_prefixes,
            country_relation_prefixes=country_relation_prefixes,
        )
        self._view = StoreView([(pack_id, store)] if store is not None else [])
        # Lazy cache for suggest_prefix: maps entity_type_prefixes key → name list.
        # Built on first suggest call; never warmed in __init__ (cold-start is measured).
        self._suggest_names_cache: dict[
            frozenset[str] | None, list[tuple[str, str, str, bool, str]]
        ] = {}

    def warm(self) -> None:
        """Eagerly build all lazily-constructed source indexes.

        Calls ``warm()`` on every candidate source. A source that raises during
        warm-up is silently skipped (debug-logged); it degrades to its normal
        lazy-build path. Safe to call concurrently — per-source build locks
        make the operation idempotent.
        """
        for source in self._sources:
            try:
                source.warm()
            except Exception:
                logger.debug(
                    "warm() failed for source %r; source will build lazily",
                    source.name,
                    exc_info=True,
                )

    def close(self) -> None:
        """Close the underlying store."""
        if self._store is not None:
            self._store.close()

    def apply_confidence_threshold(self, *, threshold: float) -> bool:
        """Set confidence_threshold on the decision policy if it supports one.

        Args:
            threshold: New minimum calibrated score for RESOLVED results.

        Returns:
            True if the policy was updated, False if the policy does not
            expose a confidence_threshold (caller may wish to warn).
        """
        from resolvekit.core.engine.decision import (
            ThresholdDecisionPolicy,
        )  # local to avoid circular

        if isinstance(self._decision_policy, ThresholdDecisionPolicy):
            self._decision_policy.confidence_threshold = threshold
            return True
        return False

    @property
    def trace_sink(self) -> TraceSink:
        """Return the trace sink for event collection."""
        return self._trace

    @property
    def available_packs(self) -> frozenset[str]:
        """Return the valid pack IDs for this runner."""
        if self._pack_id is None:
            return frozenset()
        return frozenset({self._pack_id})

    def get_entity(self, entity_id: str) -> EntityRecord | None:
        """Fetch a fully hydrated entity record from the configured store."""
        return self._view.get_entity(entity_id)

    def normalize_code_value(
        self, system: str, value: str, *, pack_filter: frozenset[str] | None = None
    ) -> str:
        """Normalize *value* for *system* using this runner's code normalizer.

        Single-pack runners delegate to the normalizer supplied at construction
        (defaulting to ``BaseNormalizer``).  ``pack_filter`` is accepted for
        interface compatibility but is ignored — a single-pack runner owns one
        normalizer regardless of filter.

        Args:
            system: Code system name (e.g., ``"iso3"``).
            value: Raw query value.
            pack_filter: Accepted for interface parity; unused here.

        Returns:
            Normalized code value.
        """
        return self._code_normalizer.normalize_code(system, value)

    def lookup_code(
        self,
        system: str,
        value_norm: str,
        *,
        pack_filter: frozenset[str] | None = None,
    ) -> list[str]:
        """Look up entity IDs by code system and normalized value.

        Args:
            system: Code system name (e.g., "iso2").
            value_norm: Already-normalized lookup value.
            pack_filter: When set, restrict the lookup to those pack ids. None
                aggregates across the runner's pack (current behaviour). The
                single-pack runner returns ``[]`` if its pack id is excluded.
        """
        return self._view.lookup_code(system, value_norm, pack_filter=pack_filter)

    def lookup_code_attributed(
        self,
        *,
        system: str,
        value_norm: str,
        pack_filter: frozenset[str] | None = None,
    ) -> list[tuple[str, str]]:
        """Return (pack_id, entity_id) pairs for a code lookup in this pack."""
        return self._view.lookup_code_attributed(
            system=system, value_norm=value_norm, pack_filter=pack_filter
        )

    def _require_store(self) -> EntityStore:
        """Return the configured store or raise if missing."""
        if self._store is None:
            raise ValueError("Pipeline requires a store to be configured")
        return self._store

    # ------------------------------------------------------------------
    # ResolverBackend introspection methods (single-pack semantics)
    # ------------------------------------------------------------------

    @property
    def available_entity_types(self) -> frozenset[str]:
        """Return the entity type prefixes declared by this pack."""
        return self._type_prefixes

    @property
    def available_code_systems(self) -> frozenset[str]:
        """Return all code systems available in this pack's store."""
        return self._view.available_code_systems()

    @property
    def available_group_types(self) -> frozenset[str]:
        """Return the group entity types declared by this pack."""
        return self._group_entity_types

    def get_reverse_relations(
        self,
        *,
        entity_id: str,
        relation_type: str,
        as_of: date | None = None,
    ) -> list[str]:
        """Return entity IDs that have a relation of relation_type pointing to entity_id."""
        return self._view.get_reverse_relations(
            entity_id=entity_id, relation_type=relation_type, as_of=as_of
        )

    def get_relations_as_of(
        self,
        *,
        entity_id: str,
        relation_type: str,
        as_of: date,
    ) -> frozenset[str]:
        """Return the set of target entity IDs for a relation as of a given date."""
        return self._view.get_relations_as_of(
            entity_id=entity_id, relation_type=relation_type, as_of=as_of
        )

    def list_entities_by_type(
        self,
        *,
        entity_type: str,
    ) -> list[EntityRecord]:
        """Return all entities with the given entity_type in this pack's store."""
        return self._view.list_entities_by_type(entity_type=entity_type)

    def get_pack_group_types(
        self,
        *,
        pack_id: str,
    ) -> frozenset[str]:
        """Return the group entity types for the given pack.

        For a single-pack runner, returns the declared group_entity_types when
        pack_id matches; otherwise returns an empty frozenset.
        """
        if self._pack_id is None or pack_id != self._pack_id:
            return frozenset()
        return self._group_entity_types

    def is_snapshot_entity(
        self,
        *,
        entity_id: str,
    ) -> bool:
        """Return True if the entity carries attributes['snapshot'] = True."""
        return self._view.is_snapshot_entity(entity_id=entity_id)

    def lookup_pack_id(self) -> str | None:
        """Return this runner's pack ID (single-pack semantics)."""
        return self._pack_id

    def lookup_name_exact(
        self,
        *,
        value: str,
        pack_filter: frozenset[str] | None = None,
    ) -> list[tuple[str, str]]:
        """Return (pack_id, entity_id) pairs matching the given name exactly.

        When pack_filter is provided and this runner's pack_id is not in it,
        returns an empty list.
        """
        return self._view.lookup_name_exact(value=value, pack_filter=pack_filter)

    def store_for_domain(self, domain: str) -> EntityStore:
        """Return the EntityStore for the given domain.

        Single-pack runners hold exactly one store; the domain must match this
        runner's pack ID (exact or prefix) or ``ValueError`` is raised.

        Raises:
            ValueError: If the runner has no store or the domain doesn't match.
        """
        if self._store is None:
            raise ValueError(
                f"Cannot find EntityStore for domain '{domain}': runner has no store"
            )
        if self._pack_id is not None and (
            self._pack_id == domain or self._pack_id.startswith(domain)
        ):
            return self._store
        raise ValueError(
            f"Cannot find EntityStore for domain '{domain}'. "
            f"Available packs: {[self._pack_id] if self._pack_id else []}"
        )

    # ------------------------------------------------------------------
    # suggest_prefix — autocomplete path (bypasses resolution pipeline)
    # ------------------------------------------------------------------

    def suggest_prefix(
        self,
        *,
        query_norm: str,
        top_k: int,
        entity_type_prefixes: frozenset[str] | None = None,
        fuzzy: Literal["auto", "always", "never"] = "auto",
        deadline: float | None = None,
        pack_filter: frozenset[str] | None = None,
    ) -> list[SuggestCandidate]:
        """Return ranked suggest candidates for a normalized prefix.

        Produces candidates from three sources:
        1. Exact prefix (FTS5 ``search_prefix``).
        2. Token-infix (``search_token_infix``).
        3. Fuzzy brute-force (RapidFuzz over the memoized name list) —
           gated by ``fuzzy`` policy and ``suggest_rank`` constants.

        Candidates are deduplicated by entity_id (best match class wins),
        each entity is fetched once to populate prominence and canonical_name,
        and the list is sorted by ``suggest_rank.sort_key`` and truncated to
        ``top_k``.

        MUST NOT call ``resolve_detailed()``, run feature extraction, the
        scorer, the decision policy, or ``_QueryCache``.

        Args:
            query_norm: Already-normalized prefix string.
            top_k: Maximum number of candidates to return.
            entity_type_prefixes: Optional entity type filter.
            fuzzy: Fuzzy policy — ``"auto"``, ``"always"``, or ``"never"``.
            deadline: Absolute ``time.monotonic()`` deadline; returns partial
                results on overrun rather than raising.
            pack_filter: Accepted for interface parity with
                ``MultiPackRunner.suggest_prefix``; ignored here since a
                single-pack runner owns exactly one pack.

        Returns:
            Sorted ``list[SuggestCandidate]``, at most ``top_k`` entries.
        """
        from resolvekit.core.engine import suggest_rank
        from resolvekit.core.engine.suggest_rank import (
            FUZZY_AUTO_MAX_NAMES,
            FUZZY_DENYLIST_PREFIXES,
            MatchClass,
            SuggestCandidate,
            name_kind_rank,
            sort_key,
        )

        if not query_norm:
            return []
        store = self._store
        if store is None:
            return []

        # ------------------------------------------------------------------
        # Pool size for exact / infix sources — fetch a bit more than top_k
        # so the merge has headroom.
        # ------------------------------------------------------------------
        pool = min(max(top_k * 5, 50), 500)

        # ------------------------------------------------------------------
        # Exact-prefix hits (FTS5 ``term*`` query)
        # ------------------------------------------------------------------
        exact_hits = store.search_prefix(query_norm, "name", pool)

        # ------------------------------------------------------------------
        # Token-infix hits
        # ------------------------------------------------------------------
        infix_hits = store.search_token_infix(
            query_norm,
            entity_type_prefixes=entity_type_prefixes,
            limit=pool,
        )

        # ------------------------------------------------------------------
        # Build per-entity info map from exact + infix sources.
        # EXACT_PREFIX outranks TOKEN_PREFIX/INFIX: if an entity appears in
        # both exact and infix, it keeps EXACT_PREFIX.
        # Tuple: (match_class, matched_value_norm, match_score, typo_count)
        # ------------------------------------------------------------------
        entity_class: dict[str, tuple[MatchClass, str, float | None, int]] = {}

        for entity_id, _raw_score, _rank in exact_hits:
            entity_class[entity_id] = (MatchClass.EXACT_PREFIX, query_norm, None, 0)

        for entity_id, _raw_score, _rank in infix_hits:
            if entity_id not in entity_class:
                entity_class[entity_id] = (MatchClass.INFIX, query_norm, None, 0)

        # ------------------------------------------------------------------
        # Fuzzy phase (gated by policy + denylist + size)
        # ------------------------------------------------------------------
        over_deadline = deadline is not None and time.monotonic() >= deadline
        # Short-prefix fast-path: when exact+infix already fills top_k, fuzzy
        # adds noise but no useful typo correction on a 1-2 char query — skip
        # the brute-force phase to stay within the 10 ms warm budget.
        fast_path_full = fuzzy == "auto" and len(entity_class) >= top_k

        if fuzzy != "never" and not over_deadline and not fast_path_full:
            # Determine whether the denylist blocks fuzzy for this filter set.
            denylist_active = (
                entity_type_prefixes is not None
                and fuzzy == "auto"
                and any(
                    prefix == deny or prefix.startswith(f"{deny}.")
                    for prefix in entity_type_prefixes
                    for deny in FUZZY_DENYLIST_PREFIXES
                )
            )

            if not denylist_active or fuzzy == "always":
                # Lazily materialize the name list (memoized per filter set).
                # When fuzzy="auto" with no entity-type filter, the full name
                # set may include large denylist tiers (e.g. cities) that would
                # push the count past FUZZY_AUTO_MAX_NAMES and suppress fuzzy
                # for all bundled tiers.  Use a denylist-excluded pool so the
                # size check reflects only the fuzzy-eligible name rows.
                if fuzzy == "auto" and entity_type_prefixes is None:
                    # Sentinel key: "auto with denylist types excluded" differs
                    # from the unfiltered (always) case.
                    _auto_denylist_key: frozenset[str] = frozenset(
                        {"__auto_denylist_excluded__"}
                    )
                    names_key: frozenset[str] | None = _auto_denylist_key
                    if names_key not in self._suggest_names_cache:
                        try:
                            # Exclude denylist entity-type rows using the
                            # store's entity_type_exclude_prefixes parameter
                            # so the size check reflects only fuzzy-eligible
                            # name rows.
                            self._suggest_names_cache[names_key] = list(
                                store.iter_suggest_names(
                                    entity_type_exclude_prefixes=FUZZY_DENYLIST_PREFIXES
                                )
                            )
                        except (NotImplementedError, TypeError):
                            # Store doesn't support the exclude param — fall
                            # back to unfiltered.  This means auto-fuzzy will
                            # be suppressed on packs with > 20k total names.
                            self._suggest_names_cache[names_key] = list(
                                store.iter_suggest_names(entity_type_prefixes=None)
                            )
                else:
                    names_key = entity_type_prefixes
                    if names_key not in self._suggest_names_cache:
                        try:
                            self._suggest_names_cache[names_key] = list(
                                store.iter_suggest_names(
                                    entity_type_prefixes=entity_type_prefixes
                                )
                            )
                        except NotImplementedError:
                            self._suggest_names_cache[names_key] = []
                names_list = self._suggest_names_cache[names_key]

                run_fuzzy = fuzzy == "always" or (
                    fuzzy == "auto" and len(names_list) <= FUZZY_AUTO_MAX_NAMES
                )

                if run_fuzzy and names_list:
                    fuzzy_cands = suggest_rank.fuzzy_candidates(
                        query_norm, names_list, top_k=top_k
                    )
                    # Keep the best fuzzy hit per entity_id (lowest sort_key =
                    # fewest typos, then cascade).  Exact/infix prefill entries
                    # (typo=0, non-FUZZY class) always outrank any fuzzy hit for
                    # the same entity, so skip entities already in entity_class.
                    best_fuzzy: dict[
                        str, tuple[MatchClass, str, float | None, int]
                    ] = {}
                    for fc in fuzzy_cands:
                        if fc.entity_id in entity_class:
                            # Exact/infix prefill wins; don't overwrite.
                            continue
                        candidate_entry = (
                            MatchClass.FUZZY,
                            fc.matched_value_norm,
                            fc.match_score,
                            fc.typo_count,
                        )
                        existing = best_fuzzy.get(fc.entity_id)
                        if existing is None or fc.typo_count < existing[3]:
                            best_fuzzy[fc.entity_id] = candidate_entry
                    entity_class.update(best_fuzzy)

        # ------------------------------------------------------------------
        # Fetch entity once per surviving candidate to get prominence,
        # name_kind, and canonical_name.
        # ------------------------------------------------------------------
        candidates: list[SuggestCandidate] = []
        for entity_id, (
            mc,
            matched_norm,
            match_score,
            typo_count,
        ) in entity_class.items():
            entity = self.get_entity(entity_id)
            if entity is None:
                continue

            # Apply entity_type_prefixes filter.  search_prefix and
            # search_token_infix may not support this natively, so we check
            # after fetching the entity.
            if entity_type_prefixes is not None and not any(
                entity.entity_type == p or entity.entity_type.startswith(f"{p}.")
                for p in entity_type_prefixes
            ):
                continue

            # Prominence: float in [0, 1]; absent → 0.0
            raw_prom = entity.attributes.get("prominence")
            prominence: float = 0.0
            if isinstance(raw_prom, (int, float)):
                prominence = float(raw_prom)

            # canonical_name: column > is_preferred name > first name
            canonical: str | None = entity.canonical_name or None
            if not canonical:
                for nr in entity.names:
                    if nr.is_preferred:
                        canonical = nr.value
                        break
            if not canonical and entity.names:
                canonical = entity.names[0].value

            # Best name_kind for the matched name (scan names for the norm).
            # exact_name_hit=True when a name record whose value_norm equals
            # matched_norm is found — i.e. the entity owns a name whose full
            # text equals the query, not merely starts with it.
            nk_rank = 3  # default: unknown kind
            matched_val = matched_norm  # fallback original-cased form
            exact_name_hit = False
            for nr in entity.names:
                if nr.value_norm == matched_norm:
                    nk_rank = name_kind_rank(nr.kind, is_preferred=nr.is_preferred)
                    matched_val = nr.value
                    exact_name_hit = True
                    break

            candidates.append(
                SuggestCandidate(
                    entity_id=entity_id,
                    match_class=mc,
                    exact_match=exact_name_hit and matched_norm == query_norm,
                    typo_count=typo_count,
                    prominence=prominence,
                    name_kind_rank=nk_rank,
                    matched_value_norm=matched_norm,
                    match_score=match_score,
                    pack_id=self._pack_id,
                    entity_type=entity.entity_type,
                    canonical_name=canonical,
                    matched_value=matched_val,
                )
            )

        candidates.sort(key=sort_key)
        return candidates[:top_k]

    def resolve(
        self,
        query: Query,
        context: ResolutionContext,
        *,
        trace_sink: TraceSink | None = None,
        deadline: float | None = None,
    ) -> ResolutionResult:
        """Run the resolution pipeline and return the final result.

        Use ``resolve_detailed()`` to retrieve the full ``PipelineResult``
        including candidates.
        """
        return self._run(
            query, context, trace_sink=trace_sink, deadline=deadline
        ).result

    def resolve_detailed(
        self,
        query: Query,
        context: ResolutionContext,
        *,
        trace_sink: TraceSink | None = None,
        deadline: float | None = None,
    ) -> PipelineResult:
        """Run the resolution pipeline and return full pipeline data including candidates."""
        return self._run(query, context, trace_sink=trace_sink, deadline=deadline)

    def _run(  # noqa: PLR0911 (resolution dispatch naturally has many early returns)
        self,
        query: Query,
        context: ResolutionContext,
        *,
        trace_sink: TraceSink | None = None,
        deadline: float | None = None,
    ) -> PipelineResult:
        """Run the resolution pipeline, returning a PipelineResult with candidates.

        Deadline checks are cooperative: a single blocking C-level call (e.g. a
        SymSpell lookup) cannot be preempted mid-call; checks occur between
        pipeline phases, not within them.

        Args:
            query: The resolution query
            context: Resolution context
            trace_sink: Optional per-call trace sink (falls back to self._trace)
            deadline: Absolute monotonic time by which the call must return.
                When exceeded, returns ERROR/TIMEOUT immediately.

        Returns:
            PipelineResult with result and full candidate list.
        """
        store = self._require_store()

        trace = trace_sink or self._trace

        # Helper to wrap result in PipelineResult
        def _make_result(
            result: ResolutionResult, final_candidates: list[Candidate] | None = None
        ) -> PipelineResult:
            enriched_result = self._finalize_result(
                result=result,
                final_candidates=final_candidates,
                context=context,
                query=query,
            )
            return PipelineResult(
                result=enriched_result,
                candidates=final_candidates,
            )

        sources = self._sources
        budget = self._budget
        config = self._config
        constraints = self._constraints
        feature_extractor = self._feature_extractor
        scorer = self._scorer
        source_reason_codes = self._source_reason_codes

        try:
            # Generate candidates from all primary sources
            all_evidence: dict[str, list[CandidateEvidence]] = defaultdict(list)
            _stages.run_primary_sources(
                query,
                context,
                all_evidence,
                trace,
                sources=sources,
                store=store,
                budget=budget,
                config=config,
                deadline=deadline,
            )

            if deadline is not None and time.monotonic() >= deadline:
                return _make_result(_TIMEOUT_RESULT)

            # Merge evidence into Candidate objects (deduplicate by entity_id)
            candidates = _stages.merge_candidates(all_evidence)
            trace.emit(
                TraceEvent(
                    event_type=EventType.CANDIDATES_MERGED,
                    data={"count": len(candidates)},
                )
            )

            if not candidates:
                return _make_result(
                    ResolutionResult(
                        status=ResolutionStatus.NO_MATCH,
                        reasons=(ReasonCode.NO_CANDIDATES,),
                    )
                )

            # Sort by initial retrieval score so rerankers process strongest first
            candidates.sort(
                key=lambda c: c.retrieval.best_raw_score or 0.0, reverse=True
            )

            # Run reranker sources that need existing candidates
            _stages.run_reranker_sources(
                query,
                context,
                candidates,
                trace,
                sources=sources,
                store=store,
                budget=budget,
                deadline=deadline,
            )

            if deadline is not None and time.monotonic() >= deadline:
                return _make_result(_TIMEOUT_RESULT)

            # Apply constraints (hard filters and soft enrichers)
            candidates = _stages.apply_constraints(
                query,
                context,
                candidates,
                trace,
                constraints=constraints,
                store=store,
                deadline=deadline,
            )
            if not candidates:
                return _make_result(
                    ResolutionResult(
                        status=ResolutionStatus.NO_MATCH,
                        reasons=(ReasonCode.FILTERED_BY_CONSTRAINT,),
                    )
                )

            if deadline is not None and time.monotonic() >= deadline:
                return _make_result(_TIMEOUT_RESULT)

            # Extract features and score candidates
            _stages.score_candidates(
                query,
                context,
                candidates,
                trace,
                store=store,
                feature_extractor=feature_extractor,
                scorer=scorer,
                deadline=deadline,
            )

            if deadline is not None and time.monotonic() >= deadline:
                return _make_result(_TIMEOUT_RESULT)

            # Sort by calibrated confidence
            candidates.sort(key=lambda c: c.scores.calibrated_score, reverse=True)

            # Check for early exit conditions (e.g. exact code match)
            stop_result = _stages.check_post_scoring_stop(
                candidates,
                config=config,
                source_reason_codes=source_reason_codes,
            )
            if stop_result is not None:
                trace.emit(
                    TraceEvent(
                        event_type=EventType.DECIDED,
                        data={
                            "status": stop_result.status.value,
                            "trigger": "post_scoring_stop_condition",
                        },
                    )
                )
                return _make_result(stop_result, candidates)

            # Make final decision
            result = self._decision_policy.decide(
                query=query,
                context=context,
                candidates=candidates,
                trace=trace,
            )
            trace.emit(
                TraceEvent(
                    event_type=EventType.DECIDED,
                    data={"status": result.status.value},
                )
            )
            return _make_result(result, candidates)

        except Exception as e:
            trace.emit(
                TraceEvent(
                    event_type=EventType.ERROR,
                    data={
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "traceback": traceback.format_exc(),
                    },
                )
            )
            return _make_result(
                ResolutionResult(
                    status=ResolutionStatus.ERROR,
                    reasons=(ReasonCode.INTERNAL_ERROR,),
                )
            )

    def _finalize_result(
        self,
        result: ResolutionResult,
        final_candidates: list[Candidate] | None,
        context: ResolutionContext,
        query: Query | None = None,
    ) -> ResolutionResult:
        """Attach user-facing metadata to a pipeline result.

        Delegates to ``ResultEnricher.finalize_result``, passing
        ``self._derive_refinement_hints`` so subclass overrides (e.g. spy runners in
        tests) are still honoured.
        """
        return self._enricher.finalize_result(
            result=result,
            final_candidates=final_candidates,
            context=context,
            query=query,
            derive_hints_fn=self._derive_refinement_hints,
        )

    def _derive_refinement_hints(
        self,
        result: ResolutionResult,
        close_candidates: list[Candidate],
        entities: dict[str, EntityRecord],
        context: ResolutionContext,
        query: Query | None = None,
    ) -> list[RefinementHint]:
        """Suggest which ResolutionContext fields would best improve the next attempt.

        Delegates to ``ResultEnricher._derive_refinement_hints``.  Kept on
        ``PipelineRunner`` so subclass overrides continue to intercept hint derivation.
        """
        return self._enricher._derive_refinement_hints(
            result=result,
            close_candidates=close_candidates,
            entities=entities,
            context=context,
            query=query,
        )
