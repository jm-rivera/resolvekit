"""Span linking: turn a detected ``_RawHit`` into a ``_LinkedSpan`` or ``DroppedSpan``.

``link_span`` is the per-span hot path:
1. Derive entity_types from the automaton side-table payload.
2. Build (or intern) a per-span ``ResolutionContext`` that pins the pack
   domain and supplies entity_types so the short-input gate is unlocked.
3. Call ``backend._resolve_one(...)`` — the resolver runs its full pipeline
   and returns a ``ResolutionResult`` with a live ``_explainer`` weakref.
4. Apply the confidence threshold: status ≥ threshold → ``_LinkedSpan``
   (RESOLVED/AMBIGUOUS); below threshold → NIL ``_LinkedSpan``
   (NO_MATCH) when ``include_nil`` is True; otherwise drop.
5. Sentinel or short-input gate rejects → ``DroppedSpan``.

**Context interning:** ``parse_one`` owns a ``ctx_cache`` dict keyed
on ``(frozenset(entity_types), country, tuple(parent_ids), as_of)``.
``link_span`` looks up / inserts there so same-typed spans reuse *one*
``ResolutionContext`` object → stable ``id(ctx)`` → the existing
``id(context)`` query cache in ``cache.py:91`` hits on repeated surfaces
(e.g. "Kenya" x5 in one document).  No change to ``QueryPreparer`` or
``cache.py`` is needed: ``prepare_query`` returns the caller's context
unchanged when it is not None.

**explain() survival:** ``backend._resolve_one`` returns the live
``ResolutionResult`` as produced by ``ResolveFlow.resolve_inner``, which
sets ``result._explainer = weakref.ref(resolver)`` before returning.
``link_span`` stores that result on ``_LinkedSpan.result`` without
copying it, so ``entity.resolution.explain()`` works.

``ParseBackend`` Protocol
-------------------------
A small structural protocol (preferred over ABC — composition) capturing
what link / engine need from a resolver backend. Enables decoupling from
the Resolver facade: only the minimal methods needed by parsing are exposed,
keeping the implementation flexible.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from resolvekit.core.model.query import ResolutionContext
    from resolvekit.core.model.result import ResolutionResult
    from resolvekit.core.parse.automaton import _RawHit
    from resolvekit.core.parse.detect import _LinkedSpan
    from resolvekit.core.parse.result import DroppedSpan
    from resolvekit.core.store.interface import EntityStore
    from resolvekit.core.util.normalization import TextNormalizer


# When True, spans whose resolved entity_type is "geo.continent" or
# "geo.continental_union" are dropped from parse output.  These broad
# geographic groupings are almost never the intended parse mention (e.g.
# "South America" → wikidataId/Q18, type geo.continent).  Flip to False
# if a gold evaluation row requires a continent in the output.
_EXCLUDE_CONTINENTS: bool = True

# Entity types that are excluded when _EXCLUDE_CONTINENTS is True.
_CONTINENT_TYPES: frozenset[str] = frozenset({"geo.continent", "geo.continental_union"})


@runtime_checkable
class ParseBackend(Protocol):
    """Structural protocol for the resolver seam used by parse/link/engine.

    Minimal interface that decouples the parsing engine from the Resolver facade.
    Any object satisfying these methods can be a valid backend.
    """

    def _resolve_one(
        self,
        text: str,
        *,
        context: ResolutionContext | None,
    ) -> ResolutionResult:
        """Resolve *text* and return a ``ResolutionResult`` with ``_explainer`` set.

        This is the linking path; the returned result carries a live
        ``_explainer`` weakref so ``result.explain()`` works on the span.
        Delegates to ``Resolver._resolve_inner`` with ``include_entity=False``
        (the entity can be hydrated later if ``to=`` is set).
        """
        ...

    @property
    def pack_normalizers(self) -> dict[str, TextNormalizer]:
        """Per-pack ``TextNormalizer`` instances keyed by pack ID."""
        ...

    @property
    def available_packs(self) -> frozenset[str]:
        """Set of valid pack IDs this backend has loaded."""
        ...

    def store_for(self, pack_id: str) -> EntityStore:
        """Return the ``EntityStore`` backing the given pack."""
        ...

    def data_version_summary(self) -> str:
        """Opaque data-version string (e.g. ``"2026.06"``), or empty string."""
        ...


# ---------------------------------------------------------------------------
# link_span
# ---------------------------------------------------------------------------


def link_span(  # noqa: PLR0911 (per-gate precision dispatch is naturally multi-exit)
    hit: _RawHit,
    *,
    backend: ParseBackend,
    base_context: ResolutionContext | None,
    confidence_threshold: float | None,
    ctx_cache: dict,
    include_nil: bool,
) -> _LinkedSpan | DroppedSpan:
    """Link one detected span to an entity via the resolution engine.

    Builds a per-span ``ResolutionContext`` (entity_types + pinned domain
    from the hit's payload — unlocks the short-input gate, avoids 2x AutoRouter
    fan-out), calls ``backend._resolve_one(...)``, applies the confidence
    threshold, and returns either a ``_LinkedSpan`` (RESOLVED/AMBIGUOUS or
    NIL when ``include_nil`` is True) or a ``DroppedSpan`` when a precision
    gate rejects the span.

    Args:
        hit: Raw detection from ``PackAutomaton.find()``.
        backend: Resolver seam implementing ``ParseBackend``.
        base_context: Caller-supplied ``context=`` arg; country/as_of/parent_ids
            are preserved; entity_types is overridden by the automaton payload.
        confidence_threshold: Minimum calibrated score for RESOLVED.  ``None``
            uses the pack's built-in threshold (the resolver applies it).
        ctx_cache: Intern map owned by ``parse_one``; keyed on
            ``(frozenset(entity_types), country, tuple(parent_ids), as_of)``.
            Same-typed spans reuse one object → stable ``id(ctx)`` → query-cache
            hits on repeated surfaces within one document.
        include_nil: When False, below-threshold spans return ``DroppedSpan``
            with ``reason="below_threshold"``; when True, they return a
            ``_LinkedSpan`` with ``status=NO_MATCH``.

    Returns:
        ``_LinkedSpan`` on RESOLVED, AMBIGUOUS, or NIL (when ``include_nil``);
        ``DroppedSpan`` on sentinel-block, short-input block, or
        below-threshold when ``include_nil=False``.
    """
    from resolvekit.core.model.result import ResolutionStatus
    from resolvekit.core.parse.detect import _LinkedSpan
    from resolvekit.core.parse.result import DroppedSpan
    from resolvekit.core.util.sentinel import DEFAULT_BLOCKLIST

    def _dropped(reason: str) -> DroppedSpan:
        return DroppedSpan(
            surface=hit.surface,
            start=hit.start,
            end=hit.end,
            pack_id=hit.pack_id,
            reason=reason,
        )

    # Sentinel gate: block hard-coded non-entities.
    if DEFAULT_BLOCKLIST.is_blocked(hit.surface):
        return _dropped("sentinel")

    # Deny-list gate: block multi-language function words and common-noun
    # collisions (e.g., "the", "island").  Casefolded membership check, but
    # all-caps ASCII surfaces (potential codes) skip this gate.
    from resolvekit.core.parse.denylist import is_denied

    if is_denied(hit.surface) and not (hit.surface.isascii() and hit.surface.isupper()):
        return _dropped("deny_list")

    # Case-sensitive code channel: code-shaped patterns (all-caps aliases) are
    # admitted only when the surface is all-uppercase ASCII.  "AND" (Andorra) →
    # admitted; "and" / "And" → code_case_mismatch.  The deny-list owns function
    # words; the code channel owns ISO/org acronyms.
    if hit.code_shaped and not (
        hit.surface.isascii() and hit.surface == hit.surface.upper()
    ):
        return _dropped("code_case_mismatch")

    # Derive entity_types from the hit's automaton side-table payload.
    # entity_ids encode the type as a prefix before '/' (e.g., "country/KEN" →
    # "geo.country").  Look up in the store when available; fall back to prefix
    # extraction.  entity_types unlocks the short-input gate for low-confidence
    # short ISO codes.
    entity_types = _entity_types_from_ids(hit.entity_ids, backend, hit.pack_id)

    # Intern the per-span context so same-typed spans within one parse_one call
    # reuse a single ResolutionContext object, enabling query-cache hits on
    # repeated surfaces (e.g., "Kenya" x5).
    ctx = _intern_context(
        base_context=base_context,
        entity_types=entity_types,
        ctx_cache=ctx_cache,
    )

    # Short-input gate (geo-specific): contexts with entity_types like
    # "geo.country" unlock short ISO codes that would otherwise be rejected.
    if hit.pack_id == "geo":
        from resolvekit.packs.geo.sources._short_input import short_input_blocked

        # Simple NFC+casefold normalization for the gate's punctuation-noise
        # detection; the primary gate is entity_types in context.
        norm_approx = hit.surface.strip().casefold()
        if short_input_blocked(hit.surface, norm_approx, ctx):
            return _dropped("short_input")

    # Resolve via backend (full pipeline; result carries live _explainer weakref).
    result = backend._resolve_one(
        hit.surface,
        context=ctx,
    )

    # Apply confidence_threshold override when supplied by caller.  The resolver
    # applies its built-in threshold; an explicit override enforces a stricter
    # floor (caller's threshold > pack's built-in).
    if (
        confidence_threshold is not None
        and result.confidence is not None
        and result.status == ResolutionStatus.RESOLVED
        and result.confidence < confidence_threshold
    ):
        from resolvekit.core.model.result import ReasonCode, ResolutionResult

        result = ResolutionResult(
            status=ResolutionStatus.NO_MATCH,
            confidence=result.confidence,
            candidates=result.candidates,
            reasons=(ReasonCode.BELOW_CONFIDENCE_THRESHOLD,),
            query_text=result.query_text,
        )
        # Constructor drops PrivateAttr; re-attach None to signal demoted result.
        result._explainer = None  # type: ignore[assignment]  # intentional clear

    # Map result to _LinkedSpan or DroppedSpan.
    if result.status == ResolutionStatus.NO_MATCH:
        if not include_nil:
            return _dropped("below_threshold")
        # NIL span — surfaced only when include_nil=True.
        return _LinkedSpan(
            start=hit.start,
            end=hit.end,
            surface=hit.surface,
            entity_ids=hit.entity_ids,
            pack_id=hit.pack_id,
            result=result,
            status=result.status,
            confidence=result.confidence,
            entity_id=None,
            entity_type=None,
        )

    # RESOLVED or AMBIGUOUS.
    entity_type: str | None = None
    if result.entity_id and result.candidates:
        top = result.candidates[0]
        entity_type = top.entity_type

    # Continent type-scope gate: drop spans resolved to broad geographic
    # groupings (geo.continent, geo.continental_union) — these rarely represent
    # intended parse mentions.  NIL spans exit earlier; non-continent types pass.
    if _EXCLUDE_CONTINENTS and entity_type in _CONTINENT_TYPES:
        return _dropped("continent_excluded")

    return _LinkedSpan(
        start=hit.start,
        end=hit.end,
        surface=hit.surface,
        entity_ids=hit.entity_ids,
        pack_id=hit.pack_id,
        result=result,
        status=result.status,
        confidence=result.confidence,
        entity_id=result.entity_id,
        entity_type=entity_type,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entity_types_from_ids(
    entity_ids: list[str],
    backend: ParseBackend,
    pack_id: str,
) -> frozenset[str]:
    """Derive entity types for a set of entity ids.

    Tries the store first (authoritative).  Falls back to prefix extraction
    from the entity_id scheme (``"geo.country/KEN"`` → ``"geo.country"``;
    ``"country/KEN"`` → ``"geo.country"`` via prefix heuristic for the geo pack)
    when the store lookup is unavailable.

    The entity_types set is used to unlock the short-input gate: passing
    ``entity_types=frozenset({"geo.country"})`` in the context tells the
    geo sources to allow short ISO codes that they would otherwise suppress.
    """
    types: set[str] = set()
    try:
        store = backend.store_for(pack_id)
    except (ValueError, AttributeError):
        store = None

    for eid in entity_ids:
        if store is not None:
            entity = store.get_entity(eid)
            if entity is not None:
                types.add(entity.entity_type)
                continue
        # Fallback: extract type from id prefix.
        # Common schemes: "geo.country/KEN" or "country/KEN" (geo pack).
        if "/" in eid:
            prefix = eid.split("/")[0]
            if "." in prefix:
                types.add(prefix)
            elif pack_id == "geo":
                # geo store uses bare prefixes like "country", "admin1".
                types.add(f"geo.{prefix}")
            elif pack_id == "org":
                types.add(f"org.{prefix}")
            else:
                types.add(f"{pack_id}.{prefix}")

    return frozenset(types)


def _intern_context(
    *,
    base_context: ResolutionContext | None,
    entity_types: frozenset[str],
    ctx_cache: dict,
) -> ResolutionContext:
    """Return an interned ``ResolutionContext`` for the given entity_types.

    Looks up or inserts into *ctx_cache* so that same-typed spans within one
    ``parse_one`` call reuse a single context object.  Stable ``id(ctx)``
    → the existing ``id(context)`` query cache in ``cache.py`` hits on
    repeated raw surfaces (e.g. "Kenya" x5 in one document).

    The cache key is ``(entity_types, country, tuple(parent_ids), as_of)``
    so that different base_context fields produce distinct entries.

    Args:
        base_context: Caller's context hint (country/as_of/parent_ids
            preserved; entity_types overridden).
        entity_types: Type hints derived from the automaton payload.
        ctx_cache: Mutable dict owned by the calling ``parse_one`` frame.

    Returns:
        A ``ResolutionContext`` with ``entity_types`` set and all other
        fields from *base_context* (or defaults when None).
    """
    from resolvekit.core.model.query import ResolutionContext

    country: str | None = None
    parent_ids: tuple[str, ...] = ()
    as_of = None

    if base_context is not None:
        country = base_context.country
        parent_ids = tuple(base_context.parent_ids or ())
        as_of = base_context.as_of

    key = (entity_types, country, parent_ids, as_of)
    if key not in ctx_cache:
        if base_context is not None:
            ctx = base_context.replace(entity_types=entity_types)
        else:
            ctx = ResolutionContext(entity_types=entity_types)
        ctx_cache[key] = ctx

    return ctx_cache[key]  # type: ignore[return-value]


__all__ = [
    "ParseBackend",
    "link_span",
]
