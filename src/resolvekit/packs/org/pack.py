"""Org domain pack - full implementation."""

from __future__ import annotations

from pathlib import Path

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
from resolvekit.packs._artifacts import load_scoring_artifacts
from resolvekit.packs.org.constraints import (
    CountryRelevanceConstraint,
    OrgTemporalConstraint,
    OrgTypeConstraint,
    ParentOrgConstraint,
)
from resolvekit.packs.org.decision import OrgDecisionPolicy
from resolvekit.packs.org.feature_extractor import OrgFeatureExtractor
from resolvekit.packs.org.normalizer import OrgNormalizer
from resolvekit.packs.org.routing import org_scoring_fn
from resolvekit.packs.org.scoring import OrgScorer
from resolvekit.packs.org.sources import (
    OrgAcronymSource,
    OrgExactCodeSource,
    OrgExactNameSource,
    OrgFTSSource,
    OrgFuzzySource,
    OrgSymSpellSource,
)

# Org normalization profile: aggressive, strips punctuation for matching
ORG_NORMALIZATION_PROFILE = NormalizationProfile(
    unicode_nfc=True,
    casefold=True,
    strip_whitespace=True,
    strip_punctuation=True,  # Strip punctuation like "AT&T" → "ATT"
    preserve_digits=True,
)


class OrgPack:
    """Organization domain pack.

    Key differences from GeoPack:
    - Acronym source is first-class (not fuzzy fallback)
    - Parent org context support
    - Stricter ambiguity detection for acronyms
    - Country relevance as soft constraint
    """

    DATAPACK_DIR: Path = Path(__file__).parent / "data"
    GROUP_ENTITY_TYPES: frozenset[str] = frozenset()

    def __init__(
        self,
        symspell_dict_path: str | None = None,
        calibrator_path: str | None = None,
        model_path: str | None = None,
    ):
        self._model_path = model_path

        self._sources: list[CandidateSource] = [
            OrgExactCodeSource(),
            OrgExactNameSource(),
            OrgAcronymSource(),
            OrgSymSpellSource(dictionary_path=symspell_dict_path),
            OrgFTSSource(),
            OrgFuzzySource(),
        ]

        self._constraints: list[Constraint] = [
            OrgTypeConstraint(),
            ParentOrgConstraint(),
            OrgTemporalConstraint(),
            CountryRelevanceConstraint(),
        ]

        self._feature_extractor: FeatureExtractor = OrgFeatureExtractor()

        artifacts = load_scoring_artifacts(
            model_path=model_path, calibrator_path=calibrator_path
        )
        self._scorer = OrgScorer(model=artifacts.model, calibrator=artifacts.calibrator)

        t = self._scorer.decision_thresholds
        self._decision_policy: DecisionPolicy = OrgDecisionPolicy(
            confidence_threshold=t.confidence_threshold,
            min_gap=t.min_gap,
        )

        self._routing_hints = RoutingHints(
            type_prefixes=["org"],
            keywords=[
                "bank",
                "union",
                "organization",
                "foundation",
                "institute",
                "fund",
                "corporation",
                "company",
            ],
            scoring_fn=org_scoring_fn,
            # org has no country relation prefixes
        )

        self._merge_normalizer: Normalizer = OrgNormalizer()

    @property
    def pack_id(self) -> str:
        return "org"

    @property
    def group_entity_types(self) -> frozenset[str]:
        return self.GROUP_ENTITY_TYPES

    @property
    def normalization_profile(self) -> NormalizationProfile:
        return ORG_NORMALIZATION_PROFILE

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
    def scorer(self) -> OrgScorer:
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
        """Org pack has no candidate ordering opinion; always returns None."""
        return None

    def get_source(self, name: str) -> CandidateSource | None:
        """Get a source by name."""
        return next((s for s in self.sources if s.name == name), None)
