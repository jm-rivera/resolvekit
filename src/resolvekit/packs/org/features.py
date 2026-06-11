"""Typed feature schema for org domain pack."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OrgFeaturesV1(BaseModel):
    """Typed feature vector for organization entities.

    Version: org.features.v1

    Key differences from GeoFeaturesV1:
    - Acronym-specific features
    - Parent org context alignment
    - Query classification (is_acronym_like)
    """

    model_config = ConfigDict(frozen=True)

    # Retrieval signals
    exact_code_hit: bool = Field(default=False)
    acronym_hit: bool = Field(default=False)
    acronym_exact: bool = Field(default=False)
    exact_name_hit: bool = Field(default=False)
    fts_bm25_norm: float | None = Field(default=None)
    token_set_sim: float | None = Field(default=None)
    fuzzy_edit_sim: float | None = Field(default=None)

    # ResolutionContext alignment
    parent_org_match: bool | None = Field(default=None)
    country_match: bool | None = Field(default=None)
    type_match: bool | None = Field(default=None)

    # Cross-candidate features (populated during scoring)
    top1_top2_gap: float | None = Field(default=None)

    # Query features
    query_len: int = Field(default=0)
    query_all_caps: bool = Field(default=False)
    query_is_acronym_like: bool = Field(default=False)

    # Candidate priors
    candidate_prominence: float | None = Field(default=None)

    @property
    def schema_version(self) -> str:
        return "org.features.v1"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for scoring."""
        return self.model_dump()
