"""``_bulk_dispatch`` — batch resolution with native-shape dispatch.

Returns the user's native shape directly when ``to=`` is a scalar pivot or
a spec is active with ``output="series"``, or a
:class:`~resolvekit.core.model.bulk_result.BulkResult` otherwise.

The public surface lives at :func:`resolvekit.bulk` (convenience layer) and
:meth:`Resolver.bulk`; both delegate here.
"""

from __future__ import annotations

import difflib
import math
import warnings
import weakref
from typing import Any, Literal

from resolvekit.core.api.code_lookup import looks_like_code as _looks_like_code
from resolvekit.core.api.output_spec import UNSET as _UNSET
from resolvekit.core.api.output_spec import (
    OutputSpec,
    _coerce_on_missing,
    apply_output,
)
from resolvekit.core.errors import (
    AmbiguousResolutionError,
    CrosswalkError,
    ResolutionError,
    UnknownCodeSystemError,
    UnknownDomainError,
)
from resolvekit.core.model import (
    ResolutionResult,
    ResolutionStatus,
)
from resolvekit.core.model.bulk_result import BulkResult
from resolvekit.core.model.crosswalk import _MISSING, Crosswalk
from resolvekit.core.model.entity_attributes import dispatch_pivot
from resolvekit.core.model.result import ReasonCode


def _closest_match(value: str, choices: tuple[str, ...]) -> str | None:
    """Return the closest match to *value* from *choices*, or None."""
    matches = difflib.get_close_matches(value, choices, n=1, cutoff=0.6)
    return matches[0] if matches else None


def _validate_domain_available(domain: str | list[str] | None, resolver: Any) -> None:
    """Raise ``UnknownDomainError`` when *domain* names a pack the resolver lacks.

    No-op when *domain* is None or the resolver reports no available packs.
    """
    from resolvekit.core.api.loading import _normalize_domain

    norm_domain = _normalize_domain(domain)
    if norm_domain is None:
        return
    available = resolver._runner.available_packs
    if not available:
        return
    unknown = sorted(norm_domain - available)
    if unknown:
        raise UnknownDomainError(unknown, sorted(available))


def _numeric_to_str(v: int | float) -> str:
    """Coerce an ``int`` or ``float`` to its canonical string form.

    Integral floats (``840.0``) produce the same string as the equivalent
    integer (``"840"``), matching the numeric codes stored in data packs.
    Non-integral floats (``840.5``) are left to plain ``str()`` — they will
    not match any code, but the string is well-defined.

    This is the shared coercion kernel used by both the scalar resolve path
    and ``_flatten_input`` so the two can never diverge.
    """
    if isinstance(v, float) and math.isfinite(v) and v == int(v):
        # Integral float — strip the decimal part.
        return str(int(v))
    return str(v)


def _coerce_item_to_str(v: object) -> str:
    """Coerce a non-null collection element to ``str``.

    ``int`` and ``float`` values are passed through ``_numeric_to_str`` so
    that integral floats (``840.0``) map to ``"840"`` rather than
    ``"840.0"``.  All other types fall back to ``str()``.
    """
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return _numeric_to_str(v)  # type: ignore[arg-type]
    return str(v)


# Sentinel for crosswalk IGNORE entries — bypasses _apply_not_found.
_IGNORE_RESULT: ResolutionResult = ResolutionResult(
    status=ResolutionStatus.NO_MATCH,
    reasons=(ReasonCode.SENTINEL_BLOCKED,),
)

_InputKind = Literal["pandas", "polars", "numpy", "list", "tuple", "dict"]


def _detect_input_kind(values: Any) -> tuple[_InputKind, Any]:
    """Classify *values* into a supported input kind.

    Returns a ``(kind, values)`` pair.  Raises ``TypeError`` for unsupported
    types (generators, arbitrary iterables, etc.).
    """
    # Check pandas first (before numpy — pd.Series IS array-like).
    try:
        import pandas as pd

        if isinstance(values, pd.Series):
            return "pandas", values
    except ImportError:
        pass

    try:
        import polars as pl

        if isinstance(values, pl.Series):
            return "polars", values
    except ImportError:
        pass

    try:
        import numpy as np

        if isinstance(values, np.ndarray):
            return "numpy", values
    except ImportError:
        pass

    if isinstance(values, list):
        return "list", values
    if isinstance(values, tuple):
        return "tuple", values
    if isinstance(values, dict):
        return "dict", values

    # Generators and other iterables: refuse with a hint.
    if hasattr(values, "__iter__") and not hasattr(values, "__len__"):
        err = TypeError(
            f"bulk() does not accept generators or arbitrary iterables "
            f"(got {type(values).__name__!r}); "
            f"materialize first: list(values)"
        )
        setattr(err, "hint", "materialize first: list(values)")  # noqa: B010
        raise err

    # Check if a DataFrame was passed — give a column-extraction hint.
    _df_hint: str | None = None
    try:
        import pandas as pd

        if isinstance(values, pd.DataFrame):
            _df_hint = "extract one column first: values['col_name']"
    except ImportError:
        pass
    if _df_hint is None:
        try:
            import polars as pl

            if isinstance(values, pl.DataFrame):
                _df_hint = (
                    "extract one column first: "
                    "values['col_name'] or values.get_column('col_name')"
                )
        except ImportError:
            pass

    _base_msg = (
        f"bulk() values must be a list, tuple, dict, numpy ndarray, "
        f"pd.Series, or pl.Series; got {type(values).__name__!r}"
    )
    raise TypeError(_base_msg + (f"; {_df_hint}" if _df_hint else ""))


