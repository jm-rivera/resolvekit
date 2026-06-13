"""Polars Expr namespace registration — opt-in via ``import resolvekit.polars``.

Call :func:`register` once (idempotent) to attach the ``resolvekit``
expression namespace to Polars.

Call site::

    import resolvekit.polars                           # registers the namespace
    df.with_columns(
        pl.col("country").resolvekit.resolve(to="iso3")
    )
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from resolvekit.core.model import ResolutionContext

_REGISTERED: bool = False


def register() -> None:
    """Register the ``resolvekit`` polars Expr namespace (idempotent)."""
    global _REGISTERED
    if _REGISTERED:
        return

    try:
        import polars as pl
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "The polars integration requires polars. "
            "Install it with: pip install 'resolvekit[polars]'"
        ) from exc

    @pl.api.register_expr_namespace("resolvekit")
    class _ResolveKitExprNamespace:
        """Polars Expr namespace for resolvekit operations.

        Registered under ``pl.Expr.resolvekit``.  Activate by importing
        ``resolvekit.polars`` once at the top of your module.

        Examples::

            import resolvekit.polars
            df.with_columns(
                pl.col("country").resolvekit.resolve(to="iso3").alias("iso3")
            )
        """

        def __init__(self, expr: pl.Expr) -> None:
            self._expr = expr

        def resolve(
            self,
            *,
            to: str,
            domain: str | list[str] | None = None,
            context: ResolutionContext | dict | None = None,
            from_system: str | None = None,
            not_found: str = "null",
            on_error: str = "raise",
            on_ambiguous: str = "null",
        ) -> pl.Expr:
            """Resolve column values and pivot to a code or attribute.

            Evaluates the expression via ``map_batches`` (batched, not per-element)
            and returns an expression of the same shape.  For large batches, prefer
            ``rk.bulk(values=series, to=to)`` directly.

            Args:
                to: Target pivot (e.g. ``"iso3"``, ``"flag"``, ``"name"``).
                domain: Optional domain filter.
                context: Resolution hints, as a ``ResolutionContext`` or a plain ``dict``.
                    Dict shorthand keys: ``country`` (ISO alpha-2/alpha-3 or a country
                    name like ``"France"``), ``entity_types``, ``parent_ids``,
                    ``languages``, ``attributes`` (pack-specific escape hatch), and
                    ``as_of``. An empty dict is treated as no context. Unknown keys raise
                    ``UnknownContextKeyError`` listing the valid keys.
                    Dict values may be a ``pl.Expr`` or ``pl.Series`` for per-row context.
                from_system: Force code-system for lookup.
                not_found: ``"null"`` (default), ``"raise"``, or sentinel.
                on_error: ``"raise"`` (default), ``"null"``, or ``"keep"``.
                    Controls what happens when a per-row resolution raises an
                    unexpected error.  ``"raise"`` propagates the exception;
                    ``"null"`` silently returns ``None``; ``"keep"`` returns the
                    original input string.
                on_ambiguous: ``"null"`` (default), ``"raise"``, or ``"best"``.

            Returns:
                Polars ``Expr`` of pivot values.
            """
            from resolvekit._convenience import _get_default
            from resolvekit.core.api._pivot import validate_scalar_pivot
            from resolvekit.core.api.bulk import (
                _bulk_dispatch,
                _is_per_row_value,
                _validate_domain_available,
            )
            from resolvekit.core.api.context_input import (
                _VALID_CONTEXT_KEYS,
            )
            from resolvekit.core.errors import (
                UnknownContextKeyError,
            )

            # Validate on_error / on_ambiguous eagerly — these are caller mistakes
            # that must raise directly, not be swallowed inside map_batches.
            if on_error not in {"raise", "null", "keep"}:
                raise ValueError(
                    f"on_error={on_error!r} is not valid; "
                    "expected one of 'raise', 'null', 'keep'"
                )
            if on_ambiguous not in {"raise", "null", "best"}:
                raise ValueError(
                    f"on_ambiguous={on_ambiguous!r} is not valid; "
                    "expected one of 'raise', 'null', 'best'"
                )

            resolver = _get_default()

            # Validate to= eagerly so UnknownCodeSystemError propagates directly
            # rather than being mangled by polars's map_batches exception reconstruction.
            validate_scalar_pivot(to, available_code_systems=resolver.code_systems())

            # Validate domain eagerly so UnknownDomainError propagates directly
            # rather than being mangled by polars's map_batches exception reconstruction.
            _validate_domain_available(domain, resolver)

            # Eager context validation: unknown-key check and scalar country-name
            # coercion run before map_batches so errors surface with a clean traceback.
            # Per-row (Expr/Series) values are deferred — only their keys are checked here.
            _has_per_row_ctx = False
            _per_row_ctx_keys: list[str] = []  # keys with Expr/Series values
            _scalar_ctx: dict[str, object] = {}  # scalar context entries

            if isinstance(context, dict) and context:
                from typing import cast

                ctx_as_dict: dict[str, Any] = cast("dict[str, Any]", context)
                unknown = sorted(set(ctx_as_dict) - _VALID_CONTEXT_KEYS)
                if unknown:
                    from resolvekit.core.api.context_input import (
                        _VALID_CONTEXT_KEYS_SORTED,
                    )

                    raise UnknownContextKeyError(unknown, _VALID_CONTEXT_KEYS_SORTED)
                for k, v in ctx_as_dict.items():
                    if isinstance(v, (pl.Expr, pl.Series)) or _is_per_row_value(v):
                        _has_per_row_ctx = True
                        _per_row_ctx_keys.append(k)
                    else:
                        _scalar_ctx[k] = v

            if not _has_per_row_ctx:
                # Uniform context — simple closure, single map_batches.
                def _apply(series: pl.Series) -> pl.Series:
                    result = _bulk_dispatch(
                        resolver=resolver,
                        values=series,
                        to=to,
                        output="series",
                        domain=domain,
                        context=context,
                        from_system=from_system,
                        not_found=not_found,
                        on_error=on_error,
                        on_ambiguous=on_ambiguous,
                    )
                    vals = (
                        result.to_list()
                        if isinstance(result, pl.Series)
                        else list(result)
                    )
                    return pl.Series(values=vals, dtype=pl.String)

                return self._expr.map_batches(_apply, return_dtype=pl.String)

            # Per-row context path: pack value + per-row context columns into a
            # single struct so map_batches receives them aligned in one Series.
            # ctx_as_dict is always set here because _has_per_row_ctx is True.
            ctx_dict: dict[str, Any] = ctx_as_dict  # type: ignore[possibly-undefined]

            # Build a list of (field_name, Expr) for each per-row context key.
            ctx_exprs: list[pl.Expr] = []
            ctx_field_names: list[str] = []
            for k in _per_row_ctx_keys:
                v = ctx_dict[k]
                if isinstance(v, pl.Expr):
                    ctx_exprs.append(v.alias(f"__ctx_{k}"))
                elif isinstance(v, pl.Series):
                    ctx_exprs.append(pl.lit(v).alias(f"__ctx_{k}"))
                else:
                    # list / np.ndarray — convert to Series first
                    ctx_exprs.append(
                        pl.lit(pl.Series(values=list(v))).alias(f"__ctx_{k}")
                    )
                ctx_field_names.append(k)

            # Pack [value_col, ctx_col_0, ..., ctx_col_N] into a struct.
            struct_expr = pl.struct([self._expr.alias("__value__"), *ctx_exprs])

            def _apply_struct(struct_series: pl.Series) -> pl.Series:
                # Unpack struct fields column-oriented; avoids materialising N dicts.
                unpacked = struct_series.to_frame("__s").unnest("__s")
                value_list = unpacked["__value__"].to_list()

                # Build a per-row context dict where per-row keys map to lists.
                per_row_ctx: dict[str, object] = dict(_scalar_ctx)
                for k in ctx_field_names:
                    per_row_ctx[k] = unpacked[f"__ctx_{k}"].to_list()

                result = _bulk_dispatch(
                    resolver=resolver,
                    values=value_list,  # pass list directly; avoids a pl.Series → .to_list() round-trip in _flatten_input
                    to=to,
                    output="series",
                    domain=domain,
                    context=per_row_ctx,
                    from_system=from_system,
                    not_found=not_found,
                    on_error=on_error,
                    on_ambiguous=on_ambiguous,
                )
                vals = (
                    result.to_list() if isinstance(result, pl.Series) else list(result)
                )
                return pl.Series(values=vals, dtype=pl.String)

            return struct_expr.map_batches(_apply_struct, return_dtype=pl.String)

    _REGISTERED = True
