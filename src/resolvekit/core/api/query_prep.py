"""QueryPreparer — query normalization and validation collaborator.

Owns normalize, prepare-query, and invalid-query-result logic.
Depends on injected primitives at construction, not on the concrete Resolver
facade.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from resolvekit.core.engine import RoutingMode
from resolvekit.core.errors import UnknownDomainError
from resolvekit.core.model import (
    NormalizedText,
    Query,
    ReasonCode,
    ResolutionContext,
    ResolutionResult,
    ResolutionStatus,
)
from resolvekit.core.util.normalization import TextNormalizer

if TYPE_CHECKING:
    from resolvekit.core.engine.interfaces import ResolverBackend


class QueryPreparer:
    """Owns normalization and query-preparation logic; no Resolver dependency.

    Constructed once in ``Resolver.__init__`` and reused across all calls.
    """

    def __init__(
        self,
        *,
        runner: ResolverBackend,
        normalizer: TextNormalizer,
        pack_normalizers: dict[str, TextNormalizer],
        max_query_length: int,
        routing_mode: RoutingMode | None,
        default_context: ResolutionContext,
    ) -> None:
        self._runner = runner
        self._normalizer = normalizer
        self._pack_normalizers = pack_normalizers
        self._max_query_length = max_query_length
        self._routing_mode = routing_mode
        self._default_context = default_context

    def normalize(self, text: str, pack_id: str | None = None) -> NormalizedText:
        """Normalize text using the configured normalizer.

        Uses a pack-specific normalization profile when ``pack_id`` is given
        and a matching normalizer exists; falls back to the default profile.
        """
        if pack_id and pack_id in self._pack_normalizers:
            return self._pack_normalizers[pack_id].normalize_with_original(text)
        return self._normalizer.normalize_with_original(text)

    def prepare_query(
        self,
        text: str,
        context: ResolutionContext | None,
        domains: frozenset[str] | None,
    ) -> tuple[Query, ResolutionContext]:
        """Validate and prepare query for resolution.

        Performs routing validation, query-length truncation, and normalization.

        Raises:
            ValueError: When domains are specified with AUTO routing mode.
            UnknownDomainError: When a domain name is not registered.
        """
        if self._routing_mode == RoutingMode.AUTO and domains:
            raise ValueError(
                "Cannot specify domains with AUTO routing mode. "
                "Use RoutingMode.EXPLICIT for caller-controlled pack selection, "
                "or remove domains to let AUTO mode decide."
            )
        if domains:
            available_packs = self._runner.available_packs
            if available_packs:
                unknown = sorted(domains - available_packs)
                if unknown:
                    raise UnknownDomainError(unknown, sorted(available_packs))

        effective_context = context if context is not None else self._default_context
        text = text[: self._max_query_length]
        normalized = self.normalize(text)

        query = Query(
            raw_text=text,
            normalized=normalized,
            domains=domains,
        )
        return query, effective_context

    @staticmethod
    def invalid_query_result(
        reason: ReasonCode = ReasonCode.INVALID_QUERY,
    ) -> ResolutionResult:
        """Return a stable result for empty / whitespace-only / non-string queries."""
        return ResolutionResult(
            status=ResolutionStatus.NO_MATCH,
            reasons=[reason],
        )