def _dedup_list(
    items: list[str | None],
) -> tuple[list[str], list[int | None]]:
    """Return (uniques, indexer) for *items*.

    ``uniques`` is the ordered list of distinct non-null strings.
    ``indexer[i]`` is the position of ``items[i]`` in ``uniques``, or
    ``None`` when ``items[i]`` is null.
    """
    seen: dict[str, int] = {}
    uniques: list[str] = []
    for v in items:
        if v is not None and v not in seen:
            seen[v] = len(uniques)
            uniques.append(v)
    indexer: list[int | None] = [None if v is None else seen[v] for v in items]
    return uniques, indexer


def _dedup_pairs(
    items: list[str | None],
    contexts: list[Any],
) -> tuple[list[tuple[str, Any]], list[int | None]]:
    """Return (unique_pairs, indexer) for per-row context resolution.

    ``unique_pairs`` is a list of ``(text, context)`` tuples for distinct
    non-null ``(text, context._cache_key())`` pairs.  ``indexer[i]`` is the
    position of row ``i`` in ``unique_pairs``, or ``None`` when ``items[i]``
    is null.

    Uses ``context._cache_key()`` for identity so that structurally-equal
    ``ResolutionContext`` objects deduplicate — the same guarantee provided by
    ``_QueryCache`` and ``BatchResolver``.
    """
    # Compute (value, ctx_key, ctx) once per row — avoids calling ctx._cache_key() twice.
    row_keys: list[tuple[str | None, tuple, Any]] = [
        (v, (() if ctx is None else ctx._cache_key()), ctx)
        for v, ctx in zip(items, contexts, strict=True)
    ]
    seen: dict[tuple, int] = {}
    unique_pairs: list[tuple[str, Any]] = []
    for v, ctx_key, ctx in row_keys:
        if v is None:
            continue
        pair_key = (v, ctx_key)
        if pair_key not in seen:
            seen[pair_key] = len(unique_pairs)
            unique_pairs.append((v, ctx))
    indexer: list[int | None] = [
        None if v is None else seen[(v, ctx_key)] for v, ctx_key, _ in row_keys
    ]
    return unique_pairs, indexer


def _is_per_row_value(v: Any) -> bool:
    """Return True when *v* is a Series, list, or numpy array (per-row context value)."""
    if isinstance(v, list):
        return True
    try:
        import pandas as pd

        if isinstance(v, pd.Series):
            return True
    except ImportError:
        pass
    try:
        import polars as pl

        if isinstance(v, (pl.Series, pl.Expr)):
            return True
    except ImportError:
        pass
    try:
        import numpy as np

        if isinstance(v, np.ndarray):
            return True
    except ImportError:
        pass
    return False


def _context_has_per_row_value(context: Any) -> bool:
    """Return True when *context* is a dict carrying any per-row (Series/list/array) value.

    Such a context bypasses eager coercion and the uniform-context dedup path,
    routing through the per-row ``_dedup_pairs`` machinery instead.
    """
    return isinstance(context, dict) and any(
        _is_per_row_value(v) for v in context.values()
    )


def _extract_scalar_list(v: Any, n: int, key: str) -> list[Any]:
    """Extract a Python list of length *n* from a per-row context value *v*.

    Raises ``ValueError`` when the length differs from *n*.
    """
    values = _to_plain_list(v)
    if len(values) != n:
        raise ValueError(f"context[{key!r}] length {len(values)} != {n}")
    return values


def _to_plain_list(v: Any) -> list[Any]:
    """Materialize a per-row context value (list, Series, or ndarray) to a list."""
    if isinstance(v, list):
        return v
    try:
        import pandas as pd

        if isinstance(v, pd.Series):
            return v.tolist()
    except ImportError:
        pass
    try:
        import polars as pl

        if isinstance(v, pl.Series):
            return v.to_list()
    except ImportError:
        pass
    try:
        import numpy as np

        if isinstance(v, np.ndarray):
            return v.tolist()
    except ImportError:
        pass
    return list(v)


