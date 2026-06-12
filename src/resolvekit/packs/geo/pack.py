"""Geo domain pack - full implementation."""

from __future__ import annotations

from pathlib import Path

from resolvekit.core.engine import (
    CandidateSource,
    Constraint,
    DecisionPolicy,
    FeatureExtractor,
    PipelineConfig,
    StopCondition,
)
from resolvekit.core.linking import Normalizer
from resolvekit.core.registry import RoutingHints
from resolvekit.core.util.normalization import NormalizationProfile
from resolvekit.packs._artifacts import load_scoring_artifacts
from resolvekit.packs.geo._specificity import geo_candidate_ordering_key
from resolvekit.packs.geo.constraints import (
    GeoContainmentConstraint,
    GeoMembershipConstraint,
    GeoTemporalConstraint,
    GeoTypeConstraint,
)
from resolvekit.packs.geo.decision import GeoDecisionPolicy
from resolvekit.packs.geo.extractor import GeoFeatureExtractor
from resolvekit.packs.geo.normalizer import GeoNormalizer
from resolvekit.packs.geo.routing import geo_scoring_fn
from resolvekit.packs.geo.scoring import GeoScorer
from resolvekit.packs.geo.sources import (
    GeoExactCodeSource,
    GeoExactNameSource,
    GeoFTSSource,
    GeoFuzzyRetrievalSource,
    GeoFuzzySource,
    GeoSymSpellSource,
)

# Geo normalization profile: conservative, preserves diacritics.
# Markdown/HTML preprocessing is on by default so real-world inputs like
# "**Italy**" or "&amp;Spain" resolve without manual pre-cleaning.
GEO_NORMALIZATION_PROFILE = NormalizationProfile(
    unicode_nfc=True,
    casefold=True,
    strip_whitespace=True,
    strip_punctuation=False,  # Preserve punctuation like "St. Louis"
    preserve_digits=True,
    strip_markdown_formatting=True,
    decode_html_entities=True,
)

# Skip downstream retrieval when early sources already produced a decisive hit.
# Evaluated in generation phase against raw evidence scores (before scoring/calibration).
# exact_code emits raw 1.0; exact_name emits raw 1.0 (canonical) or 0.95 (alias).
GEO_PIPELINE_CONFIG = PipelineConfig(
    stop_conditions=[
        # exact_code is decisive regardless of candidate count: ISO code lookup
        # returning multiple entities reflects a real collision (e.g. deprecated
        # codes) that downstream fuzzy sources cannot disambiguate.
        StopCondition(
            name="exact_code_decisive",
            source_name="geo_exact_code",
            min_confidence=0.95,
            phase="generation",
        ),
        # exact_name short-circuits only when exactly one entity matches. Names
        # like "Saint Martin" (MAF/SXM) resolve to 2+ entities; those need
        # downstream sources to break the tie.
        StopCondition(
            name="exact_name_unambiguous",
            source_name="geo_exact_name",
            min_candidates=1,
            max_candidates=1,
            min_confidence=0.90,
            phase="generation",
        ),
    ]
)


def _build_symspell_pair(
    *,
    paths: list[str],
    symspell_name: str,
    fuzzy_name: str,
    large_tier: bool,
) -> tuple[GeoSymSpellSource, GeoFuzzyRetrievalSource]:
    """Build a lazily-built SymSpell source and a fuzzy-retrieval source sharing it.

    Both use full params (prefix_length=7, max_edit_distance=2). The first path
    seeds the index; any remaining paths are loaded as additional dictionaries.
    The fuzzy-retrieval source shares the SymSpell index rather than loading its
    own copy.

    ``use_compiled_cache`` is enabled only for the LARGE tier (admin2-5 / cities,
    ~706k terms, ~6s text build).  The SMALL tier builds in ~0.15s and does not
    justify the ~156MB pickle overhead.  The fuzzy-retrieval source shares the
    provider's SymSpell instance and needs no separate flag.
    """
    symspell = GeoSymSpellSource(
        name=symspell_name,
        dictionary_path=paths[0] if paths else None,
        max_edit_distance=2,
        prefix_length=7,
        large_tier=large_tier,
        use_compiled_cache=large_tier,
    )
    for extra_path in paths[1:]:
        symspell.load_additional_dictionary(extra_path)

    fuzzy_retrieval = GeoFuzzyRetrievalSource(
        name=fuzzy_name,
        dictionary_path=None,
        large_tier=large_tier,
    )
    fuzzy_retrieval.share_symspell_from(symspell)
    return symspell, fuzzy_retrieval


