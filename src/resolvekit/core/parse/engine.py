"""Parse engine: orchestrates detect → link → arbitrate → assemble.

``parse_one`` and ``parse_bulk_rows`` are the internal entry points called
by the public ``Resolver.parse()`` and ``Resolver.parse_bulk()`` methods.

Cost model (``parse_one``)
--------------------------
Per document: ``O(spans x packs x passes x pipeline)``; each span is a
full ``PipelineRunner._run`` call.

With per-span context interning (step 2a in ``link_span``), **repeated
surfaces of the same entity-type within one ``parse()`` call hit the query
cache**; distinct surfaces and cross-call repeats still miss (the cache is
per-Resolver, keyed on ``id(context)``).

When ``to=`` is set, add **one ``get_entity`` hydration per RESOLVED span**
(SQLite point read; not currently batched).

**One Resolver per thread** — do not share a Resolver across threads (the
query cache is not thread-safe).

No quadratic cost in overlap/arbitration (greedy sweep is ``O(m log m)``).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resolvekit.core.model.query import ResolutionContext
    from resolvekit.core.parse.link import ParseBackend
    from resolvekit.core.parse.result import DroppedSpan, ParsedEntity


def parse_one(
    raw: str,
    *,
    backend: ParseBackend,
    domain: str | list[str] | None,
    context: ResolutionContext | None,
    confidence_threshold: float | None,
    include_nil: bool,
    row_idx: int | None = None,
) -> tuple[list[ParsedEntity], list[DroppedSpan]]:
    """Detect, link, arbitrate, and assemble entities for one text.

    Flow:
    1. Route packs (pin via *domain* or default to all available).
    2. For each routed pack, get or build its ``PackAutomaton`` (cached).
    3. Call ``automaton.find(raw)`` → ``list[_RawHit]``.
    4. Create a per-call ``ctx_cache`` for context interning.
    5. ``link_span`` each hit → ``_LinkedSpan | DroppedSpan``.
    6. Split linked vs. dropped spans.
    7. ``arbitrate_cross_pack`` over linked spans.
    8. Assemble ``ParsedEntity`` objects.
    9. Sort by ``start`` offset; return ``(entities, dropped)``.

    Cost model: see module docstring.

    Args:
        raw: Free-text input string.
        backend: Resolver seam implementing ``ParseBackend``.
        domain: Pack(s) to route to; ``None`` routes to all available.
        context: Caller-supplied resolution hints (country, as_of, etc.).
        confidence_threshold: Override minimum calibrated confidence.
            ``None`` uses each pack's built-in threshold.
        include_nil: When True, below-threshold detected spans are included
            in ``entities`` with ``status=NO_MATCH``; when False they go
            to ``dropped_spans``.
        row_idx: Row index tag for ``parse_bulk_rows``; ``None`` for
            single-text ``parse()`` calls.

    Returns:
        ``(entities, dropped_spans)`` tuple.  ``entities`` is sorted by
        ``start`` offset; ``dropped_spans`` is in detection order.
    """
    from resolvekit.core.parse.automaton import (
        _SMALL_ENTITY_TYPE_PREFIXES,
        _is_small_only_entity_types,
        build_or_get_automaton,
    )
    from resolvekit.core.parse.detect import arbitrate_cross_pack
    from resolvekit.core.parse.link import link_span
    from resolvekit.core.parse.result import DroppedSpan, ParsedEntity

    if not raw or not raw.strip():
        return [], []

    # Step 1: route packs.
    target_packs = _resolve_target_packs(domain, backend)

    # Step 4: context intern cache (scoped to this call, not shared across rows).
    ctx_cache: dict = {}

    # Steps 2-3: detect per pack.
    all_hits_raw = []
    for pack_id in target_packs:
        profile = _pack_profile(pack_id, backend)
        try:
            store = backend.store_for(pack_id)
        except (ValueError, AttributeError):
            continue

        version = backend.data_version_summary() or ""
        entity_types_hint = context.entity_types if context else None
        is_small = _is_small_only_entity_types(entity_types_hint)
        small_or_full = "small" if is_small else "full"
        small_prefixes = _SMALL_ENTITY_TYPE_PREFIXES if is_small else None

        automaton = build_or_get_automaton(
            store=store,
            profile=profile,
            pack_id=pack_id,
            small_or_full=small_or_full,
            small_prefixes=small_prefixes,
            data_version_summary=version,
        )
        hits = automaton.find(raw)
        all_hits_raw.extend(hits)

    # Step 5: link each hit.
    linked_spans = []
    dropped_spans: list[DroppedSpan] = []

    for hit in all_hits_raw:
        outcome = link_span(
            hit,
            backend=backend,
            base_context=context,
            confidence_threshold=confidence_threshold,
            ctx_cache=ctx_cache,
            include_nil=include_nil,
        )
        if isinstance(outcome, DroppedSpan):
            dropped_spans.append(outcome)
        else:
            linked_spans.append(outcome)

    # Step 7: cross-pack arbitration.
    arbitrated = arbitrate_cross_pack(linked_spans)

    # Step 8: assemble ParsedEntity objects.
    entities: list[ParsedEntity] = []
    for span in arbitrated:
        entities.append(
            ParsedEntity(
                surface=span.surface,
                start=span.start,
                end=span.end,
                entity_id=span.entity_id,
                entity_type=span.entity_type,
                pack_id=span.pack_id,
                status=span.status,
                confidence=span.confidence,
                resolution=span.result,
                row_idx=row_idx,
                output=None,  # output pivot applied by caller if needed
            )
        )

    # Step 9: sort by start offset.
    entities.sort(key=lambda e: e.start)

    return entities, dropped_spans


def parse_bulk_rows(
    values: Sequence[str],
    *,
    backend: ParseBackend,
    domain: str | list[str] | None,
    context: ResolutionContext | None,
    confidence_threshold: float | None,
    include_nil: bool,
) -> tuple[list[ParsedEntity], list[DroppedSpan]]:
    """``parse_one`` per row, tagging ``row_idx``; results concatenated.

    Each row gets a fresh ``ctx_cache`` (context interning is scoped to one
    document; it never crosses rows).  Single-threaded: the ``id(context)``
    query cache in ``cache.py`` is not thread-safe, and one Resolver must
    not be shared across threads.

    Cost model: per row, ``O(spans x packs x passes x pipeline)``.  See
    ``parse_one`` docstring for the full cost model including interning
    savings and ``to=`` hydration cost.

    Args:
        values: Sequence of raw text values (one per row).
        backend: Resolver seam implementing ``ParseBackend``.
        domain: Pack(s) to route to; ``None`` routes to all available.
        context: Caller-supplied resolution hints shared across all rows.
        confidence_threshold: Override minimum calibrated confidence.
        include_nil: Surface detected-but-below-threshold spans as NIL
            entities (``status=NO_MATCH``) when True.

    Returns:
        ``(entities, dropped_spans)`` with all rows concatenated.
        Each entity carries its ``row_idx`` for identification.
    """
    all_entities: list = []
    all_dropped: list = []

    for i, raw in enumerate(values):
        entities, dropped = parse_one(
            raw,
            backend=backend,
            domain=domain,
            context=context,
            confidence_threshold=confidence_threshold,
            include_nil=include_nil,
            row_idx=i,
        )
        all_entities.extend(entities)
        all_dropped.extend(dropped)

    return all_entities, all_dropped


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_target_packs(
    domain: str | list[str] | None,
    backend: ParseBackend,
) -> list[str]:
    """Return the ordered list of pack IDs to detect over.

    When *domain* is None, defaults to all available packs (sorted for
    determinism).  A single string or list is intersected with available
    packs so callers can pass unknown domains without errors (silently
    skipped — e.g. requesting "org" on a geo-only resolver).
    """
    available = backend.available_packs
    if domain is None:
        return sorted(available)
    requested = [domain] if isinstance(domain, str) else list(domain)
    # Preserve caller-supplied order; skip unknown packs silently.
    return [p for p in requested if p in available]


def _pack_profile(
    pack_id: str,
    backend: ParseBackend,
):
    """Return the normalization profile for *pack_id*.

    Falls back to the geo profile when the pack has no registered normalizer
    (e.g. a custom pack loaded without a profile mapping).
    """
    from resolvekit.packs.geo.pack import GEO_NORMALIZATION_PROFILE

    normalizers = backend.pack_normalizers
    normalizer = normalizers.get(pack_id)
    if normalizer is not None and hasattr(normalizer, "_profile"):
        return normalizer._profile
    # No registered normalizer: use the pack's own profile constant when known.
    if pack_id == "geo":
        return GEO_NORMALIZATION_PROFILE
    if pack_id == "org":
        from resolvekit.packs.org.pack import ORG_NORMALIZATION_PROFILE

        return ORG_NORMALIZATION_PROFILE
    # Unknown pack: fall back to geo profile as a safe default.
    return GEO_NORMALIZATION_PROFILE


__all__ = [
    "parse_bulk_rows",
    "parse_one",
]
