"""SuggestFlow — per-call suggest orchestrator.

Owns ``suggest()``: prefix normalization, entity-type/domain routing, fan-out
to ``runner.suggest_prefix``, candidate→result promotion, ``to=`` rendering,
and ``highlight_ranges`` computation.

Bypasses ``_QueryCache`` by construction — holding no cache reference makes
the cache bypass explicit and safe for parallel callers.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from resolvekit.core.api.output_spec import OutputSpec
    from resolvekit.core.api.query_prep import QueryPreparer
    from resolvekit.core.engine.interfaces import ResolverBackend
    from resolvekit.core.engine.suggest_rank import SuggestCandidate
    from resolvekit.core.model.entity import EntityRecord

from resolvekit.core.model.result import MatchClass, SuggestionResult

# Minimum prefix length required to attempt a suggest call.
# Empty or whitespace-only prefixes always return [] without touching the store.
_MIN_PREFIX_LEN: int = 1


class SuggestFlow:
    """Per-call suggest orchestrator.

    Constructed once in ``Resolver.__init__`` and reused across all calls.
    Does NOT hold a reference to ``_QueryCache`` — the cache bypass is
    structural, not conditional.

    Args:
        runner: ``ResolverBackend`` for the suggest fan-out path.
        query_preparer: Normalization helper (shared with ``ResolveFlow``).
        max_query_length: Prefix truncation limit; applied BEFORE normalization.
        default_output_spec: Compiled ``OutputSpec`` from ``Resolver.default_to``,
            or ``None`` when no default is configured.
    """

    def __init__(
        self,
        *,
        runner: ResolverBackend,
        query_preparer: QueryPreparer,
        max_query_length: int,
        default_output_spec: OutputSpec | None,
    ) -> None:
        self._runner = runner
        self._query_preparer = query_preparer
        self._max_query_length = max_query_length
        # The suggest contract says display misses are None, never raised. The
        # resolver's default spec may carry on_missing="raise" (or "auto", which
        # raises for scalar) — force "null" so a suggestion lacking the default
        # code renders None instead of raising, matching the per-call `to` path.
        if default_output_spec is not None and default_output_spec.on_missing != "null":
            import dataclasses

            default_output_spec = dataclasses.replace(
                default_output_spec, on_missing="null"
            )
        self._default_output_spec = default_output_spec

    def suggest(
        self,
        prefix: str,
        *,
        top_k: int,
        domain: str | list[str] | None,
        entity_type: str | list[str] | None,
        context: object,
        to: str | list[str] | None,
        fuzzy: Literal["auto", "always", "never"],
        timeout: float | None,
    ) -> list[SuggestionResult]:
        """Return a ranked suggestion list for *prefix*.

        Validates and normalizes *prefix*, fans out to ``runner.suggest_prefix``,
        then promotes each ``SuggestCandidate`` to a ``SuggestionResult`` by
        rendering ``display`` via the active ``OutputSpec`` and computing
        ``highlight_ranges`` against the rendered string.

        Never raises a verdict (unlike ``resolve()``); below-floor → ``[]``.

        Args:
            prefix: Raw prefix string from the caller.
            top_k: Maximum results to return; clamped to [1, 100].
            domain: Pack filter (same validation as ``resolve()``).
            entity_type: Entity-type filter (e.g. ``"geo.country"``).
            context: Ignored in this cut — present for future caller hints.
            to: Per-call output override; takes precedence over ``default_to``.
            fuzzy: Fuzzy policy propagated to the runner.
            timeout: Per-call time budget; ``None`` = no limit.

        Returns:
            Sorted ``list[SuggestionResult]``, at most ``top_k`` entries.
        """
        # Validate prefix type and whitespace.
        if not isinstance(prefix, str):
            return []
        if not prefix.strip():
            return []

        # Truncate BEFORE normalization to enforce max_query_length independent of
        # the eventual normalized form.
        raw = prefix[: self._max_query_length]

        # Normalize via the shared query preparer.
        from resolvekit.core.util.normalization import NormalizationError

        try:
            norm_result = self._query_preparer.normalize(raw)
        except NormalizationError:
            return []
        query_norm = norm_result.normalized if norm_result else ""
        if not query_norm or len(query_norm) < _MIN_PREFIX_LEN:
            return []

        # Clamp top_k to [1, 100].
        top_k = max(1, min(top_k, 100))

        # Resolve entity_type and domain into filter structures.
        entity_type_prefixes: frozenset[str] | None = None
        if entity_type is not None:
            entity_type_prefixes = frozenset(
                {entity_type} if isinstance(entity_type, str) else entity_type
            )

        # domain validation mirrors _normalize_domain (paths.py); build a
        # pack_filter frozenset that MultiPackRunner uses to skip non-matching
        # packs (single-pack runners accept and ignore it).
        pack_filter: frozenset[str] | None = None
        if domain is not None:
            domains: set[str] = {domain} if isinstance(domain, str) else set(domain)
            dotted = sorted(d for d in domains if "." in d)
            if dotted:
                raise ValueError(
                    f"Domain names must be simple strings (e.g., 'geo'), not dotted. "
                    f"Got: {dotted}. Did you mean entity_type={set(dotted)!r}?"
                )
            pack_filter = frozenset(domains)

        # Compute deadline and fan out to runner.
        deadline: float | None = None
        if timeout is not None:
            deadline = time.monotonic() + timeout

        candidates = self._runner.suggest_prefix(
            query_norm=query_norm,
            top_k=top_k,
            entity_type_prefixes=entity_type_prefixes,
            fuzzy=fuzzy,
            deadline=deadline,
            pack_filter=pack_filter,
        )

        # Promote each SuggestCandidate to SuggestionResult.
        # Determine the effective OutputSpec for display rendering.
        effective_spec = self._default_output_spec
        if to is not None:
            from resolvekit.core.api.output_spec import compile_output_spec

            effective_spec = compile_output_spec(
                to,
                "null",  # on_missing for suggest is always "null"
                known_systems=self._runner.available_code_systems,
            )

        from resolvekit.core.engine.suggest_rank import ranking_quality

        results: list[SuggestionResult] = []
        for cand in candidates:
            display = _render_display(
                cand=cand, runner=self._runner, spec=effective_spec
            )
            highlight_ranges = _compute_highlight_ranges(
                query_norm=query_norm,
                display=display,
                match_class=cand.match_class,
            )
            results.append(
                SuggestionResult(
                    entity_id=cand.entity_id,
                    canonical_name=cand.canonical_name,
                    entity_type=cand.entity_type,
                    pack_id=cand.pack_id,
                    match_class=cand.match_class,
                    fuzzy_score=(
                        cand.match_score
                        if cand.match_class == MatchClass.FUZZY
                        else None
                    ),
                    ranking_quality=ranking_quality(cand.entity_type),
                    display=display,
                    highlight_ranges=highlight_ranges,
                )
            )

        return results


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _render_display(
    *,
    cand: SuggestCandidate,
    runner: ResolverBackend,
    spec: OutputSpec | None,
) -> str | None:
    """Render the ``display`` field for *cand*.

    When no spec is active, falls back to ``canonical_name``.
    When a spec is active, applies it via ``apply_output`` with
    ``scalar=False`` (on_missing="null" semantics).
    """
    if spec is None:
        return cand.canonical_name

    entity: EntityRecord | None = runner.get_entity(cand.entity_id)
    if entity is None:
        return cand.canonical_name

    from resolvekit.core.api.output_spec import apply_output

    return apply_output(entity, spec, scalar=False)


def _compute_highlight_ranges(
    *,
    query_norm: str,
    display: str | None,
    match_class: MatchClass,
) -> list[tuple[int, int]]:
    """Compute ``highlight_ranges`` for *display* given the normalized query.

    Fuzzy matches have no reliable literal span → empty list.
    For exact-prefix / token-prefix / infix matches, fold both strings and
    locate the query span via ``str.find``, then map back to original
    code-point offsets via the offset map from ``fold_with_offsets``.

    Returns Unicode **code-point** offsets (NOT UTF-16), end-exclusive,
    into *display*.  JS/browser callers must convert.
    """
    if match_class == MatchClass.FUZZY:
        # No reliable literal substring to highlight for fuzzy matches.
        return []

    if not display:
        return []

    from resolvekit.core.util.normalization import fold_for_match, fold_with_offsets

    folded_display, offset_map = fold_with_offsets(display)
    folded_query = fold_for_match(query_norm)

    if not folded_query:
        return []

    pos = folded_display.find(folded_query)
    if pos == -1:
        return []

    end_pos = pos + len(folded_query)
    # Map folded indices back to original code-point offsets.
    orig_start = offset_map[pos]
    # end_pos is exclusive; if it's at the end of the folded string the last
    # mapped index is end_pos - 1, and we want the code-point AFTER it.
    if end_pos <= len(offset_map):
        # The last folded char in our span maps to some original index.
        # Original end = original_index + 1 (end-exclusive).
        orig_end = offset_map[end_pos - 1] + 1
    else:
        # Span runs to the end of the string.
        orig_end = len(display)

    return [(orig_start, orig_end)]