def _expand_per_row_contexts(
    context_dict: dict[str, Any],
    n: int,
    *,
    resolver: Any,
) -> list[Any]:
    """Expand a per-row context dict into a list of *n* ResolutionContext objects.

    Validates lengths, broadcasts scalars to length-*n*, then deduplicates by
    frozenset signature before construction — coercing each unique signature
    once rather than once per row.

    Country-name coercion happens inside ``coerce_context`` — once per unique
    value, not per row.  Returns a ``list[ResolutionContext | None]`` of length *n*.
    """
    from resolvekit.core.api.context_input import coerce_context

    # Validate lengths and convert per-row values to column lists.
    columns: dict[str, list[Any]] = {}
    for key, val in context_dict.items():
        if _is_per_row_value(val):
            columns[key] = _extract_scalar_list(val, n, key)
        else:
            columns[key] = [val] * n

    # Dedup-before-construct — group rows by frozenset signature.
    # Signature uses scalar values only; per-row country coercion handled in coerce_context.
    sig_to_ctx: dict[frozenset, Any] = {}
    result: list[Any] = []
    for i in range(n):
        row = {key: col[i] for key, col in columns.items()}
        sig: frozenset = frozenset((k, str(v)) for k, v in row.items())
        if sig not in sig_to_ctx:
            sig_to_ctx[sig] = coerce_context(row, resolver=resolver)
        result.append(sig_to_ctx[sig])
    return result


def _apply_not_found(
    result: ResolutionResult,
    original: str,
    not_found: str,
    on_ambiguous: str,
) -> Any:
    """Convert a ResolutionResult to the caller's desired value.

    Returns ``None`` for no-match / ambiguous (per the contracts), the
    original string for ``on_error="keep"``, or the entity pivot value
    when resolved.
    """
    if result.status == ResolutionStatus.RESOLVED:
        return result  # pivot applied later

    if result.status == ResolutionStatus.AMBIGUOUS:
        if on_ambiguous == "raise":
            raise AmbiguousResolutionError(candidates=list(result.candidates))
        if on_ambiguous == "best":
            # Return a synthetic RESOLVED result wrapping the top candidate.
            top = result.candidates[0] if result.candidates else None
            if top is not None:
                return result.model_copy(
                    update={
                        "status": ResolutionStatus.RESOLVED,
                        "entity_id": top.entity_id,
                    }
                )
        return None  # on_ambiguous="null"

    # NO_MATCH or ERROR
    if not_found == "raise":
        raise ResolutionError(
            status=result.status,
            candidates=(),
            message=f"no match for {original!r}",
        )
    if not_found == "null":
        return None
    return not_found  # literal sentinel string


def _pivot_result(
    result: ResolutionResult,
    to: Any,
    *,
    spec: OutputSpec | None,
    on_missing: str = "auto",
    known_systems: frozenset[str] | None = None,
) -> Any:
    """Apply pivoting when *result* is RESOLVED; else return as-is.

    On the **spec path** (``spec is not None``), calls ``apply_output`` with
    ``scalar=False`` — per-entity misses return ``None`` and never raise
    (batch-safe).  When the spec carries ``on_missing="raise"``, ``apply_output``
    raises ``OutputMissingError`` on the first wholly-missing entity; the
    exception propagates out, aborting the batch.

    On the **explicit-to path** (``spec is None``), calls ``dispatch_pivot``
    with selective ``UnknownCodeSystemError`` handling — a typo'd code system
    still surfaces loudly (every row would silently return None otherwise).
    When ``to`` is a *known* code system but this entity simply lacks it,
    ``on_missing`` governs the outcome: ``"auto"`` / ``"null"`` → ``None``;
    ``"raise"`` re-raises.  Per-entity misses on non-code pivots return None.
    """
    if result.status != ResolutionStatus.RESOLVED or result.entity is None:
        return None

    if spec is not None:
        # Spec path: apply_output handles the full chain + on_missing policy.
        # scalar=False → "auto" resolves to null; explicit "raise" still raises.
        return apply_output(result.entity, spec, scalar=False)

    try:
        return dispatch_pivot(result.entity, to)
    except UnknownCodeSystemError:
        # Distinguish a resolved-entity-lacking-a-code (output miss, governed by
        # on_missing) from a genuine typo/unknown system (always raises loudly).
        if (
            isinstance(to, str)
            and known_systems is not None
            and to in known_systems
            and on_missing != "raise"
        ):
            return None  # known system, this entity just lacks it
        raise  # genuine typo or unknown system: surface loudly
    except Exception:
        return None


