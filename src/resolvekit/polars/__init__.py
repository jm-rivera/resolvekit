"""Opt-in polars integration for resolvekit.

Importing this module registers the ``resolvekit`` expression namespace on
Polars, enabling::

    import resolvekit.polars
    df.with_columns(
        pl.col("country").resolvekit.resolve(to="iso3").alias("iso3")
    )

The namespace is registered lazily and only once (idempotent).  It is
**never** auto-registered by the core ``resolvekit`` package — you must
import this module explicitly.
"""

from resolvekit._polars_integration import register

register()

__all__: list[str] = []
