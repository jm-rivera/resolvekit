"""Feature extractor for the custom domain pack."""

from resolvekit.core.engine import FeatureExtractor
from resolvekit.core.explain import TraceSink
from resolvekit.core.explain.events import EventType, TraceEvent
from resolvekit.core.model import Candidate, Query, ResolutionContext
from resolvekit.core.store import EntityStore
from resolvekit.packs.custom.features import CustomFeaturesV1

# This must match GenericDataPackBuilder.FEATURE_SCHEMA_VERSION exactly.
# _validate_feature_schema raises IncompatibleFeatureSchemaError if they drift.
_SCHEMA_VERSION = "custom.features.v1"


class CustomFeatureExtractor(FeatureExtractor):
    """Extract typed features for custom-domain candidates.

    Populates CustomFeaturesV1 from candidate evidence and retrieval signals.
    """

    @property
    def schema_version(self) -> str:
        return _SCHEMA_VERSION

    def extract(
        self,
        query: Query,
        context: ResolutionContext,
        candidate: Candidate,
        store: EntityStore,
        trace: TraceSink,
    ) -> CustomFeaturesV1:
        exact_code_hit = False
        exact_name_hit = False
        fts_bm25_norm = None

        for ev in candidate.sources:
            if ev.source_name == "custom_exact_code":
                exact_code_hit = True
            elif ev.source_name == "custom_exact_name":
                exact_name_hit = True
            elif ev.source_name == "custom_fts":
                fts_bm25_norm = ev.raw_score

        # Fuzzy signals are populated by CustomFuzzySource into retrieval.signals.
        fuzzy_edit_sim = candidate.retrieval.signals.get("fuzzy_edit_sim")
        fuzzy_token_sim = candidate.retrieval.signals.get("fuzzy_token_sim")

        features = CustomFeaturesV1(
            exact_code_hit=exact_code_hit,
            exact_name_hit=exact_name_hit,
            fts_bm25_norm=fts_bm25_norm,
            fuzzy_edit_sim=fuzzy_edit_sim,
            fuzzy_token_sim=fuzzy_token_sim,
            query_len=len(query.normalized.normalized),
        )

        trace.emit(
            TraceEvent(
                event_type=EventType.FEATURES_EXTRACTED,
                source="custom_feature_extractor",
                data={
                    "schema_version": self.schema_version,
                    "entity_id": candidate.entity_id,
                    "exact_code_hit": exact_code_hit,
                    "exact_name_hit": exact_name_hit,
                },
            )
        )

        return features
