"""Pure helpers for EntityRecord attribute access and pivot dispatch.

``dispatch_pivot`` is the single-target pivot primitive for per-call ``to=``
routing (``EntityRecord.to()``, ``resolve(..., to=)``, ``bulk(..., to=)``).
It handles codes, computed properties, and the name grammar
(``name:<lang|kind>[:<script>]``).  ``apply_output`` in ``core.api.output_spec``
layers fallback chains and ``on_missing`` policy on top.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from resolvekit.core.errors import UnknownCodeSystemError
from resolvekit.core.model.name_grammar import apply_name, parse_name_grammar

if TYPE_CHECKING:
    from resolvekit.core.model.entity import EntityRecord

# ---------------------------------------------------------------------------
# Known computed pivot targets
# ---------------------------------------------------------------------------

KNOWN_PIVOTS: frozenset[str] = frozenset(
    {"name", "flag", "continent", "iso2", "iso3", "numeric", "aliases"}
)

# ---------------------------------------------------------------------------
# Flag computation
# ---------------------------------------------------------------------------

_REGIONAL_INDICATOR_BASE = 0x1F1E6  # ord('🇦')
_ASCII_UPPER_BASE = ord("A")


def _flag_from_iso2(iso2: str) -> str:
    """Return the flag emoji for a two-letter ISO 3166-1 alpha-2 code.

    Args:
        iso2: Two-letter ISO 3166-1 alpha-2 country code (e.g. ``"US"``).

    Returns:
        A two-character string of Unicode regional indicator symbols,
        e.g. ``"🇺🇸"`` for ``"US"``.

    Raises:
        ValueError: If ``iso2`` is not exactly two ASCII uppercase letters.
    """
    if len(iso2) != 2 or not iso2.isalpha():
        raise ValueError(f"iso2 must be a two-letter code, got {iso2!r}")
    return "".join(
        chr(_REGIONAL_INDICATOR_BASE + (ord(ch.upper()) - _ASCII_UPPER_BASE))
        for ch in iso2
    )


# ---------------------------------------------------------------------------
# Pivot dispatch — single source of truth
# ---------------------------------------------------------------------------


def dispatch_pivot(
    entity: EntityRecord,
    target: str | type[EntityRecord],
) -> object:
    """Route a single ``to=`` pivot target to the corresponding value.

    Routing order:
    1. ``target is EntityRecord`` → return the entity itself.
    2. ``target in KNOWN_PIVOTS`` → ``getattr(entity, target)``
       (bare ``"name"`` → ``entity.canonical_name``).
    3. ``target.startswith("name:")`` → name-grammar branch via
       ``parse_name_grammar`` + ``apply_name``.  Malformed grammar raises
       ``UnknownOutputError`` (loud — programming error).  A valid token that
       the entity simply lacks returns ``None`` (quiet — per-entity miss).
    4. ``target`` in ``entity.codes_dict`` → that code value.
       Note: a *known-system* miss here raises ``UnknownCodeSystemError``
       because ``dispatch_pivot`` has no ``known_systems`` set to distinguish
       "unknown system" from "entity lacks a valid system".  The spec path
       (``_resolve_target`` in ``output_spec.py``) uses ``codes_dict.get``
       directly and never raises; that asymmetry is intentional and deferred.
    5. ``target`` in ``entity.attributes`` → that attribute value.
    6. Raise ``UnknownCodeSystemError`` with a hint listing available options.

    Args:
        entity: The resolved ``EntityRecord``.
        target: A known pivot name, a code system name, an attribute key,
            a name-grammar token (e.g. ``"name:fr"``),
            or the ``EntityRecord`` type itself.

    Returns:
        The requested value, or the entity itself when ``target is EntityRecord``.

    Raises:
        UnknownOutputError: When ``target`` is a malformed name-grammar token.
        UnknownCodeSystemError: When ``target`` doesn't match any routing branch.
        TypeError: When ``target`` is a list or other unsupported type.
            Hint directs callers to ``rk.to([...])`` or ``default_to=[...]``.
    """
    from resolvekit.core.model.entity import EntityRecord as _EntityRecord

    if target is _EntityRecord:
        return entity

    if isinstance(target, str):
        if target in KNOWN_PIVOTS:
            return getattr(entity, target)

        # Name-grammar branch: "name:<lang|kind>[:<script>]" tokens.
        # parse_name_grammar raises UnknownOutputError on malformed grammar;
        # apply_name returns None when the entity lacks the named variant.
        if target.startswith("name:"):
            parsed = parse_name_grammar(target)
            return apply_name(entity, parsed)

        codes = entity.codes_dict
        if (val := codes.get(target)) is not None:
            return val
        attrs = entity.attributes
        if (val := attrs.get(target)) is not None:
            return val
        hint = (
            f"available: codes={sorted(codes)} "
            f"| attrs={sorted(str(k) for k in attrs)} "
            f"| computed={sorted(KNOWN_PIVOTS)}"
        )
        raise UnknownCodeSystemError(
            target, list(codes) + list(KNOWN_PIVOTS), hint=hint
        )

    if isinstance(target, list):
        err = TypeError(
            "to= takes a single target string; "
            "for a fallback chain like ['iso3', 'name'] "
            "use rk.to([...]) or default_to=[...]"
        )
        setattr(err, "hint", "use rk.to([...]) or default_to=[...] for chains")  # noqa: B010
        raise err

    raise TypeError(
        f"to= must be str, EntityRecord, or None; got {type(target).__name__}"
    )
