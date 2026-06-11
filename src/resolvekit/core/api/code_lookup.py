"""CodeLookup — code-shape detection and code-input short-circuit collaborator.

Owns ``looks_like_code``, the code-system priority ordering, and the
``resolve_or_lookup`` entry point.  Depends on the ``ResolverBackend``
protocol (not the concrete ``Resolver`` facade), so it is circular-import-free
and protocol-testable in isolation.
"""

from __future__ import annotations

import re
import weakref
from collections.abc import Callable
from typing import TYPE_CHECKING

from resolvekit.core.api.loading import _normalize_domain
from resolvekit.core.model import (
    CandidateSummary,
    ReasonCode,
    ResolutionContext,
    ResolutionResult,
    ResolutionStatus,
)

if TYPE_CHECKING:
    from resolvekit.core.engine.interfaces import ResolverBackend
    from resolvekit.core.explain.protocol import Explainer
    from resolvekit.core.model import EntityRecord

# ---------------------------------------------------------------------------
# Code-shape detection constants
# ---------------------------------------------------------------------------

# Priority order for auto-detect: most-specific first.
_CODE_SYSTEM_PRIORITY: list[str] = [
    "iso3",
    "iso2",
    "numeric",
    "dcid",
    "wikidata",
]

# Patterns that indicate a value is probably a code rather than free text.
# Case-insensitive for alpha codes: "uk", "UK", "Uk" all route to code lookup,
# which casefolds before querying. Inputs like "is" → Iceland are accepted by
# design — see ``looks_like_code`` for the disambiguation guidance.
_CODE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^[A-Za-z]{2,3}$"),  # iso2, iso3
    re.compile(r"^[0-9]{3}$"),  # numeric
    re.compile(r"^[a-z]+/[A-Za-z0-9_-]+$"),  # dcid-style
]


def looks_like_code(value: str) -> bool:
    """Return True if *value* matches a known code-shape pattern.

    Alpha codes are matched case-insensitively, so ``"uk"`` and ``"UK"`` both
    route to the code-lookup path. A handful of 2-letter ISO codes collide
    with common English words (``"is"`` → Iceland, ``"in"`` → India,
    ``"it"`` → Italy); callers who need to force name resolution on such
    inputs should pass ``from_system="name"`` or constrain ``domain``.
    """
    return any(p.fullmatch(value) for p in _CODE_PATTERNS)


