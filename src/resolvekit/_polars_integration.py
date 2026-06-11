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
            from resolvekit.core.api.bulk import _bulk_dispatch
            from resolvekit.core.api.loading.paths import _normalize_domain
            from resolvekit.core.errors import UnknownDomainError

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
            if domain is not None:
                norm_domain = _normalize_domain(domain)
                if norm_domain is not None:
                    available = resolver._runner.available_packs
                    if available:
                        unknown = sorted(norm_domain - available)
                        if unknown:
                            raise UnknownDomainError(unknown, sorted(available))

            def _apply(series: pl.Series) -> pl.Series:
                result = _bulk_dispatch(
                    resolver=resolver,
                    values=series,
                    to=to,
                    output="series",
                    domain=domain,
                    context=None,
                    from_system=from_system,
                    not_found=not_found,
                    on_error=on_error,
                    on_ambiguous=on_ambiguous,
                )
                vals = (
                    result.to_list() if isinstance(result, pl.Series) else list(result)
                )
                return pl.Series(values=vals, dtype=pl.String)

            return self._expr.map_batches(_apply, return_dtype=pl.String)

    _REGISTERED = True
