"""Pandas Series accessor registration — opt-in via ``import resolvekit.pandas``.

Importing ``resolvekit.pandas`` registers the ``resolvekit``
accessor on ``pd.Series``.

Call site::

    import resolvekit.pandas          # registers the accessor
    s.resolvekit.resolve(to="iso3")   # → pd.Series[str]
"""

from __future__ import annotations

_REGISTERED: bool = False


def register() -> None:
    """Register the ``resolvekit`` pandas Series accessor (idempotent)."""
    global _REGISTERED
    if _REGISTERED:
        return

    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "The pandas integration requires pandas. "
            "Install it with: pip install 'resolvekit[pandas]'"
        ) from exc

    @pd.api.extensions.register_series_accessor("resolvekit")
    class _ResolveKitSeriesAccessor:
        """Pandas Series accessor for resolvekit operations.

        Registered under ``pd.Series.resolvekit``.  Activate by importing
        ``resolvekit.pandas`` once at the top of your module.

        Examples::

            import resolvekit.pandas
            df["iso3"] = df["country"].resolvekit.resolve(to="iso3")
            df["resolved"] = df["country"].resolvekit.bulk()
        """

        def __init__(self, series: pd.Series) -> None:
            self._series = series

        def resolve(
            self,
            *,
            to: str,
            domain: str | list[str] | None = None,
            from_system: str | None = None,
            not_found: str = "null",
            on_error: str = "raise",
            on_ambiguous: str = "null",
        ) -> pd.Series:
            """Resolve the Series and pivot to a code or attribute.

            Shorthand for ``.bulk(to=to, ...)``.  Returns a ``pd.Series`` of
            pivoted values in the same index/name as the original.

            Args:
                to: Target pivot (e.g. ``"iso3"``, ``"flag"``, ``"name"``).
                domain: Optional domain filter.
                from_system: Force code-system for lookup.
                not_found: ``"null"`` (default), ``"raise"``, or sentinel string.
                on_error: ``"raise"`` (default), ``"null"``, or ``"keep"``.
                    Controls what happens when a per-row resolution raises an
                    unexpected error.  ``"raise"`` propagates the exception;
                    ``"null"`` silently returns ``None``; ``"keep"`` returns the
                    original input string.
                on_ambiguous: ``"null"`` (default), ``"raise"``, or ``"best"``.

            Returns:
                ``pd.Series`` of pivot values, aligned to the input Series.
            """
            return self.bulk(  # type: ignore[return-value]
                to=to,
                domain=domain,
                from_system=from_system,
                not_found=not_found,
                on_error=on_error,
                on_ambiguous=on_ambiguous,
            )

        def bulk(
            self,
            *,
            to: str | None = None,
            output: str = "series",
            domain: str | list[str] | None = None,
            from_system: str | None = None,
            not_found: str = "null",
            on_error: str = "raise",
            on_ambiguous: str = "null",
        ) -> object:
            """Run bulk resolution on the Series.

            Delegates to :func:`resolvekit.bulk` with ``values=self._series``.

            Args:
                to: Optional pivot target.
                output: ``"series"`` (default), ``"record"`` (Series-of-struct),
                    or ``"frame"`` (DataFrame).  Forwarded straight through to
                    the underlying dispatch.
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
                Native ``pd.Series`` when ``to`` is a scalar, or
                :class:`~resolvekit.core.model.bulk_result.BulkResult`
                otherwise.
            """
            from resolvekit._convenience import _get_default
            from resolvekit.core.api.bulk import _bulk_dispatch

            return _bulk_dispatch(
                resolver=_get_default(),
                values=self._series,
                to=to,
                output=output,
                domain=domain,
                context=None,
                from_system=from_system,
                not_found=not_found,
                on_error=on_error,
                on_ambiguous=on_ambiguous,
            )

    _REGISTERED = True