class CodeLookup:
    """Owns code-shape detection and the resolve-or-lookup short-circuit.

    Constructed once in ``Resolver.__init__`` and reused across all calls.
    Depends on ``ResolverBackend`` (protocol) and a per-call callable that
    falls through to full name resolution when no code hit is found.
    """

    def __init__(self, *, runner: ResolverBackend) -> None:
        self._runner = runner

    def sorted_code_systems(self) -> list[str]:
        """Return code systems in stable priority order for auto-detect.

        Priority: iso3 > iso2 > numeric > dcid > wikidata > <other standards
        from builder ordering> > <custom alphabetical>.  The first five slots
        are hard-wired; remaining systems are sorted alphabetically.
        """
        all_systems = self._runner.available_code_systems
        head = [s for s in _CODE_SYSTEM_PRIORITY if s in all_systems]
        tail = sorted(s for s in all_systems if s not in _CODE_SYSTEM_PRIORITY)
        return head + tail

    def make_code_resolved_result(
        self,
        explainer_ref: weakref.ref[Explainer],
        entity_id: str,
        entity: EntityRecord | None,
        value: str,
    ) -> ResolutionResult:
        """Build a RESOLVED ResolutionResult for a code-lookup hit.

        Sets ``query_text`` and the ``_explainer`` weakref so
        ``result.explain()`` works on code-lookup results the same way it
        does on name-resolution results.
        """
        result = ResolutionResult(
            status=ResolutionStatus.RESOLVED,
            entity_id=entity_id,
            entity=entity,
            reasons=[ReasonCode.EXACT_CODE_MATCH],
            query_text=value,
        )
        result._explainer = explainer_ref
        return result

    def resolve_or_lookup(
        self,
        value: str,
        *,
        explainer_ref: weakref.ref[Explainer],
        from_system: str | None = None,
        domain: str | list[str] | None = None,
        context: ResolutionContext | None = None,
        include_entity: bool = False,
        timeout: float | None = None,
        resolve_inner_fn: Callable[..., ResolutionResult],
    ) -> ResolutionResult:
        """Resolve *value* via code lookup or full name resolution.

        When ``from_system`` is set, skips name resolution and calls
        ``runner.lookup_code(from_system, value, ...)`` directly.

        When ``from_system`` is None and *value* matches a code-shape regex,
        iterates loaded code systems in priority order — first hit wins.  If
        multiple systems return *different* entity_ids, raises
        ``AmbiguousResolutionError``.

        Falls through to ``resolve_inner_fn`` when no code match is found.

        Args:
            value: The string to resolve or look up.
            explainer_ref: Weakref to the Explainer (Resolver) for back-ref.
            from_system: When supplied, skip auto-detect and use this system.
            domain: Optional domain filter.
            context: Optional resolution context.
            include_entity: Whether to populate ``result.entity``.
            timeout: Optional per-call timeout in seconds.
            resolve_inner_fn: Callable matching ``_resolve_inner``'s signature;
                called when no code hit is found.
        """
        from resolvekit.core.errors import (
            AmbiguousResolutionError,
            UnknownCodeSystemError,
        )

        normalized_domain = _normalize_domain(domain)
        pack_filter = normalized_domain

        if from_system is not None:
            known_systems = self._runner.available_code_systems
            if from_system not in known_systems:
                raise UnknownCodeSystemError(from_system, sorted(known_systems))

            value_norm = self._runner.normalize_code_value(
                from_system, value, pack_filter=pack_filter
            )
            entity_ids = self._runner.lookup_code(
                from_system, value_norm, pack_filter=pack_filter
            )
            if not entity_ids:
                return ResolutionResult(
                    status=ResolutionStatus.NO_MATCH,
                    reasons=[ReasonCode.NO_CANDIDATES],
                    query_text=value,
                )
            if len(entity_ids) > 1:
                candidates = [CandidateSummary(entity_id=eid) for eid in entity_ids]
                raise AmbiguousResolutionError(candidates=candidates)
            entity_id = entity_ids[0]
            entity = self._runner.get_entity(entity_id) if include_entity else None
            return self.make_code_resolved_result(
                explainer_ref, entity_id, entity, value
            )

        # Auto-detect path: only attempt if value looks like a code.
        if looks_like_code(value):
            systems = self.sorted_code_systems()
            hits: dict[str, str] = {}  # system → entity_id (first unique)
            for system in systems:
                # Normalize per-system: different packs apply distinct transforms
                # (e.g. DUNS dash-strip in org vs plain casefold in geo).
                value_norm = self._runner.normalize_code_value(
                    system, value, pack_filter=pack_filter
                )
                ids = self._runner.lookup_code(
                    system, value_norm, pack_filter=pack_filter
                )
                if ids:
                    hits[system] = ids[0]

            unique_entity_ids = list(dict.fromkeys(hits.values()))
            if len(unique_entity_ids) == 1:
                entity_id = unique_entity_ids[0]
                entity = self._runner.get_entity(entity_id) if include_entity else None
                return self.make_code_resolved_result(
                    explainer_ref, entity_id, entity, value
                )
            if len(unique_entity_ids) > 1:
                candidates = [
                    CandidateSummary(entity_id=eid) for eid in unique_entity_ids
                ]
                raise AmbiguousResolutionError(candidates=candidates)
            # No code hit — fall through to name resolution below.

        # Full name-resolution pipeline via injected callable.
        # resolve_inner_fn is Resolver._resolve_inner — call it directly.
        return resolve_inner_fn(
            value,
            normalized_domain=normalized_domain,
            context=context,
            include_entity=include_entity,
            timeout=timeout,
        )
