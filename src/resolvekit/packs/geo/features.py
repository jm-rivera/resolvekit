"""Typed feature schema for geo domain pack."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GeoFeaturesV1(BaseModel):
    """Typed feature vector for geo entities.

    Version: geo.features.v1

    All features have explicit types and defaults.
    This prevents dict[str, Any] feature drift.
    """

    model_config = ConfigDict(frozen=True)

    # Retrieval signals
    exact_code_hit: bool = Field(default=False)
    exact_name_hit: bool = Field(default=False)
    fts_bm25_norm: float | None = Field(default=None)
    fts_bm25_raw: float | None = Field(default=None)
    symspell_edit_norm: float | None = Field(default=None)
    fuzzy_edit_sim: float | None = Field(default=None)
    fuzzy_token_sim: float | None = Field(default=None)
    retrieval_rank_inv: float | None = Field(default=None)
    fts_name_overlap: float | None = Field(default=None)

    # Query features
    query_len: int = Field(default=0)
    query_has_digits: bool = Field(default=False)
    query_is_upper: bool = Field(default=False)

    # Constraint features
    containment_pass: bool | None = Field(default=None)
    type_pass: bool | None = Field(default=None)
    temporal_pass: bool | None = Field(default=None)
    membership_pass: bool | None = Field(default=None)

    # Candidate features
    hierarchy_rank: float | None = Field(default=None)
    candidate_prominence: float | None = Field(default=None)

    @property
    def schema_version(self) -> str:
        return "geo.features.v1"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for scoring."""
        return self.model_dump()