def _flatten_input(
    kind: _InputKind,
    raw: Any,
) -> tuple[list[str | None], Any, Any, str | None, list[str] | None]:
    """Flatten *raw* to a Python list of ``str | None`` and capture shape metadata.

    Returns ``(items, orig_index, orig_name, orig_polars_name, orig_keys)``.
    ``orig_index`` / ``orig_name`` are ``None`` for non-pandas input;
    ``orig_polars_name`` is ``None`` for non-polars input;
    ``orig_keys`` holds the dict's key list in order for ``kind="dict"``,
    and ``None`` for all other input kinds.
    """
    orig_index: Any = None
    orig_name: Any = None
    orig_polars_name: str | None = None
    orig_keys: list[str] | None = None

    if kind == "pandas":
        import pandas as pd

        orig_index = raw.index
        orig_name = raw.name
        # Coerce to object before map so typed Series (Int64, categorical) don't reject ""
        items: list[str | None] = [
            None if pd.isna(v) else _coerce_item_to_str(v) for v in raw.astype(object)
        ]
    elif kind == "polars":
        orig_polars_name = raw.name
        items = [None if v is None else _coerce_item_to_str(v) for v in raw.to_list()]
    elif kind == "numpy":
        import numpy as np

        items = [
            None
            if (v is None or (isinstance(v, float) and np.isnan(v)))
            else _coerce_item_to_str(v)
            for v in raw.tolist()
        ]
    elif kind == "dict":
        orig_keys = list(raw.keys())
        items = [None if v is None else _coerce_item_to_str(v) for v in raw.values()]
    elif kind == "tuple":
        items = [None if v is None else _coerce_item_to_str(v) for v in raw]
    else:  # list
        items = [None if v is None else _coerce_item_to_str(v) for v in raw]

    return items, orig_index, orig_name, orig_polars_name, orig_keys


def _resolve_uniques(
    *,
    resolver: Any,
    uniques: list[str],
    from_system: str | None,
    domain: str | list[str] | None,
    context: Any,
    include_entity: bool,
    on_error: str,
    crosswalk: Crosswalk | None = None,
) -> list[ResolutionResult]:
    """Resolve each unique value and return one ``ResolutionResult`` per unique.

    When *crosswalk* is provided, values present in it skip name resolution
    entirely.  Synthetic RESOLVED results (or ``_IGNORE_RESULT`` for IGNORE entries)
    are placed directly in ``unique_results`` for broadcast by ``_assemble_output``.
    Unknown entity-ids under ``strict=True`` raise ``CrosswalkError`` before
    the remainder is resolved.

    Uses the code-input short-circuit when all uniques look like codes or
    ``from_system`` is set; otherwise dispatches to ``_resolve_many_internal``.
    """
    unique_results: list[ResolutionResult | None] = [None] * len(uniques)
    to_resolve_idx: list[int] = []
    offenders: list[str] = []

    for i, u in enumerate(uniques):
        hit = crosswalk._get(u) if crosswalk is not None else _MISSING
        if hit is _MISSING:
            to_resolve_idx.append(i)
            continue
        if hit is None:
            unique_results[i] = _IGNORE_RESULT
            continue
        # Crosswalk hit: verify entity exists via the runner.
        eid: str = hit  # ty: ignore[invalid-assignment]  # type: ignore[assignment]
        entity = resolver._runner.get_entity(eid)  # type: ignore[union-attr]
        if entity is None:
            offenders.append(eid)
            unique_results[i] = ResolutionResult(
                status=ResolutionStatus.NO_MATCH,
                query_text=u,
                reasons=(ReasonCode.SENTINEL_BLOCKED,),
            )
            continue
        # Entity found — synthetic RESOLVED result with entity attached.
        unique_results[i] = ResolutionResult(
            status=ResolutionStatus.RESOLVED,
            entity_id=eid,
            entity=entity,
            query_text=u,
            reasons=(ReasonCode.EXACT_CODE_MATCH,),
        )

    # Fail fast on unknown ids when strict mode is active.
    if crosswalk is not None and crosswalk.strict and offenders:
        raise CrosswalkError(offenders)

    to_resolve = [uniques[i] for i in to_resolve_idx]

    # Code-path detection runs over the to-resolve subset only (never the full
    # uniques list) so a fully-crosswalked batch routes the empty remainder correctly.
    use_code_path = from_system is not None or (
        bool(to_resolve) and all(_looks_like_code(u) for u in to_resolve)
    )

    if use_code_path:
        resolved_subset: list[ResolutionResult] = []
        for u in to_resolve:
            try:
                r = resolver._code_lookup.resolve_or_lookup(
                    u,
                    explainer_ref=weakref.ref(resolver),
                    from_system=from_system,
                    domain=domain,
                    context=context,
                    include_entity=include_entity,
                    timeout=None,
                    resolve_inner_fn=resolver._resolve_inner,
                )
            except Exception:
                if on_error == "raise":
                    raise
                if on_error == "null":
                    r = ResolutionResult(
                        status=ResolutionStatus.ERROR,
                        reasons=(ReasonCode.INTERNAL_ERROR,),
                    )
                else:  # keep — pass through original input string as query_text
                    r = ResolutionResult(
                        status=ResolutionStatus.NO_MATCH,
                        reasons=(ReasonCode.INTERNAL_ERROR,),
                        query_text=u,
                    )
            resolved_subset.append(r)
    elif to_resolve:
        # Batch resolve via resolve_many (with include_entity when pivoting).
        try:
            _validate_domain_available(domain, resolver)
            raw_results = resolver._resolve_many_internal(
                to_resolve,
                domain=domain,
                context=context,
                include_entity=include_entity,
            )
            resolved_subset = list(raw_results)
        except Exception:
            if on_error == "raise":
                raise
            _batch_sentinel = ResolutionResult(
                status=ResolutionStatus.ERROR,
                reasons=(ReasonCode.INTERNAL_ERROR,),
            )
            resolved_subset = [_batch_sentinel] * len(to_resolve)
    else:
        resolved_subset = []

    # Scatter resolved results back to their original unique indices.
    for list_pos, orig_idx in enumerate(to_resolve_idx):
        unique_results[orig_idx] = resolved_subset[list_pos]

    return unique_results  # ty: ignore[invalid-return-type]  # type: ignore[return-value]


