"""Context coercion helper for the public resolution API.

Accepts ``dict | ResolutionContext | None`` at every public surface and
normalises to a validated ``ResolutionContext | None``.  Country *names* are
resolved to ISO alpha-2 codes via the caller's resolver so that ``ResolutionContext``
itself stays a strict ISO-typed value object.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from resolvekit.core.model.query import ResolutionContext

if TYPE_CHECKING:
    from resolvekit.core.api.resolver import Resolver

# The set of valid dict keys, derived from ResolutionContext field names so it
# stays in sync if the model ever gains or loses a field.
_VALID_CONTEXT_KEYS: frozenset[str] = frozenset(ResolutionContext.model_fields)

# Sorted list kept for deterministic error messages.
_VALID_CONTEXT_KEYS_SORTED: list[str] = sorted(_VALID_CONTEXT_KEYS)

# A 2- or 3-letter uppercase alphabetic string is treated as an ISO code and
# passed directly through the ResolutionContext validator without name lookup.
_ISO_CODE_LENGTHS = frozenset({2, 3})


def _looks_like_iso_code(value: str) -> bool:
    return (
        isinstance(value, str) and len(value) in _ISO_CODE_LENGTHS and value.isalpha()
    )


def _iso2_or_id_tail(entity_id: str, resolver: Resolver) -> str | None:
    """Return *entity_id*'s ISO alpha-2 code, falling back to its id tail.

    Looks the entity up to read its ``iso2``; if that's missing, strips the
    prefix (``"country/GEO"`` → ``"GEO"``).  Returns ``None`` when neither
    yields a usable code.
    """
    entity = resolver._runner.get_entity(entity_id)
    if entity is not None:
        iso2 = getattr(entity, "iso2", None)
        if iso2:
            return iso2
    code = entity_id.split("/", 1)[-1]
    return code if _looks_like_iso_code(code) else None


def _resolve_country_name(name: str, resolver: Resolver) -> str:
    """Resolve a country name to an ISO alpha-2 code via *resolver*'s country tier.

    Uses ``entity_types={'geo.country'}`` to restrict lookup to the country
    tier, so "Georgia" resolves to the country GEO, not the US state.

    Raises:
        ValueError: When the name is unresolvable or ambiguous (with verbatim
            messages from the Canonical specs).
    """
    result = resolver.resolve(
        name,
        to=None,
        domain=None,
        context=ResolutionContext(entity_types=frozenset({"geo.country"})),
    )

    unresolvable = ValueError(
        f"cannot resolve country name {name!r} to an ISO code; "
        "pass an ISO alpha-2/alpha-3 code"
    )

    if result.is_resolved:
        if result.entity_id is not None:
            # Prefer the already-hydrated entity's iso2 to skip a store read.
            iso2 = getattr(result.entity, "iso2", None) if result.entity else None
            code = iso2 or _iso2_or_id_tail(result.entity_id, resolver)
            if code:
                return code
        raise unresolvable

    if result.is_ambiguous and result.candidates:
        codes = [
            _iso2_or_id_tail(c.entity_id, resolver) or c.entity_id.split("/", 1)[-1]
            for c in result.candidates[:2]
        ]
        if len(codes) >= 2:
            raise ValueError(
                f"cannot resolve country name {name!r} — ambiguous "
                f"(did you mean {codes[0]!r} or {codes[1]!r}?); pass an ISO code"
            )

    raise unresolvable


def coerce_context(
    value: ResolutionContext | dict[str, Any] | None,
    *,
    resolver: Resolver,
) -> ResolutionContext | None:
    """Coerce a dict | ResolutionContext into a validated ResolutionContext.

    Empty dict ≡ None. Unknown keys raise UnknownContextKeyError listing
    valid keys. A dict-form ``country`` name (e.g. "France") is resolved to
    its ISO alpha-2 via *resolver*'s country tier; an unresolvable or
    ambiguous name raises ValueError naming the input.

    Args:
        value: The context to coerce.  Accepts a ``ResolutionContext``, a
            plain ``dict``, or ``None``.

            Dict shorthand keys: ``country`` (ISO alpha-2/alpha-3 or a country
            name like ``"France"``), ``entity_types``, ``parent_ids``,
            ``languages``, ``attributes`` (pack-specific escape hatch), and
            ``as_of``. An empty dict is treated as no context. Unknown keys raise
            ``UnknownContextKeyError`` listing the valid keys.
        resolver: A live :class:`Resolver` instance used to resolve country
            names to ISO codes.  Not consulted for pure-key-validation.

    Returns:
        A validated :class:`ResolutionContext`, or ``None`` when *value* is
        ``None`` or an empty ``dict``.

    Raises:
        UnknownContextKeyError: When *value* contains keys not in
            ``ResolutionContext.model_fields``.
        ValueError: When a dict-form ``country`` value cannot be resolved to
            an ISO code (unresolvable or ambiguous name).
    """
    from resolvekit.core.errors import UnknownContextKeyError

    if value is None:
        return None
    if isinstance(value, ResolutionContext):
        return value

    # Dict path.
    if not isinstance(value, dict):
        raise TypeError(
            f"context must be a ResolutionContext, dict, or None; "
            f"got {type(value).__name__!r}"
        )

    if not value:
        return None

    # Key validation — pure dict-key check, no store access needed.
    unknown = sorted(set(value) - _VALID_CONTEXT_KEYS)
    if unknown:
        raise UnknownContextKeyError(unknown, _VALID_CONTEXT_KEYS_SORTED)

    # Country-name coercion — only when the value looks like a name, not a code.
    coerced = dict(value)
    raw_country = coerced.get("country")
    if isinstance(raw_country, str) and not _looks_like_iso_code(raw_country):
        coerced["country"] = _resolve_country_name(raw_country, resolver)

    return ResolutionContext.model_validate(coerced)
