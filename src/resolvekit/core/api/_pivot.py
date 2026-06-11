"""Scalar pivot validation and application helpers for relation-based queries.

``validate_scalar_pivot`` and ``pivot_entities`` provide the ``to=`` validation
and apply logic used by ``Resolver.within`` (and available for future callers).
The equivalent inline logic in ``related()`` is intentionally left untouched —
the duplication is load-bearing for stability.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from resolvekit.core.errors import UnknownCodeSystemError
from resolvekit.core.model.entity_attributes import KNOWN_PIVOTS
from resolvekit.core.model.name_grammar import parse_name_grammar

if TYPE_CHECKING:
    from resolvekit.core.model import EntityRecord

# Non-scalar KNOWN_PIVOTS that return a list rather than a single string.
_NON_SCALAR_PIVOTS: frozenset[str] = frozenset({"aliases"})


def validate_scalar_pivot(
    to: str,
    *,
    available_code_systems: frozenset[str],
) -> None:
    """Raise ``UnknownCodeSystemError`` if *to* is not a scalar pivot.

    Mirrors the validation in ``Resolver.related()``: rejects non-scalar
    KNOWN_PIVOTS (e.g. ``"aliases"``), validates
    ``name:<...>`` grammar, and rejects unknown code systems.

    Args:
        to: The requested pivot target (e.g. ``"iso3"``, ``"name:fr"``).
        available_code_systems: Code systems declared by the loaded packs.

    Raises:
        UnknownCodeSystemError: *to* is non-scalar, malformed, or unknown.
    """
    scalar_pivots = KNOWN_PIVOTS - _NON_SCALAR_PIVOTS
    if to in _NON_SCALAR_PIVOTS:
        available = sorted(available_code_systems | scalar_pivots)
        raise UnknownCodeSystemError(
            to,
            available,
            hint=f"{to!r} returns a list, not a scalar; available scalars: {available}",
        )
    # name / name:<lang|kind>[:<script>] tokens are scalar; validate grammar.
    _is_name_token = to == "name" or to.startswith("name:")
    if _is_name_token:
        parse_name_grammar(to)  # raises UnknownOutputError on bad grammar
    elif to not in scalar_pivots and to not in available_code_systems:
        available = sorted(available_code_systems | scalar_pivots)
        raise UnknownCodeSystemError(to, available)


def pivot_entities(
    entities: list[EntityRecord],
    to: str,
) -> list[str | None]:
    """Apply a scalar *to* pivot to each entity, returning ``None`` where absent.

    Args:
        entities: Hydrated entity records to pivot.
        to: Scalar pivot target (must already be validated by
            :func:`validate_scalar_pivot`).

    Returns:
        ``list[str | None]`` — one entry per input entity; ``None`` when the
        entity lacks the requested code or attribute.
    """
    return cast(
        "list[str | None]",
        [entity.to(to) for entity in entities],
    )
