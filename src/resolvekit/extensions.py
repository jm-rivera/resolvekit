"""Public re-export module for Tier 3 custom-pack authors.

Import from here rather than from internal engine/store modules.
All names in ``__all__`` are covered by the v1 stability guarantee.
"""

from resolvekit.core.engine.interfaces import (
    CandidateSource,
    Constraint,
    FeatureExtractor,
    Scorer,
)
from resolvekit.core.explain.sink import TraceSink
from resolvekit.core.model import FeaturesV1, FeatureVector
from resolvekit.core.model.candidate import ConstraintRole
from resolvekit.core.model.entity import EntityRecord
from resolvekit.core.model.result import MatchTier
from resolvekit.core.store.interface import EntityStore

__all__ = [
    "CandidateSource",
    "Constraint",
    "ConstraintRole",
    "EntityRecord",
    "EntityStore",
    "FeatureExtractor",
    "FeatureVector",
    "FeaturesV1",
    "MatchTier",
    "Scorer",
    "TraceSink",
]
