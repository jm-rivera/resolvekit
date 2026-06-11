"""Internal helper for Resolver.inspect."""

from __future__ import annotations

from typing import TYPE_CHECKING

from resolvekit.core.engine.interfaces import PipelineResult
from resolvekit.core.model.inspection import InspectionReport, InspectMatch
from resolvekit.core.util.normalization import NormalizationError

if TYPE_CHECKING:
    from resolvekit.core.api.resolver import Resolver


def _run_inspection(
    *,
    resolver: Resolver,
    text: str,
    domain: str | list[str] | None = None,
) -> InspectionReport:
    """Build a diagnostic InspectionReport for *text*.

    Shows exact-code matches, exact-name matches, and the top-5 fuzzy
    candidates unfiltered by the decision policy.

    Args:
        resolver: The Resolver instance to inspect through.
        text: Raw query text.
        domain: Optional domain filter (same semantics as Resolver.resolve).

    Returns:
        InspectionReport — always returns a report, never raises on bad input.
    """
    from resolvekit.core.api.loading import _normalize_domain

    if not isinstance(text, str) or not text.strip():
        return InspectionReport(
            query=text if isinstance(text, str) else "", normalized=""
        )

    try:
        query, context = resolver._prepare_query(text, None, _normalize_domain(domain))
    except (NormalizationError, ValueError):
        return InspectionReport(query=text, normalized="")

    normalized_text = query.normalized.normalized
    runner = resolver._runner

    # Resolve the optional domain filter to a frozenset for pack attribution.
    # lookup_name_exact / lookup_code both accept a pack_filter kwarg.
    pack_filter: frozenset[str] | None = (
        frozenset(query.domains) if query.domains else None
    )

    code_matches: list[InspectMatch] = []
    seen_code_ids: set[str] = set()
    # lookup_code_attributed returns (pack_id, entity_id) pairs — pack attribution preserved.
    for system in runner.available_code_systems:
        # Normalize through the owning pack's code normalizer so the code
        # lookup matches value_norm in the store by construction (not via the
        # TextNormalizer, which applies name-oriented transforms, not code ones).
        code_norm = runner.normalize_code_value(
            system, normalized_text, pack_filter=pack_filter
        )
        for store_pack_id, eid in runner.lookup_code_attributed(
            system=system, value_norm=code_norm, pack_filter=pack_filter
        ):
            if eid in seen_code_ids:
                continue
            seen_code_ids.add(eid)
            entity = runner.get_entity(eid)
            code_matches.append(
                InspectMatch(
                    entity_id=eid,
                    canonical_name=entity.canonical_name if entity else None,
                    pack_id=store_pack_id or None,
                    entity_type=entity.entity_type if entity else None,
                    matched_field=f"code.{system}",
                    matched_value=code_norm,
                )
            )

    name_matches: list[InspectMatch] = []
    seen_name_ids: set[str] = set()
    # lookup_name_exact returns (pack_id, entity_id) pairs — pack attribution preserved.
    for store_pack_id, eid in runner.lookup_name_exact(
        value=normalized_text, pack_filter=pack_filter
    ):
        if eid in seen_name_ids:
            continue
        seen_name_ids.add(eid)
        entity = runner.get_entity(eid)
        name_matches.append(
            InspectMatch(
                entity_id=eid,
                canonical_name=entity.canonical_name if entity else None,
                pack_id=store_pack_id or None,
                entity_type=entity.entity_type if entity else None,
                matched_field="name",
                matched_value=normalized_text,
            )
        )

    fuzzy_candidates: list[InspectMatch] = []
    pipeline_result = runner.resolve_detailed(query, context)
    if isinstance(pipeline_result, PipelineResult):
        # Reuse the enrichment _finalize_result already did on result.candidates
        # (canonical_name / entity_type / pack_id) — no per-candidate re-fetch.
        for summary in pipeline_result.result.candidates[:5]:
            fuzzy_candidates.append(
                InspectMatch(
                    entity_id=summary.entity_id,
                    canonical_name=summary.canonical_name,
                    pack_id=summary.pack_id,
                    entity_type=summary.entity_type,
                )
            )

    return InspectionReport(
        query=text,
        normalized=normalized_text,
        exact_code_matches=code_matches,
        exact_name_matches=name_matches,
        fuzzy_candidates=fuzzy_candidates,
    )
