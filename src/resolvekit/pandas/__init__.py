"""Opt-in pandas integration for resolvekit.

Importing this module registers the ``.resolvekit`` accessor on
``pd.Series``, enabling::

    import resolvekit.pandas
    df["iso3"] = df["country"].resolvekit.resolve(to="iso3")

The accessor is registered lazily and only once (idempotent).  It is
**never** auto-registered by the core ``resolvekit`` package — you must
import this module explicitly.
"""

from resolvekit._pandas_integration import register

register()

__all__: list[str] = []
