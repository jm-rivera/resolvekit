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
    """Fetch entity and apply an explicit ``to=`` pivot; returns ``None`` on miss."""
    if to is None:
        return entity_id
    entity = resolver._runner.get_entity(entity_id)
    if entity is None:
        return None
    try:
        return dispatch_pivot(entity, to)
    except Exception:
        return None


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
        candidates: Entity IDs to constrain the match to.
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
    if not candidates:
        return None

    candidate_set = set(candidates)
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
