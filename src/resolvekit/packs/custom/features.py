"""Typed feature schema for the custom domain pack."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CustomFeaturesV1(BaseModel):
    """Typed feature vector for custom entities.

    Version: custom.features.v1

    Signals mirror those available from the four custom sources:
    - exact_code_hit   (CustomExactCodeSource)
    - exact_name_hit   (CustomExactNameSource)
    - fts_bm25_norm    (CustomFTSSource)
    - fuzzy_edit_sim / fuzzy_token_sim  (CustomFuzzySource)
    """

    model_config = ConfigDict(frozen=True)

    # Retrieval signals
    exact_code_hit: bool = Field(default=False)
    exact_name_hit: bool = Field(default=False)
    fts_bm25_norm: float | None = Field(default=None)
    fuzzy_edit_sim: float | None = Field(default=None)
    fuzzy_token_sim: float | None = Field(default=None)

    # Query features
    query_len: int = Field(default=0)

    @property
    def schema_version(self) -> str:
        return "custom.features.v1"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for scoring."""
        return self.model_dump()