def _assemble_output(
    *,
    items: list[str | None],
    indexer: list[int | None],
    unique_results: list[ResolutionResult],
    uniques: list[str],
    to: Any,
    spec: OutputSpec | None,
    not_found: str,
    on_ambiguous: str,
    resolver: Any,
    on_missing: str = "auto",
    known_systems: frozenset[str] | None = None,
) -> tuple[list[Any], list[ResolutionResult]]:
    """Apply not_found / on_ambiguous contracts, pivot, and broadcast to original order.

    Returns ``(out_values, out_source)``.  Entity fetches for ``on_ambiguous="best"``
    happen per-unique (not per-broadcast), so each entity is fetched at most once.

    When ``spec`` is set, pivoting goes through ``apply_output`` (batch-safe:
    per-entity misses return None unless ``on_missing="raise"`` in the spec).
    Otherwise uses ``dispatch_pivot`` with selective ``UnknownCodeSystemError``
    handling: typos still raise; a known system absent from this entity honours
    ``on_missing``.
    """
    _null_sentinel = ResolutionResult(
        status=ResolutionStatus.NO_MATCH,
        reasons=(ReasonCode.INVALID_QUERY,),
    )

    pivoting = spec is not None or to is not None

    unique_out: list[Any] = []  # pivot result per unique (len == len(uniques))
    for i, r in enumerate(unique_results):
        if r is _IGNORE_RESULT:
            # IGNORE entry bypasses _apply_not_found, so not_found="raise" never fires.
            unique_out.append(None)
            continue
        coerced = _apply_not_found(r, uniques[i], not_found, on_ambiguous)
        if coerced is None or isinstance(coerced, str):
            unique_out.append(coerced)
        elif hasattr(coerced, "status"):
            # When on_ambiguous="best" promotes an AMBIGUOUS result, the synthetic
            # RESOLVED result has entity_id set but entity=None.  Fetch the entity
            # lazily so that pivot dispatch works correctly.
            if pivoting and coerced.entity is None and coerced.entity_id is not None:
                fetched = resolver._runner.get_entity(coerced.entity_id)
                if fetched is not None:
                    coerced = coerced.model_copy(update={"entity": fetched})
            unique_out.append(
                _pivot_result(
                    coerced,
                    to,
                    spec=spec,
                    on_missing=on_missing,
                    known_systems=known_systems,
                )
                if pivoting
                else coerced
            )
        else:
            unique_out.append(coerced)

    # Broadcast back to original order.
    out_values: list[Any] = []
    out_source: list[ResolutionResult] = []
    for idx, item in enumerate(items):
        if item is None:
            out_values.append(None)
            out_source.append(_null_sentinel)
        else:
            ui = indexer[idx]
            if ui is not None:  # mypy narrowing
                out_values.append(unique_out[ui])
                out_source.append(unique_results[ui])

    return out_values, out_source


