"""Parse-output pivot helpers.

``coerce_to_str_list`` and ``apply_to_pivot`` provide entity-hydration
logic that is unit-testable without constructing a full ``Resolver``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from resolvekit.core.engine.interfaces import ResolverBackend
    from resolvekit.core.model import EntityRecord
    from resolvekit.core.parse.result import ParsedEntity


def coerce_to_str_list(values: Any) -> list[str]:
    """Coerce a sequence of values to ``list[str]`` for ``parse_bulk_rows``.

    None and NaN-like values become empty strings so the engine skips them
    (empty/whitespace rows produce zero entities in ``parse_one``).

    Args:
        values: Any iterable whose elements will be coerced to strings.

    Returns:
        List of strings, one per input element.
    """
    result: list[str] = []
    for v in values:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            result.append("")
        else:
            result.append(str(v))
    return result


def apply_to_pivot(
    entities: list[ParsedEntity],
    to: str | list[str] | None,
    *,
    runner: ResolverBackend,
    code_systems: frozenset[str],
) -> list[ParsedEntity]:
    """Apply a ``to=`` output pivot to each RESOLVED entity in *entities*.

    Hydrates the entity (one ``get_entity`` per resolved span) and applies
    the compiled ``OutputSpec``.  NIL spans (``status != RESOLVED``) get
    ``output=None`` regardless.  When ``to`` is ``None``, returns *entities*
    unchanged.

    The bulk-fetch path uses ``runner.store_for_domain``; the ``except
    (ValueError, AttributeError)`` fallback handles packs where the store
    seam is unavailable and falls back to per-entity ``runner.get_entity``.

    Args:
        entities: List of ``ParsedEntity`` objects from the engine.
        to: Raw output spec (e.g. ``"iso3"``), or ``None`` for no pivot.
        runner: ``ResolverBackend`` supplying ``store_for_domain`` /
            ``get_entity``.
        code_systems: Frozenset of code systems known to the resolver scope,
            used to validate the output spec.

    Returns:
        Same list with ``output`` field populated via ``dataclasses.replace``.
    """
    if to is None:
        return entities

    import dataclasses

    from resolvekit.core.api.output_spec import apply_output, compile_output_spec
    from resolvekit.core.model.result import ResolutionStatus

    spec = compile_output_spec(to, "null", known_systems=code_systems)

    # Collect all resolved entity_ids that need hydration, keyed by pack_id.
    ids_by_pack: dict[str, list[str]] = {}
    for e in entities:
        if e.status == ResolutionStatus.RESOLVED and e.entity_id is not None:
            pack = e.pack_id or ""
            ids_by_pack.setdefault(pack, []).append(e.entity_id)

    # Bulk-fetch per pack using the public store_for_domain seam.
    entity_map: dict[str, EntityRecord] = {}
    for pack, eids in ids_by_pack.items():
        try:
            store = runner.store_for_domain(pack)
            entity_map.update(store.bulk_get_entities(eids))
        except (ValueError, AttributeError):
            # Pack not found via store_for_domain — fall back per-entity.
            for eid in eids:
                rec = runner.get_entity(eid)
                if rec is not None:
                    entity_map[eid] = rec

    result: list[ParsedEntity] = []
    for e in entities:
        if e.status != ResolutionStatus.RESOLVED or e.entity_id is None:
            result.append(e)
            continue
        entity_record = entity_map.get(e.entity_id)
        if entity_record is None:
            result.append(e)
            continue
        output_val = apply_output(entity_record, spec, scalar=True)
        result.append(dataclasses.replace(e, output=output_val))
    return result
