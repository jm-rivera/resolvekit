"""Typed info object returned by ``Resolver.info`` property.

``build_resolver_info`` assembles a ``ResolverInfo`` from the plain data that
``Resolver.info`` gathers from ``self``; it is unit-testable without a full
``Resolver`` instance.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from resolvekit.core.model._repr import escape, next_container_id


class ResolverInfo(BaseModel):
    """Structured information about a ``Resolver`` instance.

    Returned by the ``Resolver.info`` property; fields are read as attributes.

    Attributes:
        domains: Sorted tuple of loaded domain pack IDs.
        routing_mode: Router mode string (``"auto"``, ``"explicit"``,
            ``"hybrid"``).
        max_query_length: Maximum query length before truncation.
        closed: Whether the resolver has been closed.
        resolvekit_version: Installed library version string.
        data_versions: Nested mapping
            ``{pack_id: {module_id: {datapack_id, data_version,
            build_timestamp}}}``.
        data_version: Summary CalVer across all loaded modules (first
            non-None found in alphabetical order), or ``None`` when no
            modules are loaded.
        cache: Cache statistics snapshot, or ``None`` when the query
            cache is off.
        modules: Catalog of all installed modules, populated from the
            manifest on each ``info`` access.  Empty tuple when the manifest
            cannot be read.
    """

    model_config = ConfigDict(frozen=True)

    domains: tuple[str, ...]
    routing_mode: str
    max_query_length: int
    closed: bool
    resolvekit_version: str
    data_versions: dict[str, dict[str, dict[str, str | None]]]
    data_version: str | None
    cache: Any  # CacheInfo | None — avoid circular import at model-define time
    modules: tuple[Any, ...] = ()  # tuple[ModuleInfo, ...] — avoid circular import

    def __repr__(self) -> str:
        ver = self.data_version or "unknown"
        return (
            f"ResolverInfo(domains={list(self.domains)!r}, "
            f"data_version={ver!r}, "
            f"routing_mode={self.routing_mode!r}, "
            f"closed={self.closed})"
        )

    def _repr_html_(self) -> str:
        """Rich HTML rendering for Jupyter notebooks with sklearn-scoped CSS.

        User-supplied strings (``data_version``, ``resolvekit_version``,
        domain ids) are HTML-escaped before interpolation.
        """
        container_id = next_container_id("rk-info")
        scope = f"#{container_id} >"

        rows: list[str] = []

        def _row(key: str, val: str) -> str:
            return f"<tr><th>{escape(key)}</th><td>{escape(val)}</td></tr>"

        rows.append(_row("resolvekit_version", self.resolvekit_version))
        rows.append(_row("data_version", self.data_version or "<none>"))
        rows.append(_row("routing_mode", self.routing_mode))
        rows.append(_row("max_query_length", str(self.max_query_length)))
        rows.append(_row("closed", str(self.closed).lower()))

        if self.domains:
            rows.append(_row("domains", ", ".join(self.domains)))

        if self.cache is not None:
            rows.append(
                _row(
                    "cache",
                    f"hits={self.cache.hits} misses={self.cache.misses} "
                    f"size={self.cache.currsize}/{self.cache.maxsize}",
                )
            )
        else:
            rows.append(_row("cache", "off"))

        rows_html = "\n".join(rows)
        return f"""
<div id="{container_id}">
<style>
  {scope} table.rk-info {{
    border-collapse: collapse;
    font-family: monospace;
    font-size: 0.9em;
  }}
  {scope} table.rk-info th {{
    text-align: left;
    padding: 2px 8px 2px 0;
    color: #666;
    font-weight: normal;
  }}
  {scope} table.rk-info td {{
    padding: 2px 4px;
  }}
  {scope} table.rk-info tr:nth-child(even) td {{
    background: #f7f7f7;
  }}
</style>
<table class="rk-info">
{rows_html}
</table>
</div>
"""


# ---------------------------------------------------------------------------
# build_resolver_info
# ---------------------------------------------------------------------------


def build_resolver_info(
    *,
    domains: tuple[str, ...],
    routing_mode: str,
    max_query_length: int,
    closed: bool,
    resolvekit_version: str,
    loaded_modules: dict[str, list[Any]],
    data_version: str | None,
    cache_info: Any,
    modules_catalog: tuple[Any, ...],
) -> ResolverInfo:
    """Assemble a ``ResolverInfo`` from plain resolver state data.

    Extracted from ``Resolver.info`` so the assembly logic is unit-testable
    without constructing a full ``Resolver``.  The ``Resolver.info`` property
    reads ``self.*``, calls ``_summary_data_version()``, and delegates here.

    Args:
        domains: Sorted tuple of loaded domain pack IDs.
        routing_mode: Router mode string (e.g. ``"auto"``, ``"explicit"``).
        max_query_length: Maximum query length before truncation.
        closed: Whether the resolver has been closed.
        resolvekit_version: Installed library version string.
        loaded_modules: The resolver's ``_loaded_modules`` dict
            (``{pack_id: [LoadedDataPack, ...]}``) used to build
            ``data_versions``.
        data_version: Summary CalVer across all loaded modules (or ``None``).
        cache_info: ``CacheInfo`` snapshot, or ``None`` when cache is off.
        modules_catalog: Tuple of ``ModuleInfo`` from the manifest, or empty.

    Returns:
        A fully constructed :class:`ResolverInfo`.
    """
    data_versions: dict[str, dict[str, dict[str, str | None]]] = {}
    for pack_id, modules in loaded_modules.items():
        data_versions[pack_id] = {
            module.module_id: {
                "datapack_id": module.metadata.datapack_id,
                "data_version": module.metadata.data_version,
                "build_timestamp": module.metadata.build_timestamp,
            }
            for module in modules
        }

    return ResolverInfo(
        domains=domains,
        routing_mode=routing_mode,
        max_query_length=max_query_length,
        closed=closed,
        resolvekit_version=resolvekit_version,
        data_versions=data_versions,
        data_version=data_version,
        cache=cache_info,
        modules=modules_catalog,
    )