def _bulk_dispatch(
    *,
    resolver: Any,
    values: Any,
    to: Any = _UNSET,
    output: str,
    domain: str | list[str] | None,
    context: Any,
    from_system: str | None,
    not_found: str,
    on_error: str,
    on_ambiguous: str,
    output_spec: OutputSpec | None = None,
    on_missing: str = "auto",
    crosswalk: Crosswalk | None = None,
) -> Any:
    """Core implementation shared by ``Resolver.bulk()`` and ``resolvekit.bulk()``.

    Args:
        resolver: The resolver instance (duck-typed).
        values: Batch of input values (list, tuple, pd.Series, pl.Series, or ndarray).
        to: Explicit pivot target.  ``UNSET`` (default) activates ``output_spec``
            when set.  ``None`` forces raw ``ResolutionResult`` output.
        output: Return shape — ``"series"``, ``"record"``, or ``"frame"``.
        domain: Domain filter forwarded to resolver.
        context: Resolution context forwarded to resolver.
        from_system: Source code system forwarded to resolver.
        not_found: Policy for NO_MATCH rows (``"null"``, ``"raise"``, or a literal).
        on_error: Policy for ERROR rows (``"null"`` or ``"raise"``).
        on_ambiguous: Policy for AMBIGUOUS rows (``"null"``, ``"raise"``, or ``"best"``).
        output_spec: Compiled ``OutputSpec`` for the default-output path.  Ignored
            when ``to`` is not ``UNSET``.
        on_missing: ``"auto"`` (default) — resolves to null for bulk.  ``"raise"``
            raises ``OutputMissingError`` on the spec path or re-raises
            ``UnknownCodeSystemError`` on the explicit-to path when the entity
            lacks a known code system.  ``"null"`` forces null silently.  On the
            explicit-to path, governs resolved-entities-lacking-a-code (output
            misses); genuine typos / unknown systems always raise regardless.
        crosswalk: Optional :class:`~resolvekit.core.model.crosswalk.Crosswalk`
            mapping.  Matched values bypass code-detection and name resolution
            entirely; IGNORE entries map unconditionally to ``None``.
    """
    if output not in {"series", "record", "frame"}:
        raise ValueError(
            f"output={output!r} is not valid; "
            "expected one of 'series', 'record', 'frame'"
        )
    if on_error not in {"raise", "null", "keep"}:
        _did_you_mean = _closest_match(on_error, ("raise", "null", "keep"))
        raise ValueError(
            f"on_error={on_error!r} is not valid; "
            f"expected one of 'raise', 'null', 'keep'"
            + (f"; did you mean {_did_you_mean!r}?" if _did_you_mean else "")
        )
    if on_ambiguous not in {"raise", "null", "best"}:
        _did_you_mean = _closest_match(on_ambiguous, ("raise", "null", "best"))
        raise ValueError(
            f"on_ambiguous={on_ambiguous!r} is not valid; "
            f"expected one of 'raise', 'null', 'best'"
            + (f"; did you mean {_did_you_mean!r}?" if _did_you_mean else "")
        )
    if on_missing not in {"raise", "null", "auto"}:
        _did_you_mean = _closest_match(on_missing, ("raise", "null", "auto"))
        raise ValueError(
            f"on_missing={on_missing!r} is not valid; "
            f"expected one of 'raise', 'null', 'auto'"
            + (f"; did you mean {_did_you_mean!r}?" if _did_you_mean else "")
        )

    kind, raw = _detect_input_kind(values)
    items, orig_index, orig_name, orig_polars_name, orig_keys = _flatten_input(
        kind, raw
    )

    # Pivot detection: explicit to= (not UNSET/None) vs. spec path (UNSET + output_spec).
    has_pivot = to is not _UNSET and to is not None
    spec_active = to is _UNSET and output_spec is not None

    # When pivoting (either path), we need entities hydrated.
    include_entity_for_call = has_pivot or spec_active

    # Build the effective spec for this call.
    # On the spec path, honour the per-call on_missing override. The chain is
    # already validated; construct a new frozen OutputSpec directly.
    effective_spec: OutputSpec | None = None
    if spec_active and output_spec is not None:
        if on_missing != output_spec.on_missing:
            effective_spec = OutputSpec(
                chain=output_spec.chain,
                on_missing=_coerce_on_missing(on_missing),
            )
        else:
            effective_spec = output_spec

    # Per-row context (Series/list values) uses _dedup_pairs instead of _dedup_list.
    # Crosswalk is incompatible with per-row context.
    _context_is_per_row = _context_has_per_row_value(context)

    if _context_is_per_row:
        if crosswalk is not None:
            raise ValueError(
                "crosswalk= is not supported together with per-row context; "
                "remove either crosswalk= or the per-row context column(s)"
            )
        # Expand per-row context into a list of ResolutionContext | None per row.
        n = len(items)
        row_contexts = _expand_per_row_contexts(context, n, resolver=resolver)

        # Deduplicate by (text, ctx._cache_key()) to avoid redundant resolutions.
        unique_pairs, pair_indexer = _dedup_pairs(items, row_contexts)

        unique_texts = [p[0] for p in unique_pairs]
        unique_ctxs = [p[1] for p in unique_pairs]

        # Resolve the unique (text, context) pairs.
        try:
            _validate_domain_available(domain, resolver)
            raw_results = resolver._resolve_many_internal(
                unique_texts,
                domain=domain,
                context=unique_ctxs,
                include_entity=include_entity_for_call,
            )
            unique_results: list[ResolutionResult] = list(raw_results)
        except Exception:
            if on_error == "raise":
                raise
            _batch_sentinel = ResolutionResult(
                status=ResolutionStatus.ERROR,
                reasons=(ReasonCode.INTERNAL_ERROR,),
            )
            unique_results = [_batch_sentinel] * len(unique_pairs)

        # Re-use _assemble_output with the per-row indexer.
        # ``uniques`` here are the unique texts (for not_found messages).
        out_values, out_source = _assemble_output(
            items=items,
            indexer=pair_indexer,
            unique_results=unique_results,
            uniques=unique_texts,
            to=to if has_pivot else None,
            spec=effective_spec,
            not_found=not_found,
            on_ambiguous=on_ambiguous,
            resolver=resolver,
            on_missing=on_missing,
            known_systems=resolver.code_systems() if has_pivot else None,
        )
    else:
        # Uniform (scalar or None) context.
        uniques, indexer = _dedup_list(items)

        unique_results = _resolve_uniques(
            resolver=resolver,
            uniques=uniques,
            from_system=from_system,
            domain=domain,
            context=context,
            include_entity=include_entity_for_call,
            on_error=on_error,
            crosswalk=crosswalk,
        )
        out_values, out_source = _assemble_output(
            items=items,
            indexer=indexer,
            unique_results=unique_results,
            uniques=uniques,
            to=to if has_pivot else None,
            spec=effective_spec,
            not_found=not_found,
            on_ambiguous=on_ambiguous,
            resolver=resolver,
            on_missing=on_missing,
            known_systems=resolver.code_systems() if has_pivot else None,
        )

    # After assembling values, check whether every RESOLVED row came back None.
    # Warn only when the column is wholly empty among resolved rows — a partial
    # miss (some resolved rows have a value) is not warned.
    if spec_active and effective_spec is not None:
        n_resolved = n_missing = 0
        for r, v in zip(out_source, out_values, strict=True):
            if r.status == ResolutionStatus.RESOLVED:
                n_resolved += 1
                if v is None:
                    n_missing += 1
        if n_resolved > 0 and n_missing == n_resolved:
            chain_repr = [t.raw for t in effective_spec.chain]
            # stacklevel=4 points at Resolver.bulk for the direct path;
            # the module-level resolvekit.bulk convenience adds one more frame.
            warnings.warn(
                f"default output {chain_repr!r}: {n_missing} resolved value(s) "
                f"had no output (column wholly empty among resolved rows)",
                UserWarning,
                stacklevel=4,
            )

    scalar_to = (has_pivot or spec_active) and output == "series"

    if scalar_to:
        # Return the native shape directly — no BulkResult wrapper.
        return _build_native(
            out_values,
            kind,
            orig_index=orig_index,
            orig_name=orig_name,
            orig_polars_name=orig_polars_name,
            orig_keys=orig_keys,
        )

    if output == "record":
        # Series-of-struct: each element is a dict of per-row diagnostics.
        records = [
            _record_from_result(r, v)
            for r, v in zip(out_source, out_values, strict=True)
        ]
        native = _build_records_native(
            records,
            kind,
            orig_index=orig_index,
            orig_name=orig_name,
            orig_polars_name=orig_polars_name,
            orig_keys=orig_keys,
        )
        return BulkResult(values=native, source=out_source, kind=kind)

    if output == "frame":
        # Flat DataFrame: one column per record field, built column-oriented.
        frame_cols = _frame_columns_from_output(out_source, out_values)
        native = _build_frame_native(frame_cols, kind, orig_index=orig_index)
        return BulkResult(values=native, source=out_source, kind=kind)

    # Default: wrap the native series of pivot/result values in BulkResult.
    native = _build_native(
        out_values,
        kind,
        orig_index=orig_index,
        orig_name=orig_name,
        orig_polars_name=orig_polars_name,
        orig_keys=orig_keys,
    )
    return BulkResult(
        values=native,
        source=out_source,
        kind=kind,
    )


