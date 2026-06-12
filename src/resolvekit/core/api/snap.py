"""``_snap_dispatch`` — closest-match operator dispatch.

Resolves *query*, then post-filters to entries whose ``entity_id`` is in
*candidates*.  Returns the best match (above ``1 - max_distance``) or
``None``.

The public surface lives at :func:`resolvekit.snap` (convenience layer)
and :meth:`Resolver.snap`; both delegate here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from resolvekit.core.api.output_spec import UNSET, apply_output
from resolvekit.core.model.entity_attributes import dispatch_pivot

if TYPE_CHECKING:
    from resolvekit.core.api.output_spec import OutputSpec
    from resolvekit.core.api.resolver import Resolver
    from resolvekit.core.model import ResolutionContext


def _apply_to(resolver: Resolver, entity_id: str, to: Any) -> Any:
    """Fetch entity and apply an explicit ``to=`` pivot.

    Returns ``None`` when the entity is missing or the entity lacks the
    requested output value.  Raises for programming errors (invalid ``to=``
    type, unknown code system) consistent with :func:`dispatch_pivot`.
    """
    if to is None:
        return entity_id
    entity = resolver._runner.get_entity(entity_id)
    if entity is None:
        return None
    return dispatch_pivot(entity, to)


def _resolve_candidate_to_id(resolver: Resolver, candidate: str) -> str | None:
    """Return the entity_id for *candidate*, resolving free-text labels if needed.

    Strings containing ``"/"`` are treated as entity IDs and returned as-is
    (the caller's filter will discard them if they don't exist in the store).
    Plain strings are resolved via an exact lookup; labels that cannot be
    resolved unambiguously return ``None`` and are silently skipped.
    """
    if "/" in candidate:
        return candidate
    return resolver.resolve_id(candidate, on_ambiguous="null")


def _snap_dispatch(
    *,
    resolver: Resolver,
    query: str,
    candidates: list[str],
    max_distance: float,
    to: Any = UNSET,
    domain: str | list[str] | None,
    context: ResolutionContext | None,
    output_spec: OutputSpec | None = None,
) -> Any:
    """Core implementation shared by ``Resolver.snap()`` and ``resolvekit.snap()``.

    Resolution rules (high → low precedence):

    - ``to is UNSET`` and *output_spec* is set → fetch entity, apply the
      compiled output chain via :func:`apply_output` (``scalar=True``).
    - ``to is UNSET`` and no spec → return ``best.entity_id`` (legacy behavior).
    - Explicit ``to`` value (including ``None``) → today's ``dispatch_pivot``
      path; ``None`` returns ``entity_id``.

    Args:
        resolver: The resolver instance to search and fetch entities from.
        query: The query string to match.
        candidates: Entity IDs or free-text labels to constrain the match to.
            Labels are resolved to entity IDs; unresolvable labels are skipped.
        max_distance: Confidence floor; below this threshold returns ``None``.
        to: Explicit pivot target.  Defaults to ``UNSET``; callers that pass
            ``None`` explicitly force entity_id (pre-spec behavior).
        domain: Optional domain filter.
        context: Optional resolution context.
        output_spec: Compiled ``OutputSpec`` from the resolver's default
            output configuration.  Ignored when *to* is not ``UNSET``.

    Returns:
        The closest matching candidate, pivoted according to the active
        output path, or ``None`` when below threshold or entity is missing.
    """
    # Resolve free-text labels to entity IDs; entity IDs pass through unchanged.
    # Unresolvable labels are silently dropped; an empty result returns None early.
    candidate_set: set[str] = {
        eid
        for c in candidates
        if (eid := _resolve_candidate_to_id(resolver, c)) is not None
    }
    if not candidate_set:
        return None

    min_confidence = 1.0 - max_distance

    # Use the search path to get ranked candidates without a hard decision cut-off.
    all_candidates = resolver._search_internal(
        query,
        top_k=len(candidates) + 10,
        domain=domain,
        context=context,
    )

    best = None
    best_confidence: float = -1.0
    for c in all_candidates:
        if c.entity_id not in candidate_set:
            continue
        conf = c.confidence if c.confidence is not None else 0.0
        if conf < min_confidence:
            continue
        if conf > best_confidence:
            best = c
            best_confidence = conf

    if best is None:
        return None

    # Explicit to= (including None) → dispatch_pivot path.
    if to is not UNSET:
        return _apply_to(resolver, best.entity_id, to)

    # to omitted + spec active → apply compiled output chain.
    if output_spec is not None:
        entity = resolver._runner.get_entity(best.entity_id)
        if entity is None:
            return None
        return apply_output(entity, output_spec, scalar=True)

    # to omitted + no spec → entity_id (legacy behavior).
    return best.entity_id
