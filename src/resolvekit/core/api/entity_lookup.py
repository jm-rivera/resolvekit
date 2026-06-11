"""``_entity_dispatch`` — entity lookup dispatch shared by ``Resolver.entity``.

Supports three lookup modes (in precedence order):

1. Code-system kwarg dispatch (``iso2=``, ``alpha_2=``, ``dcid=``, etc.)
2. Entity-ID direct lookup (when *text_or_id* contains a ``/``,
   e.g. ``"country/USA"``)
3. Free-text resolution (full pipeline) with entity fetch

Both the code-lookup path and the free-text path raise
:class:`AmbiguousResolutionError` on multiple matches — keeping the policy
identical across all three lookup modes.

The public surface lives at :func:`resolvekit.entity` (convenience layer)
and :meth:`Resolver.entity`; both delegate here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from resolvekit.core.api.code_lookup import _iso_numeric_lookup_value
from resolvekit.core.errors import AmbiguousResolutionError
from resolvekit.core.model import CandidateSummary

if TYPE_CHECKING:
    from resolvekit.core.api.resolver import Resolver
    from resolvekit.core.model import EntityRecord


def _entity_dispatch(
    *,
    resolver: Resolver,
    text_or_id: str | None,
    alpha_2: str | None,
    alpha_3: str | None,
    numeric: str | None,
    iso2: str | None,
    iso3: str | None,
    dcid: str | None,
    domain: str | list[str] | None,
    code_kwargs: dict[str, str],
) -> EntityRecord | None:
    """Core implementation shared with ``Resolver.entity()``."""
    from resolvekit.core.api.loading import _normalize_domain

    # Reject conflicting alias values for the same canonical system before
    # collapsing the kwargs into a single code-system map (otherwise the second
    # write would silently win and a typo'd `entity(alpha_2="US", iso2="GB")`
    # would resolve to "GB" with no warning).
    if alpha_2 is not None and iso2 is not None and alpha_2 != iso2:
        raise ValueError(
            f"entity() received conflicting iso2 aliases: "
            f"alpha_2={alpha_2!r} vs iso2={iso2!r}"
        )
    if alpha_3 is not None and iso3 is not None and alpha_3 != iso3:
        raise ValueError(
            f"entity() received conflicting iso3 aliases: "
            f"alpha_3={alpha_3!r} vs iso3={iso3!r}"
        )

    # Build a flat mapping of (canonical_system, value) from all kwarg paths.
    named_codes: dict[str, str] = {}
    if alpha_2 is not None:
        named_codes["iso2"] = alpha_2
    if alpha_3 is not None:
        named_codes["iso3"] = alpha_3
    if numeric is not None:
        named_codes["iso_numeric"] = numeric
    if iso2 is not None:
        named_codes["iso2"] = iso2
    if iso3 is not None:
        named_codes["iso3"] = iso3
    if dcid is not None:
        named_codes["dcid"] = dcid
    named_codes.update(code_kwargs)

    if len(named_codes) > 1:
        raise ValueError(
            f"entity() accepts one code-system kwarg at a time; "
            f"got {sorted(named_codes)}"
        )

    pack_filter = _normalize_domain(domain)

    if named_codes:
        system, value = next(iter(named_codes.items()))
        # Normalize through the owning pack's code normalizer (same object the
        # builder used) so the query value matches value_norm in the store by
        # construction — one normalized value, one lookup.
        value_norm = resolver._runner.normalize_code_value(
            system, value, pack_filter=pack_filter
        )
        if system == "iso_numeric":
            value_norm = _iso_numeric_lookup_value(value_norm)
        entity_ids = resolver._runner.lookup_code(
            system, value_norm, pack_filter=pack_filter
        )
        if not entity_ids:
            return None
        if len(entity_ids) > 1:
            raise AmbiguousResolutionError(
                candidates=[CandidateSummary(entity_id=eid) for eid in entity_ids]
            )
        return resolver._runner.get_entity(entity_ids[0])

    if text_or_id is None:
        return None

    # Entity-ID direct lookup: contains "/" like "country/USA"
    if "/" in text_or_id:
        return resolver._runner.get_entity(text_or_id)

    # Full free-text resolution.  Raise on AMBIGUOUS for parity with the
    # code-system path — both should signal "we cannot return one entity"
    # rather than swallow the ambiguity into a silent None.
    result = resolver._resolve_inner(
        text_or_id,
        normalized_domain=pack_filter,
        context=None,
        include_entity=True,
        timeout=None,
    )
    if result.is_ambiguous:
        raise AmbiguousResolutionError(candidates=list(result.candidates))
    return result.entity