class GeoPack:
    """Geo domain pack.

    Provides geo-specific:
    - Candidate sources (exact code, exact name, FTS, fuzzy, symspell)
    - Constraints (type, containment, temporal, membership)
    - Feature schema (GeoFeaturesV1)
    - Scorer and decision policy

    SymSpell indexes are split into two independent lazily-built groups:

    SMALL group (countries, admin1, regions, continents, continental unions):
        Few thousand terms — tiny memory footprint, always built at full params
        (prefix_length=7, max_edit_distance=2). Country typo recall depends only
        on this index.

    LARGE group (admin2, admin3, admin4, admin5, cities):
        ~720k terms — the memory driver. Also built at full params (7, 2) but
        only when a fuzzy query actually needs deep-admin/city matching. Since
        most queries resolve via exact/FTS before fuzzy is reached, and since
        the large tiers are opt-in/not-installed-by-default, this index often
        never builds in practice.

    Both indexes are built lazily and independently per-instance.
    """

    DATAPACK_DIR: Path = Path(__file__).parent / "data"
    GROUP_ENTITY_TYPES: frozenset[str] = frozenset(
        {"geo.organization", "geo.continental_union"}
    )

    # Module IDs that belong to the LARGE tier group.
    _LARGE_TIER_MODULE_IDS: frozenset[str] = frozenset(
        {"geo.admin2", "geo.admin3", "geo.admin4", "geo.admin5", "geo.cities"}
    )

    def __init__(
        self,
        symspell_dict_path: str | None = None,
        symspell_dict_paths: list[str] | None = None,
        symspell_dict_paths_small: list[str] | None = None,
        symspell_dict_paths_large: list[str] | None = None,
        calibrator_path: str | None = None,
        model_path: str | None = None,
    ):
        """Initialize GeoPack.

        SymSpell dictionaries are split into two independently-lazy indexes:

        - SMALL index: countries, admin1, regions, continents, continental unions.
          Loaded from ``symspell_dict_paths_small``. Tiny memory; always at full
          params (prefix_length=7, max_edit_distance=2).

        - LARGE index: admin2-5 and cities. Loaded from
          ``symspell_dict_paths_large``. Built lazily on the first fuzzy query
          that actually needs it; often never built. Also full params (7, 2).

        Legacy parameters (``symspell_dict_path`` / ``symspell_dict_paths``) are
        accepted for backward compat and treated as SMALL-group paths.

        Args:
            symspell_dict_path: Legacy scalar path (treated as SMALL group).
            symspell_dict_paths: Legacy list of paths (treated as SMALL group).
            symspell_dict_paths_small: Paths for the SMALL tier SymSpell index.
            symspell_dict_paths_large: Paths for the LARGE tier SymSpell index.
            calibrator_path: Optional path to a JSON calibrator file.
            model_path: Optional path to a JSON logistic scoring model file.
        """
        # Resolve SMALL-group paths (prefer explicit, fall back to legacy).
        if symspell_dict_paths_small is not None:
            small_paths = symspell_dict_paths_small
        elif symspell_dict_paths is not None:
            small_paths = symspell_dict_paths
        elif symspell_dict_path is not None:
            small_paths = [symspell_dict_path]
        else:
            small_paths = []

        large_paths: list[str] = symspell_dict_paths_large or []

        # SMALL index: full params (7, 2). Country typo recall depends on this.
        small_source, small_fuzzy_retrieval = _build_symspell_pair(
            paths=small_paths,
            symspell_name="geo_symspell",
            fuzzy_name="geo_fuzzy_retrieval",
            large_tier=False,
        )

        # LARGE index: full params (7, 2), built lazily only if large-tier
        # dictionaries are actually provided (admin2-5 / cities).
        large_source: GeoSymSpellSource | None = None
        large_fuzzy_retrieval: GeoFuzzyRetrievalSource | None = None
        if large_paths:
            large_source, large_fuzzy_retrieval = _build_symspell_pair(
                paths=large_paths,
                symspell_name="geo_symspell_large",
                fuzzy_name="geo_fuzzy_retrieval_large",
                large_tier=True,
            )

        sources: list[CandidateSource] = [
            GeoExactCodeSource(),
            GeoExactNameSource(),
            GeoFTSSource(),
            small_source,
            small_fuzzy_retrieval,
        ]
        if large_source is not None:
            sources.append(large_source)
        if large_fuzzy_retrieval is not None:
            sources.append(large_fuzzy_retrieval)
        sources.append(GeoFuzzySource())

        self._sources: list[CandidateSource] = sources

        self._constraints: list[Constraint] = [
            GeoTypeConstraint(),
            GeoContainmentConstraint(),
            GeoTemporalConstraint(),
            GeoMembershipConstraint(),
        ]

        self._feature_extractor: FeatureExtractor = GeoFeatureExtractor()

        artifacts = load_scoring_artifacts(
            model_path=model_path, calibrator_path=calibrator_path
        )
        self._scorer = GeoScorer(model=artifacts.model, calibrator=artifacts.calibrator)

        t = self._scorer.decision_thresholds
        self._decision_policy: DecisionPolicy = GeoDecisionPolicy(
            confidence_threshold=t.confidence_threshold,
            min_gap=t.min_gap,
            exact_code_min_score=t.exact_code_min_score,
        )

        self._routing_hints = RoutingHints(
            type_prefixes=["geo"],
            keywords=[],
            scoring_fn=geo_scoring_fn,
            country_relation_prefixes=frozenset({"country/"}),
            country_scoped_type_prefixes=frozenset({"geo"}),
        )

        self._merge_normalizer: Normalizer = GeoNormalizer()

    @property
    def pack_id(self) -> str:
        return "geo"

    @property
    def group_entity_types(self) -> frozenset[str]:
        return self.GROUP_ENTITY_TYPES

    @property
    def normalization_profile(self) -> NormalizationProfile:
        return GEO_NORMALIZATION_PROFILE

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
    def scorer(self) -> GeoScorer:
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
        return GEO_PIPELINE_CONFIG

    def candidate_ordering_key(self, entity_type: str) -> int | None:
        """Return specificity rank for a geo entity type.

        Lower rank = higher priority (country=0 precedes region=2).
        Returns None for unrecognized entity types.
        """
        return geo_candidate_ordering_key(entity_type)

    def get_source(self, name: str) -> CandidateSource | None:
        """Get a source by name."""
        return next((s for s in self.sources if s.name == name), None)
