"""Domain pack routing for multi-domain resolution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from collections.abc import Set as AbstractSet
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict, Field

from resolvekit.core.model import Query, ResolutionContext

if TYPE_CHECKING:
    from resolvekit.core.registry import RoutingHints

# Threshold for considering heuristic scores significantly different
SCORE_PREFERENCE_THRESHOLD: Final[float] = 0.2


def _validate_requested_packs(
    domains: AbstractSet[str],
    available_packs: list[str],
) -> list[str]:
    """Validate explicit requested packs against the configured pack set."""
    requested = sorted(domains)
    available = sorted(available_packs)
    unknown = sorted(set(requested) - set(available))
    if unknown:
        raise ValueError(f"Unknown domains: {unknown}. Available packs: {available}")
    return requested


class RoutingMode(StrEnum):
    """Routing mode for multi-domain resolution."""

    EXPLICIT = "explicit"  # Caller specifies which packs to use
    AUTO = "auto"  # Router infers from query patterns
    HYBRID = "hybrid"  # Run multiple packs, compare results


class RoutingDecision(BaseModel):
    """Result of routing decision.

    Attributes:
        target_packs: Pack IDs to route the query to (sorted for determinism)
        confidence: Router's confidence in the decision (0.0-1.0)
        reason: Human-readable explanation of the routing decision
    """

    model_config = ConfigDict(frozen=True)

    target_packs: list[str] = Field(..., min_length=1)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str = Field(default="")

    @property
    def is_single_pack(self) -> bool:
        """Return True if routing to exactly one pack."""
        return len(self.target_packs) == 1


class Router(ABC):
    """Abstract router interface for domain pack selection."""

    @abstractmethod
    def route(self, query: Query, context: ResolutionContext) -> RoutingDecision:
        """Decide which pack(s) to route the query to.

        Args:
            query: The resolution query containing normalized text and
                optional domains
            context: Resolution context with hints and constraints

        Returns:
            RoutingDecision specifying target packs and confidence
        """
        ...


class ExplicitRouter(Router):
    """Routes based on explicit caller request.

    Uses query.domains if provided, otherwise routes to all packs.
    """

    def __init__(self, available_packs: list[str] | None = None) -> None:
        """Initialize ExplicitRouter.

        Args:
            available_packs: List of available pack IDs.

        Raises:
            ValueError: If available_packs is empty.
        """
        self._available = list(available_packs) if available_packs else []
        if not self._available:
            raise ValueError("ExplicitRouter requires at least one available pack")

    def route(self, query: Query, context: ResolutionContext) -> RoutingDecision:
        """Route based on explicit request or fall back to all packs.

        Args:
            query: The resolution query
            context: Resolution context (unused in explicit routing)

        Returns:
            RoutingDecision with requested packs or all available packs
        """
        if query.domains:
            return RoutingDecision(
                target_packs=_validate_requested_packs(query.domains, self._available),
                confidence=1.0,
                reason="Explicit request",
            )

        return RoutingDecision(
            target_packs=self._available.copy(),
            confidence=0.5,
            reason="No explicit type requested, using all packs",
        )


class AutoRouter(Router):
    """Heuristic-based routing.

    Each pack's ``RoutingHints.scoring_fn`` is used when declared; packs
    without one fall through to ``_score_pack()`` which uses keyword hints
    and language affinity.  The optional ``pack_scorers`` constructor arg
    overrides everything on a per-pack basis.

    Note: Short codes (e.g., "US", "EU") often score similarly for both
    geo and org, resulting in multi-pack routing. This is intentional -
    the decision merger will pick the best result.
    """

    def __init__(
        self,
        available_packs: list[str] | None = None,
        pack_hints: dict[str, RoutingHints] | None = None,
        pack_scorers: dict[str, Callable[[str, str], float]] | None = None,
    ) -> None:
        """Initialize AutoRouter.

        Args:
            available_packs: List of available pack IDs.
            pack_hints: Routing hints declared by each pack.
            pack_scorers: Optional custom scoring functions per pack ID.
                Each callable takes (text, text_lower) and returns a float score.
                Overrides pack-declared ``scoring_fn`` for the given pack IDs.

        Raises:
            ValueError: If available_packs is empty.
        """
        self._available = list(available_packs) if available_packs else []
        if not self._available:
            raise ValueError("AutoRouter requires at least one available pack")
        self._pack_hints = pack_hints or {}

        # Build the scorer map: explicit overrides > pack-declared scoring_fn.
        # Packs with neither fall through to _score_pack() (keyword/language hints).
        self._pack_scorers: dict[str, Callable[[str, str], float]] = {}
        custom = pack_scorers or {}
        for pack_id in self._available:
            if pack_id in custom:
                self._pack_scorers[pack_id] = custom[pack_id]
            else:
                hints = self._pack_hints.get(pack_id)
                if hints is not None and hints.scoring_fn is not None:
                    self._pack_scorers[pack_id] = hints.scoring_fn

    def route(self, query: Query, context: ResolutionContext) -> RoutingDecision:
        """Route using heuristics based on query patterns.

        Args:
            query: The resolution query
            context: Resolution context with optional entity_types

        Returns:
            RoutingDecision based on pattern matching scores
        """
        # Check context hints first
        if context.entity_types:
            packs = self._packs_from_types(context.entity_types)
            # Constrain to available packs
            packs = [p for p in packs if p in self._available]
            if packs:
                return RoutingDecision(
                    target_packs=packs,
                    confidence=0.9,
                    reason="ResolutionContext hint",
                )

        text = query.normalized.original
        text_lower = text.lower()

        # Score each available pack using the scorer map (with fallback to hints)
        scores: dict[str, float] = {}
        for pack_id in self._available:
            scorer = self._pack_scorers.get(pack_id)
            if scorer is not None:
                scores[pack_id] = scorer(text, text_lower)
            else:
                scores[pack_id] = self._score_pack(pack_id, text, text_lower, context)

        if not scores:
            return RoutingDecision(
                target_packs=self._available.copy(),
                confidence=0.5,
                reason="No scores available",
            )

        # Find the max score and select packs within threshold
        max_score = max(scores.values())
        target = sorted(
            pack_id
            for pack_id, score in scores.items()
            if score >= max_score - SCORE_PREFERENCE_THRESHOLD
        )

        if len(target) == 1:
            reason = f"Pattern match → {target[0]}"
            confidence = scores[target[0]]
        else:
            reason = "Ambiguous, trying multiple packs"
            confidence = max_score

        return RoutingDecision(
            target_packs=target,
            confidence=confidence,
            reason=reason,
        )

    def _score_pack(
        self,
        pack_id: str,
        text: str,
        text_lower: str,
        context: ResolutionContext,
    ) -> float:
        """Score a pack using its declared keyword and language hints.

        Fallback for packs that declare no ``scoring_fn`` in their
        ``RoutingHints``.
        """
        hints = self._pack_hints.get(pack_id)
        if hints is None:
            return 0.5  # neutral for packs without hints

        score = 0.4

        if hints.keywords and any(kw in text_lower for kw in hints.keywords):
            score += 0.2

        # Language affinity
        if context and context.languages and hints.supported_languages:
            overlap = set(context.languages) & set(hints.supported_languages)
            if overlap:
                score += 0.1

        return min(score, 1.0)

    def _packs_from_types(self, entity_types: Iterable[str]) -> list[str]:
        """Extract pack IDs from type hints.

        Maps type hints like "geo.city" or "org.igo" to their pack prefixes.
        Uses pack_hints type_prefixes for matching, with fallback to prefix
        matching against available packs.
        """
        packs = set()
        for hint in entity_types:
            prefix = hint.split(".")[0]
            matched = False
            for pack_id, hints in self._pack_hints.items():
                if prefix in hints.type_prefixes:
                    packs.add(pack_id)
                    matched = True
            # Per-prefix fallback: if no hint matched this prefix, try direct match
            if not matched and prefix in self._available:
                packs.add(prefix)

        return sorted(packs)


class HybridRouter(Router):
    """Always runs all packs and compares results.

    The engine will run all packs with tight budgets and the
    decision merger will pick the best result across domains.
    """

    def __init__(self, packs: list[str] | None = None) -> None:
        """Initialize HybridRouter.

        Args:
            packs: List of pack IDs to always run.

        Raises:
            ValueError: If packs is empty.
        """
        self._packs = list(packs) if packs else []
        if not self._packs:
            raise ValueError("HybridRouter requires at least one pack")

    def route(self, query: Query, context: ResolutionContext) -> RoutingDecision:
        """Route to all packs (or explicit request if specified).

        Args:
            query: The resolution query
            context: Resolution context (unused unless explicit types requested)

        Returns:
            RoutingDecision targeting all packs or explicit request
        """
        # Honor explicit requests
        if query.domains:
            return RoutingDecision(
                target_packs=_validate_requested_packs(query.domains, self._packs),
                confidence=1.0,
                reason="Explicit request in hybrid mode",
            )

        return RoutingDecision(
            target_packs=self._packs.copy(),
            confidence=0.5,
            reason="Hybrid mode: running all packs",
        )
