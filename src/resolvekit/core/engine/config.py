"""Pipeline configuration models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StopCondition(BaseModel):
    """Stop condition for early pipeline exit.

    Attributes:
        name: Condition name for tracing
        source_name: Only trigger after this source (generation phase only)
        min_candidates: Minimum candidate count to trigger
        max_candidates: Maximum candidate count to trigger
        min_confidence: Minimum confidence to trigger (raw score in generation,
                        calibrated score in post_scoring)
        phase: When to evaluate - "generation" (during source generation) or
               "post_scoring" (after scoring, uses calibrated scores)
    """

    model_config = ConfigDict(frozen=True)

    name: str
    source_name: str | None = None
    min_candidates: int | None = None
    max_candidates: int | None = None
    min_confidence: float | None = None
    phase: Literal["generation", "post_scoring"] = "post_scoring"


class PipelineConfig(BaseModel):
    """Declarative pipeline config (minimal scaffold)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    stop_conditions: list[StopCondition] = Field(default_factory=list)


DEFAULT_PACK_PIPELINE_CONFIG = PipelineConfig()
# Baseline pack pipeline config with no auto-resolve rules.
#
# Post-scoring stop conditions bypass the decision policy, so a global
# ``min_confidence`` cutoff would silently resolve queries the policy would
# otherwise keep ambiguous (two candidates both above the threshold with no
# gap). Packs that need early-exit should declare their own stop condition
# with explicit gap/ambiguity handling.
