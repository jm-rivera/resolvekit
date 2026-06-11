"""Base model for v1 feature vectors used by custom-pack scorers."""

from pydantic import BaseModel, ConfigDict


class FeaturesV1(BaseModel):
    """Stable Pydantic base that third-party scorers pin against.

    Pack authors extend this with their own domain-specific fields.
    The model is frozen and forbids extra keys so that changes to the
    feature schema are explicit and versioned.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
