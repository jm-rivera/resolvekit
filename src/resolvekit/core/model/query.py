"""Query and Context models for resolution requests."""

from datetime import date
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NormalizedText(BaseModel):
    """Normalized text with original preserved.

    Value object that holds both the original input text and its
    normalized form for matching.
    """

    model_config = ConfigDict(frozen=True)

    original: str = Field(..., min_length=1, description="Original input text")
    normalized: str = Field(
        ..., min_length=1, description="Normalized text for matching"
    )


class Query(BaseModel):
    """A resolution query.

    Attributes:
        raw_text: The original input text to resolve
        normalized: Normalized form produced by normalization step
        domains: Optional set of domain types to search (e.g., {"geo", "org"})
        query_id: Unique identifier for this query (auto-generated)
    """

    model_config = ConfigDict(frozen=True)

    raw_text: str = Field(..., min_length=1, description="Original input text")
    normalized: NormalizedText = Field(..., description="Normalized text")
    domains: frozenset[str] | None = Field(
        default=None, description="Optional domain types to search"
    )
    query_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique query identifier for tracing",
    )


class ResolutionContext(BaseModel):
    """Domain-agnostic context for resolution.

    Provides hints and constraints that domain packs interpret.
    Keep this small and stable - domain-specific logic belongs in packs.

    Attributes:
        as_of: Point-in-time for temporal validity checks
        entity_types: Entity type hints (e.g., {"geo.country", "geo.state"})
        parent_ids: Parent/container entity hints
        country: ISO 3166-1 country code hint — alpha-2 or alpha-3 (useful for geo + org)
        languages: Preferred languages for name matching
        attributes: Escape hatch for domain-specific attributes (use sparingly)
    """

    model_config = ConfigDict(frozen=True)

    as_of: date | None = Field(default=None, description="Point-in-time for validity")
    entity_types: frozenset[str] | None = Field(
        default=None, description="Entity type hints"
    )
    parent_ids: list[str] | None = Field(
        default=None, description="Parent/container entity hints"
    )
    country: str | None = Field(
        default=None,
        description=(
            "ISO 3166-1 country code hint — alpha-2 (e.g. 'US') or"
            " alpha-3 (e.g. 'USA'). Stored uppercased; length disambiguates the form."
        ),
    )
    languages: list[str] | None = Field(default=None, description="Preferred languages")
    attributes: dict[str, str | int | float | bool] = Field(
        default_factory=dict, description="Domain-specific attributes (escape hatch)"
    )

    @field_validator("entity_types", mode="before")
    @classmethod
    def _reject_bare_string_entity_types(cls, value: Any) -> Any:
        # A plain str is iterable, so frozenset[str] would silently accept it
        # as a set of characters. Force callers to pass a collection.
        if isinstance(value, str):
            raise ValueError(
                "entity_types must be a collection of strings, not a single string"
            )
        return value

    @field_validator("country", mode="before")
    @classmethod
    def _validate_country(cls, value: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, str):
            raise ValueError("country must be a string")
        if not value.isalpha():
            raise ValueError(
                f"country must be an ISO 3166-1 alpha-2 or alpha-3 code"
                f" (two or three letters), got {value!r}"
            )
        if len(value) in (2, 3):
            return value.upper()
        raise ValueError(
            f"country must be an ISO 3166-1 alpha-2 or alpha-3 code"
            f" (two or three letters), got {value!r}"
        )

    def replace(self, **updates: Any) -> "ResolutionContext":
        """Return a new ResolutionContext with the specified fields replaced.

        Runs full validation on *updates* and returns an independent instance
        whose mutable fields are deep-copied from the source.
        """
        data = self.model_dump()
        data.update(updates)
        return type(self).model_validate(data)
