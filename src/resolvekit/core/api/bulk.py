"""``_bulk_dispatch`` — batch resolution with native-shape dispatch.

Returns the user's native shape directly when ``to=`` is a scalar pivot or
a spec is active with ``output="series"``, or a
:class:`~resolvekit.core.model.bulk_result.BulkResult` otherwise.

The public surface lives at :func:`resolvekit.bulk` (convenience layer) and
:meth:`Resolver.bulk`; both delegate here.
"""

from __future__ import annotations

import difflib
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _closest_match(value: str, choices: tuple[str, ...]) -> str | None:
    """Return the closest match to *value* from *choices*, or None."""
    matches = difflib.get_close_matches(value, choices, n=1, cutoff=0.6)
    return matches[0] if matches else None


# ---------------------------------------------------------------------------
# Module-level sentinels for the crosswalk short-circuit
# ---------------------------------------------------------------------------

# _IGNORE_RESULT: placed in unique_results[i] for IGNORE entries so that
# _assemble_output can bypass _apply_not_found unconditionally.
_IGNORE_RESULT: ResolutionResult = ResolutionResult(
    status=ResolutionStatus.NO_MATCH,
    reasons=[ReasonCode.SENTINEL_BLOCKED],
)

# ---------------------------------------------------------------------------
# Input-kind detection
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Dedup helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Null handling helpers
# ---------------------------------------------------------------------------


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
            candidates=[],
            message=f"no match for {original!r}",
        )
    if not_found == "null":
        return None
    return not_found  # literal sentinel string


# ---------------------------------------------------------------------------
# Pivot helper
# ---------------------------------------------------------------------------


def _pivot_result(
    result: ResolutionResult,
    to: Any,
    *,
    spec: OutputSpec | None,
) -> Any:
    """Apply pivoting when *result* is RESOLVED; else return as-is.

    On the **spec path** (``spec is not None``), calls ``apply_output`` with
    ``scalar=False`` — per-entity misses return ``None`` and never raise
    (batch-safe).  When the spec carries ``on_missing="raise"``, ``apply_output``
    raises ``OutputMissingError`` on the first wholly-missing entity; the
    exception propagates out, aborting the batch.

    On the **explicit-to path** (``spec is None``), calls ``dispatch_pivot``
    with ``UnknownCodeSystemError`` re-raise — a typo'd code system still
    surfaces loudly (every row would silently return None otherwise).
    Per-entity misses return None.
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
        raise
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Flatten helper
# ---------------------------------------------------------------------------


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
            None if pd.isna(v) else str(v) for v in raw.astype(object)
        ]
    elif kind == "polars":
        orig_polars_name = raw.name
        items = [None if v is None else str(v) for v in raw.to_list()]
    elif kind == "numpy":
        import numpy as np

        items = [
            None if (v is None or (isinstance(v, float) and np.isnan(v))) else str(v)
            for v in raw.tolist()
        ]
    elif kind == "dict":
        orig_keys = list(raw.keys())
        items = [None if v is None else str(v) for v in raw.values()]
    elif kind == "tuple":
        items = [None if v is None else str(v) for v in raw]
    else:  # list
        items = [None if v is None else str(v) for v in raw]

    return items, orig_index, orig_name, orig_polars_name, orig_keys


# ---------------------------------------------------------------------------
# Resolve-uniques helper
# ---------------------------------------------------------------------------


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
    entirely.  For a mapped value the synthetic RESOLVED result (or the
    ``_IGNORE_RESULT`` sentinel for IGNORE entries) is placed directly in
    ``unique_results`` so the broadcast in ``_assemble_output`` carries it
    correctly without a second write.  Unknown entity-ids under ``strict=True``
    raise ``CrosswalkError`` before the remainder is resolved.

    Uses the code-input short-circuit when all *to-resolve* uniques look like
    codes or ``from_system`` is set; otherwise dispatches to
    ``_resolve_many_internal``.
    """
    # --- crosswalk pre-filter -------------------------------------------------
    unique_results: list[ResolutionResult | None] = [None] * len(uniques)
    to_resolve_idx: list[int] = []
    offenders: list[str] = []

    for i, u in enumerate(uniques):
        hit = crosswalk._get(u) if crosswalk is not None else _MISSING
        if hit is _MISSING:
            # Not in the crosswalk — resolve normally.
            to_resolve_idx.append(i)
            continue
        if hit is None:
            # IGNORE entry — place the sentinel; never reaches _apply_not_found.
            unique_results[i] = _IGNORE_RESULT
            continue
        # Crosswalk hit: apply-time existence check via the runner (one read per unique).
        # hit is str here (not _MISSING, not None) — ty doesn't narrow through `is`.
        eid: str = hit  # ty: ignore[invalid-assignment]  # type: ignore[assignment]
        entity = resolver._runner.get_entity(eid)  # type: ignore[union-attr]
        if entity is None:
            offenders.append(eid)
            unique_results[i] = ResolutionResult(
                status=ResolutionStatus.NO_MATCH,
                query_text=u,
                reasons=[ReasonCode.SENTINEL_BLOCKED],
            )
            continue
        # Entity found — synthetic RESOLVED result with entity attached.
        unique_results[i] = ResolutionResult(
            status=ResolutionStatus.RESOLVED,
            entity_id=eid,
            entity=entity,
            query_text=u,
            reasons=[ReasonCode.EXACT_CODE_MATCH],
        )

    # Fail fast on unknown ids when strict mode is active.
    if crosswalk is not None and crosswalk.strict and offenders:
        raise CrosswalkError(offenders)

    # --- resolve the non-crosswalked subset -----------------------------------
    to_resolve = [uniques[i] for i in to_resolve_idx]

    # use_code_path detection runs over the to-resolve subset only — never
    # the full uniques list, so a fully-crosswalked batch doesn't mis-route the
    # empty remainder through the code path.
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
                        reasons=[ReasonCode.INTERNAL_ERROR],
                    )
                else:  # keep — pass through original input string as query_text
                    r = ResolutionResult(
                        status=ResolutionStatus.NO_MATCH,
                        reasons=[ReasonCode.INTERNAL_ERROR],
                        query_text=u,
                    )
            resolved_subset.append(r)
    elif to_resolve:
        # Batch resolve via resolve_many (with include_entity when pivoting).
        try:
            from resolvekit.core.api.loading import _normalize_domain

            norm_domain = _normalize_domain(domain)
            if norm_domain is not None:
                available = resolver._runner.available_packs
                if available:
                    unknown = sorted(norm_domain - available)
                    if unknown:
                        raise UnknownDomainError(unknown, sorted(available))

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
                reasons=[ReasonCode.INTERNAL_ERROR],
            )
            resolved_subset = [_batch_sentinel] * len(to_resolve)
    else:
        resolved_subset = []

    # Scatter resolved results back at their original unique indices.
    for list_pos, orig_idx in enumerate(to_resolve_idx):
        unique_results[orig_idx] = resolved_subset[list_pos]

    # All slots must be filled now (None would only remain if there's a logic bug).
    return unique_results  # ty: ignore[invalid-return-type]  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Assemble-output helper
