"""Feature extractor for org domain pack."""

from resolvekit.core.engine import FeatureExtractor
from resolvekit.core.explain import TraceSink
from resolvekit.core.explain.events import EventType, TraceEvent
from resolvekit.core.model import Candidate, ConstraintRole, Query, ResolutionContext
from resolvekit.core.store import EntityStore
from resolvekit.packs.org._acronym import is_acronym_like
from resolvekit.packs.org.features import OrgFeaturesV1


class OrgFeatureExtractor(FeatureExtractor):
    """Extract typed features for org candidates.

    Populates OrgFeaturesV1 from:
    - Candidate evidence (source signals)
    - Constraint outcomes (context alignment)
    - Query properties (acronym detection)
    """

    @property
    def schema_version(self) -> str:
        return "org.features.v1"

    def extract(
        self,
        query: Query,
        context: ResolutionContext,
        candidate: Candidate,
        store: EntityStore,
        trace: TraceSink,
    ) -> OrgFeaturesV1:
        # Query features
        query_text = query.normalized.original
        query_is_acronym = self._is_acronym_like(query_text)

        # Source signals
        exact_code_hit = False
        acronym_hit = False
        acronym_exact = False
        exact_name_hit = False
        fts_bm25_norm = None

        for ev in candidate.sources:
            if ev.source_name == "org_exact_code":
                exact_code_hit = True
            elif ev.source_name == "org_acronym":
                acronym_hit = True
                acronym_exact = ev.matched_field == "name.acronym" and (
                    ev.raw_score is not None and ev.raw_score >= 0.99
                )
            elif ev.source_name == "org_exact_name":
                exact_name_hit = True
            elif ev.source_name == "org_fts":
                fts_bm25_norm = ev.raw_score

        # Read fuzzy signals from retrieval (populated by FuzzySource)
        fuzzy_edit_sim = candidate.retrieval.signals.get("fuzzy_edit_sim")
        token_set_sim = candidate.retrieval.signals.get("fuzzy_token_sim")

        # ResolutionContext alignment from constraints
        parent_org_match = None
        country_match = None
        type_match = None

        for co in candidate.constraint_outcomes:
            if co.role == ConstraintRole.PARENT_SCOPE:
                parent_org_match = co.passed
            elif co.role == ConstraintRole.COUNTRY_SCOPE:
                country_match = co.passed
            elif co.role == ConstraintRole.TYPE_SCOPE:
                type_match = co.passed

        features = OrgFeaturesV1(
            exact_code_hit=exact_code_hit,
            acronym_hit=acronym_hit,
            acronym_exact=acronym_exact,
            exact_name_hit=exact_name_hit,
            fts_bm25_norm=fts_bm25_norm,
            token_set_sim=token_set_sim,
            fuzzy_edit_sim=fuzzy_edit_sim,
            parent_org_match=parent_org_match,
            country_match=country_match,
            type_match=type_match,
            query_len=len(query.normalized.normalized),
            query_all_caps=query_text.isupper(),
            query_is_acronym_like=query_is_acronym,
            top1_top2_gap=None,  # Set later during scoring
            # candidate_prominence=None for v1; org enrichment deferred.
            # When org prominence lands (v1.1+), populate via entity.attributes["prominence"].
            candidate_prominence=None,
        )

        trace.emit(
            TraceEvent(
                event_type=EventType.FEATURES_EXTRACTED,
                source="org_feature_extractor",
                data={
                    "schema_version": self.schema_version,
                    "entity_id": candidate.entity_id,
                    "acronym_hit": acronym_hit,
                    "parent_match": parent_org_match,
                },
            )
        )

        return features

    def _is_acronym_like(self, text: str) -> bool:
        return is_acronym_like(text)
