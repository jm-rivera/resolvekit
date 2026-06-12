"""Generic / custom domain pack."""

from __future__ import annotations

from resolvekit.core.engine import (
    DEFAULT_PACK_PIPELINE_CONFIG,
    CandidateSource,
    Constraint,
    DecisionPolicy,
    FeatureExtractor,
    PipelineConfig,
)
from resolvekit.core.linking import Normalizer
from resolvekit.core.registry import RoutingHints
from resolvekit.core.util.normalization import NormalizationProfile
from resolvekit.packs.custom.decision import CustomDecisionPolicy
from resolvekit.packs.custom.extractor import CustomFeatureExtractor
from resolvekit.packs.custom.normalizer import CustomNormalizer
from resolvekit.packs.custom.scoring import CustomScorer
from resolvekit.packs.custom.sources import (
    CustomExactCodeSource,
    CustomExactNameSource,
    CustomFTSSource,
    CustomFuzzyRetrievalSource,
    CustomFuzzySource,
)

# Custom normalization profile: standard NFKC + casefold + whitespace collapse.
# No punctuation stripping (user data may have meaningful punctuation like
# "A-1" product codes) and no diacritics removal (names may use them).
CUSTOM_NORMALIZATION_PROFILE = NormalizationProfile(
    unicode_nfc=True,
    casefold=True,
    strip_whitespace=True,
    strip_punctuation=False,
    preserve_digits=True,
)


class GenericPack:
    """Generic (custom-domain) pack.

    Domain-agnostic sources, a heuristic scorer, and no type constraints —
    suitable for any programmatically-built record set (products, projects,
    custom entities, etc.).

    Sources (in pipeline order):
    1. CustomExactCodeSource        — catch-all ``lookup_code_any``; raw 1.0
    2. CustomExactNameSource        — canonical raw 1.0, alias raw 0.95
    3. CustomFTSSource              — BM25 ranked FTS
    4. CustomFuzzyRetrievalSource   — generating brute-force RapidFuzz over the
                                      store's materialized name list; emits
                                      FUZZY-tier evidence so typo'd queries that
                                      FTS cannot tokenize-match still produce
                                      candidates.  Free on exact-name queries
                                      (engine fuzzy-skip guard bypasses it when
                                      a confident EXACT_NAME candidate is present).
                                      Callers needing stricter precision can raise
                                      ``confidence_threshold`` above the 0.89 FUZZY
                                      cap to suppress fuzzy-tier results.
    5. CustomFuzzySource            — reranks existing candidates with
                                      ``fuzzy_edit_sim`` / ``fuzzy_token_sim``
                                      signals (requires_existing_candidates)

    Args:
        symspell_dict_path: Accepted but ignored to satisfy factory introspection.
        calibrator_path: Accepted but ignored (no calibration for custom packs).
        model_path: Accepted but ignored (no ML model for custom packs).
    """

    GROUP_ENTITY_TYPES: frozenset[str] = frozenset()

    def __init__(
        self,
        symspell_dict_path: str | None = None,
        calibrator_path: str | None = None,
        model_path: str | None = None,
    ) -> None:
        self._sources: list[CandidateSource] = [
            CustomExactCodeSource(),
            CustomExactNameSource(),
            CustomFTSSource(),
            CustomFuzzyRetrievalSource(),
            CustomFuzzySource(),
        ]

        self._constraints: list[Constraint] = []

        self._feature_extractor: FeatureExtractor = CustomFeatureExtractor()

        self._scorer = CustomScorer()

        self._decision_policy: DecisionPolicy = CustomDecisionPolicy()

        # Constant scoring prevents starvation of custom queries when mixed with
        # geo/org packs. A standalone custom resolver has unambiguous routing.
        self._routing_hints = RoutingHints(
            type_prefixes=["custom"],
            scoring_fn=lambda text, text_lower: 0.05,
        )

        self._merge_normalizer: Normalizer = CustomNormalizer()

    @property
    def pack_id(self) -> str:
        return "custom"

    @property
    def group_entity_types(self) -> frozenset[str]:
        return self.GROUP_ENTITY_TYPES

    @property
    def normalization_profile(self) -> NormalizationProfile:
        return CUSTOM_NORMALIZATION_PROFILE

    @property
    def sources(self) -> list[CandidateSource]:
        return self._sources

    @property
    def constraints(self) -> list[Constraint]:
        return self._constraints

    @property
    def feature_extractor(self) -> FeatureExtractor:
        return self._feature_extractor

    @property
    def scorer(self) -> CustomScorer:
        return self._scorer

    @property
    def decision_policy(self) -> DecisionPolicy:
        return self._decision_policy

    @property
    def routing_hints(self) -> RoutingHints:
        return self._routing_hints

    @property
    def merge_normalizer(self) -> Normalizer:
        return self._merge_normalizer

    @property
    def config(self) -> PipelineConfig:
        return DEFAULT_PACK_PIPELINE_CONFIG

    def candidate_ordering_key(self, entity_type: str) -> int | None:
        """Custom pack has no candidate ordering opinion."""
        return None

    def get_source(self, name: str) -> CandidateSource | None:
        return next((s for s in self.sources if s.name == name), None)