# ---------------------------------------------------------------------------


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
) -> tuple[list[Any], list[ResolutionResult]]:
    """Apply not_found / on_ambiguous contracts, pivot, and broadcast to original order.

    Returns ``(out_values, out_source)``.  The lazy entity fetch for the
    ``on_ambiguous="best"`` promoted path runs inside the per-unique loop —
    not the broadcast loop — so each entity is fetched at most once.

    When ``spec`` is set, pivoting goes through ``apply_output`` (batch-safe:
    per-entity misses return None, never raise — unless ``on_missing="raise"``
    in the spec, which propagates on the first miss and aborts the batch).
    When ``spec`` is None and ``to`` is not None, the explicit-``to`` path
    uses ``dispatch_pivot`` with ``UnknownCodeSystemError`` re-raise.
    """
    # Shared sentinel for null-input rows — allocated once, reused for all nulls.
    _null_sentinel = ResolutionResult(
        status=ResolutionStatus.NO_MATCH,
        reasons=[ReasonCode.INVALID_QUERY],
    )

    # Whether pivoting is active on this call (either explicit to= or spec path).
    pivoting = spec is not None or to is not None

    unique_out: list[Any] = []  # pivot result per unique (len == len(uniques))
    for i, r in enumerate(unique_results):
        if r is _IGNORE_RESULT:
            # IGNORE entry: unconditional None, bypassing _apply_not_found
            # (so not_found="raise" never fires on a crosswalk IGNORE).
            unique_out.append(None)
            continue
        coerced = _apply_not_found(r, uniques[i], not_found, on_ambiguous)
        if coerced is None or isinstance(coerced, str):
            unique_out.append(coerced)
        elif hasattr(coerced, "status"):
            # Still a ResolutionResult (RESOLVED or "best" path).
            # When on_ambiguous="best" promotes an AMBIGUOUS result, the synthetic
            # RESOLVED result has entity_id set but entity=None.  Fetch the entity
            # lazily so that pivot dispatch works correctly.
            if pivoting and coerced.entity is None and coerced.entity_id is not None:
                fetched = resolver._runner.get_entity(coerced.entity_id)
                if fetched is not None:
                    coerced = coerced.model_copy(update={"entity": fetched})
            unique_out.append(
                _pivot_result(coerced, to, spec=spec) if pivoting else coerced
            )
        else:
            unique_out.append(coerced)

    # Broadcast back to original order.
    # indexer[i] is None iff items[i] is None, so the null check is sufficient.
    out_values: list[Any] = []
    out_source: list[ResolutionResult] = []
    for idx, item in enumerate(items):
        if item is None:
            out_values.append(None)
            out_source.append(_null_sentinel)
        else:
            ui = indexer[idx]  # invariant: item is not None → ui is not None
            if ui is not None:  # mypy narrowing
                out_values.append(unique_out[ui])
                out_source.append(unique_results[ui])

    return out_values, out_source