def _record_from_result(result: ResolutionResult, pivot_value: Any) -> dict[str, Any]:
    """Build the per-row record dict used by output='record' / 'frame'.

    When no pivot is active, ``pivot_value`` is the raw ``ResolutionResult``
    object.  We extract ``entity_id`` as a primitive rather than embedding the
    model — polars cannot store nested pydantic objects in a Struct Series.
    """
    if isinstance(pivot_value, ResolutionResult):
        # No pivot was applied; use entity_id as the scalar "value".
        value: Any = pivot_value.entity_id
    else:
        value = pivot_value
    return {
        "value": value,
        "status": result.status.value,
        "entity_id": result.entity_id,
        "confidence": result.confidence,
        "pack_id": result.pack_id,
        "query_text": result.query_text,
    }


def _build_records_native(
    records: list[dict[str, Any]],
    kind: _InputKind,
    *,
    orig_index: Any,
    orig_name: Any,
    orig_polars_name: str | None,
    orig_keys: list[str] | None = None,
) -> Any:
    """Series-of-dict assembly for ``output='record'``."""
    if kind == "pandas":
        import pandas as pd

        return pd.Series(records, index=orig_index, name=orig_name, dtype=object)
    if kind == "polars":
        import polars as pl

        # Let polars infer the struct dtype from records; bare pl.Struct raises.
        return pl.Series(name=orig_polars_name or "", values=records)
    if kind == "numpy":
        import numpy as np

        return np.array(records, dtype=object)
    if kind == "tuple":
        return tuple(records)
    if kind == "dict":
        # Project back to the same-keyed dict; orig_keys is always set for dict input.
        assert orig_keys is not None
        return dict(zip(orig_keys, records, strict=True))
    return records


