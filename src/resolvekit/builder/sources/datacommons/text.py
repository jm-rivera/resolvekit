"""String normalization helpers shared by Data Commons domain profiles."""

from __future__ import annotations


def to_prefixed_entity_type(
    raw_entity_type: str,
    *,
    prefix: str,
    fallback: str = "other",
) -> str:
    """Convert a source type name into ``<prefix>.<snake_case>``."""
    cleaned = raw_entity_type.strip().replace("/", "_")
    out: list[str] = []
    for index, char in enumerate(cleaned):
        if char.isupper() and index > 0 and cleaned[index - 1].islower():
            out.append("_")
        out.append(char.lower())
    snake = "".join(out)
    return f"{prefix}.{snake or fallback}"