# ---------------------------------------------------------------------------
# Core dispatch — invoked by Resolver.bulk() and the convenience layer.
# ---------------------------------------------------------------------------


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
            raises ``OutputMissingError`` on the first resolved-but-missing entity,
            aborting the batch.  ``"null"`` forces null silently.  Only applies on
            the spec path.
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
    uniques, indexer = _dedup_list(items)

    # Effective-pivot detection:
    #   has_pivot    — caller passed an explicit to= (not UNSET, not None)
    #   spec_active  — to= was omitted (UNSET) and an output_spec is provided
    has_pivot = to is not _UNSET and to is not None
    spec_active = to is _UNSET and output_spec is not None

    # When pivoting (either path), we need entities hydrated.
    include_entity_for_call = has_pivot or spec_active

    # Build the effective spec for this call.
    # On the spec path, honour the per-call on_missing override.  The chain is
    # already validated; construct a new frozen OutputSpec directly rather than
    # re-running compile_output_spec (which would re-validate code systems).
    effective_spec: OutputSpec | None = None
    if spec_active and output_spec is not None:
        if on_missing != output_spec.on_missing:
            effective_spec = OutputSpec(
                chain=output_spec.chain,
                on_missing=_coerce_on_missing(on_missing),
            )
        else:
            effective_spec = output_spec

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
    )

    # ---------------------------------------------------------------------------
    # Empty-column warning (spec path only)
    # ---------------------------------------------------------------------------
    # After assembling values, check whether every RESOLVED row came back None.
    # Warn only when the column is wholly empty among resolved rows — a partial
    # miss (some resolved rows have a value) is not warned.
    if spec_active and effective_spec is not None:
        resolved_indices = [
            i for i, r in enumerate(out_source) if r.status == ResolutionStatus.RESOLVED
        ]
        if resolved_indices:
            n_missing = sum(1 for i in resolved_indices if out_values[i] is None)
            if n_missing > 0 and n_missing == len(resolved_indices):
                chain_repr = [t.raw for t in effective_spec.chain]
                # stacklevel=4 points at Resolver.bulk for the direct path;
                # the module-level resolvekit.bulk convenience adds one more frame.
                warnings.warn(
                    f"default output {chain_repr!r}: {n_missing} resolved value(s) "
                    f"had no output (column wholly empty among resolved rows)",
                    UserWarning,
                    stacklevel=4,
                )

    # ---------------------------------------------------------------------------
    # Decide return shape
    # ---------------------------------------------------------------------------
    # Return a native series (not BulkResult) when pivoting and output="series".
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
        # Flat DataFrame: one column per record field.
        records = [
            _record_from_result(r, v)
            for r, v in zip(out_source, out_values, strict=True)
        ]
        native = _build_frame_native(records, kind, orig_index=orig_index)
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

        # Let polars infer the struct dtype from the records — passing
        # bare `pl.Struct` (the dtype class, not a fully-specified
        # `pl.Struct({...})` schema) raises in polars 0.20+.
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


def _build_frame_native(
    records: list[dict[str, Any]],
    kind: _InputKind,
    *,
    orig_index: Any,
) -> Any:
    """DataFrame assembly for ``output='frame'``.

    For pandas/polars, returns a DataFrame.  For non-DataFrame inputs (list,
    tuple, numpy), falls back to the same list-of-dicts representation as
    ``output='record'``.
    """
    if kind == "pandas":
        import pandas as pd

        return pd.DataFrame.from_records(records, index=orig_index)
    if kind == "polars":
        import polars as pl

        return pl.DataFrame(records)
    return records


# ---------------------------------------------------------------------------
# Native shape assembly
# ---------------------------------------------------------------------------


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