def _frame_columns_from_output(
    out_source: list[ResolutionResult],
    out_values: list[Any],
) -> dict[str, list[Any]]:
    """Build column-oriented data for ``output='frame'`` without a N-dict intermediate."""
    col_value: list[Any] = []
    col_status: list[Any] = []
    col_entity_id: list[Any] = []
    col_confidence: list[Any] = []
    col_pack_id: list[Any] = []
    col_query_text: list[Any] = []
    for r, v in zip(out_source, out_values, strict=True):
        if isinstance(v, ResolutionResult):
            col_value.append(v.entity_id)
        else:
            col_value.append(v)
        col_status.append(r.status.value)
        col_entity_id.append(r.entity_id)
        col_confidence.append(r.confidence)
        col_pack_id.append(r.pack_id)
        col_query_text.append(r.query_text)
    return {
        "value": col_value,
        "status": col_status,
        "entity_id": col_entity_id,
        "confidence": col_confidence,
        "pack_id": col_pack_id,
        "query_text": col_query_text,
    }


def _build_frame_native(
    columns: dict[str, list[Any]],
    kind: _InputKind,
    *,
    orig_index: Any,
) -> Any:
    """DataFrame assembly for ``output='frame'``.

    Accepts column-oriented data (dict of column-name → value list) rather than
    a list-of-dicts, so no N-dict intermediate is ever allocated.

    For pandas/polars, returns a DataFrame.  For non-DataFrame inputs (list,
    tuple, numpy), falls back to a list-of-dicts to preserve existing behaviour.
    """
    if kind == "pandas":
        import pandas as pd

        return pd.DataFrame(columns, index=orig_index)
    if kind == "polars":
        import polars as pl

        return pl.DataFrame(columns)
    # Non-DataFrame kinds: reconstruct list-of-dicts for backward compatibility.
    col_names = list(columns)
    col_lists = [columns[k] for k in col_names]
    return [
        dict(zip(col_names, row, strict=True)) for row in zip(*col_lists, strict=True)
    ]


def _build_native(
    values: list[Any],
    kind: _InputKind,
    *,
    orig_index: Any,
    orig_name: Any,
    orig_polars_name: str | None,
    orig_keys: list[str] | None = None,
) -> Any:
    """Assemble the per-row *values* back into the user's native flavor."""
    if kind == "pandas":
        import pandas as pd

        return pd.Series(values, index=orig_index, name=orig_name, dtype=object)
    if kind == "polars":
        import polars as pl

        return pl.Series(name=orig_polars_name or "", values=values, dtype=pl.Object)
    if kind == "numpy":
        import numpy as np

        return np.array(values, dtype=object)
    if kind == "tuple":
        return tuple(values)
    if kind == "dict":
        # Project resolved values back to the same-keyed dict; orig_keys always set.
        assert orig_keys is not None
        return dict(zip(orig_keys, values, strict=True))
    return values  # list
