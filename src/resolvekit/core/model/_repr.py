"""Shared helpers for ``_repr_html_`` rendering across model classes.

Provides:

- ``escape``: ``html.escape`` re-export (bound for hot-path use).
- ``next_container_id(prefix)``: thread-safe unique container id under a
  caller-chosen prefix (e.g. ``rk-entity``, ``rk-result``, ``rk-bulk``).
- ``scoped_table(...)``: self-scoped ``<div><style>…</style><table>…</table></div>``
  with shared rk-table CSS parametrized by ``css_class``.

Distinct prefixes prevent CSS-id collisions when multiple repr types render
on the same notebook page.
"""

from __future__ import annotations

import itertools
from html import escape

__all__ = ["escape", "next_container_id", "scoped_table"]

_COUNTER: itertools.count[int] = itertools.count()


def next_container_id(prefix: str) -> str:
    """Return a unique container id of the form ``{prefix}-{N}``.

    All prefixes share a single global counter so two distinct prefixes
    can never produce a colliding id even within the same notebook page.
    """
    return f"{prefix}-{next(_COUNTER)}"


def scoped_table(
    *,
    prefix: str,
    rows_html: str,
    css_class: str,
    extra_style: str = "",
    _container_id: str | None = None,
) -> str:
    """Return a self-scoped ``<div id><style>…</style><table class>…</table></div>``.

    Generates a unique container id via ``next_container_id(prefix)``, emits the
    shared rk-table CSS block scoped under ``#{id} >`` and parametrized by
    ``css_class``, appends ``extra_style`` verbatim, and wraps ``rows_html`` in
    the table element.

    Args:
        prefix: Container-id prefix (e.g. ``"rk-result"``).
        rows_html: Inner HTML for the table (``<tr>``/``<thead>``/``<tbody>``/
            ``<caption>`` elements).
        css_class: CSS class applied to the ``<table>`` element.
        extra_style: Additional CSS rules appended verbatim inside the
            ``<style>`` block (use to carry per-site quirks such as scoped
            status-color selectors or per-section borders).
        _container_id: Internal — caller-supplied container id for sites that
            must pre-compute the id to build scoped ``extra_style`` rules.
            When ``None`` (the default), a new id is generated via
            ``next_container_id(prefix)``.
    """
    container_id = (
        _container_id if _container_id is not None else next_container_id(prefix)
    )
    scope = f"#{container_id} >"
    extra = f"\n{extra_style}" if extra_style else ""
    return f"""
<div id="{container_id}">
<style>
  {scope} table.{css_class} {{
    border-collapse: collapse;
    font-family: monospace;
    font-size: 0.9em;
  }}
  {scope} table.{css_class} th {{
    text-align: left;
    padding: 2px 8px 2px 0;
    color: #666;
    font-weight: normal;
  }}
  {scope} table.{css_class} td {{
    padding: 2px 4px;
  }}
  {scope} table.{css_class} tr:nth-child(even) td {{
    background: #f7f7f7;
  }}{extra}
</style>
<table class="{css_class}">
{rows_html}
</table>
</div>
"""
