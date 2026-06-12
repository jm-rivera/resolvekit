"""Feature extractor for geo domain pack."""

import math

from resolvekit.core.engine import FeatureExtractor
from resolvekit.core.explain import TraceSink
from resolvekit.core.explain.events import EventType, TraceEvent
from resolvekit.core.model import Candidate, ConstraintRole, Query, ResolutionContext
from resolvekit.core.store import EntityStore
from resolvekit.packs.geo.features import GeoFeaturesV1

# continent 1.0 > continental_union 0.9 > country 0.85 > organization 0.80
# > subregion 0.78 > region 0.75 > city 0.70 > admin1 0.65 > admin2 0.55
# > admin3 0.40 > admin4 0.35 > admin5 0.25
GEO_HIERARCHY_RANK: dict[str, float] = {
    "geo.continent": 1.0,
    "geo.continental_union": 0.9,
    "geo.country": 0.85,
    # Intergovernmental bodies (NATO, OECD, UN…) — above sub-continental regions
    # so a group beats a same-named region on a tie, but below countries.
    "geo.organization": 0.80,
    "geo.subregion": 0.78,
    "geo.region": 0.75,
    "geo.city": 0.70,
    "geo.admin1": 0.65,
    "geo.admin2": 0.55,
    "geo.admin3": 0.40,
    "geo.admin4": 0.35,
    "geo.admin5": 0.25,
}


class GeoFeatureExtractor(FeatureExtractor):
    """Extracts typed GeoFeaturesV1 from candidates.

    Reads evidence from candidate.sources and constraint outcomes
    to populate the feature schema.
    """

    @property
    def schema_version(self) -> str:
        return "geo.features.v1"

    def extract(
        self,
        query: Query,
        context: ResolutionContext,
        candidate: Candidate,
        store: EntityStore,
        trace: TraceSink,
    ) -> GeoFeaturesV1:
        """Extract features from candidate."""
        # Query features
        query_text = query.normalized.original
        query_len = len(query_text)
        query_has_digits = any(c.isdigit() for c in query_text)
        # ``query_is_upper`` gates the acronym/admin mismatch suppression in the
        # scorer (NASA -> admin "Nasa").  Period-delimited abbreviations
        # (U.S.A., D.C.) are not bare acronyms and legitimately alias geo
        # entities, so they must not trip that gate.
        query_is_upper = query_text.isupper() and "." not in query_text

        # Retrieval features from sources
        exact_code_hit = False
        exact_name_hit = False
        fts_bm25_norm = None
        fts_bm25_raw = None
        symspell_edit_norm = None

        for ev in candidate.sources:
            if ev.source_name.endswith("exact_code"):
                exact_code_hit = True
            elif ev.source_name.endswith("exact_name"):
                exact_name_hit = True
            elif ev.source_name.endswith("fts"):
                fts_bm25_norm = ev.raw_score
                raw_bm25 = ev.signals.get("bm25_raw")
                if raw_bm25 is not None:
                    fts_bm25_raw = min(
                        math.log1p(abs(raw_bm25)) / math.log1p(50.0),
                        1.0,
                    )
            elif ev.source_name.endswith("symspell"):
                symspell_edit_norm = ev.raw_score

        # Fuzzy signals are populated on retrieval, not as separate sources.
        fuzzy_edit_sim = candidate.retrieval.signals.get("fuzzy_edit_sim")
        fuzzy_token_sim = candidate.retrieval.signals.get("fuzzy_token_sim")

        # Rank inverse
        retrieval_rank_inv = None
        if candidate.retrieval.best_rank:
            retrieval_rank_inv = 1.0 / candidate.retrieval.best_rank

        # Constraint features
        containment_pass = None
        type_pass = None
        temporal_pass = None
        membership_pass = None

        for co in candidate.constraint_outcomes:
            if co.role == ConstraintRole.CONTAINMENT_SCOPE:
                containment_pass = co.passed
            elif co.role == ConstraintRole.TYPE_SCOPE:
                type_pass = co.passed
            elif co.role == ConstraintRole.TEMPORAL_SCOPE:
                temporal_pass = co.passed
            elif co.role == ConstraintRole.MEMBERSHIP_SCOPE:
                membership_pass = co.passed

        # Hierarchy rank from entity type
        hierarchy_rank = None
        entity = store.get_entity(candidate.entity_id)
        if entity is not None:
            hierarchy_rank = GEO_HIERARCHY_RANK.get(entity.entity_type)

        prominence_raw = (
            entity.attributes.get("prominence") if entity is not None else None
        )
        candidate_prominence: float | None = (
            float(prominence_raw) if isinstance(prominence_raw, int | float) else None
        )

        # FTS name overlap: max Jaccard between query tokens and any name token set.
        fts_name_overlap = None
        if fts_bm25_norm is not None and entity is not None:
            query_tokens = set(query.normalized.normalized.split())
            best_jaccard = 0.0
            for norm in (
                entity.canonical_name_norm,
                *(nr.value_norm for nr in entity.names),
            ):
                name_tokens = set(norm.split())
                union_size = len(query_tokens | name_tokens)
                if union_size > 0:
                    best_jaccard = max(
                        best_jaccard,
                        len(query_tokens & name_tokens) / union_size,
                    )
            fts_name_overlap = best_jaccard

        features = GeoFeaturesV1(
            # Retrieval
            exact_code_hit=exact_code_hit,
            exact_name_hit=exact_name_hit,
            fts_bm25_norm=fts_bm25_norm,
            fts_bm25_raw=fts_bm25_raw,
            symspell_edit_norm=symspell_edit_norm,
            fuzzy_edit_sim=fuzzy_edit_sim,
            fuzzy_token_sim=fuzzy_token_sim,
            retrieval_rank_inv=retrieval_rank_inv,
            fts_name_overlap=fts_name_overlap,
            # Query
            query_len=query_len,
            query_has_digits=query_has_digits,
            query_is_upper=query_is_upper,
            # Constraints
            containment_pass=containment_pass,
            type_pass=type_pass,
            temporal_pass=temporal_pass,
            membership_pass=membership_pass,
            # Candidate
            hierarchy_rank=hierarchy_rank,
            candidate_prominence=candidate_prominence,
        )

        trace.emit(
            TraceEvent(
                event_type=EventType.FEATURES_EXTRACTED,
                source="geo_feature_extractor",
                data={"schema_version": self.schema_version},
            )
        )

        return features
