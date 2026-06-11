"""HTML and repr rendering for ResolutionResult and ResolutionResultList.

All presentation helpers from ``model/result.py`` live here as free functions.
``result.py`` imports this module lazily (function-local) to avoid a cycle:
``explain`` already imports ``model``, so a module-level import would be circular.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from resolvekit.core.model._repr import escape, next_container_id, scoped_table

if TYPE_CHECKING:
    from resolvekit.core.model.result import (
        RefinementHint,
        ResolutionResult,
        ResolutionResultList,
        ResolutionStatus,
    )

_COUNTRY_CODE_RE = re.compile(r"[-/]([A-Z]{2})(?:[-/]|$)")

_STATUS_COLORS: dict[str, str] = {
    "resolved": "#22c55e",
    "ambiguous": "#f59e0b",
    "no_match": "#ef4444",
    "error": "#ef4444",
}


def status_badge_html(status: ResolutionStatus) -> str:
    """Render a colored status badge as an HTML span."""
    color = _STATUS_COLORS.get(status.value, "#6b7280")
    return (
        f'<span style="background:{color};color:white;padding:2px 8px;'
        f'border-radius:4px;font-size:0.85em">{status.value}</span>'
    )


def did_you_mean_lines(result: ResolutionResult) -> str | None:
    """Build ``resolvekit.resolve(text=...)`` lines from candidate names.

    Returns one line per unique candidate canonical_name (excluding the
    original query_text), joined with ``"\\n  "``.  Used by both the AMBIGUOUS
    disambiguation path and the NO_MATCH DID_YOU_MEAN refinement path.
    """
    names = [c.canonical_name for c in result.candidates if c.canonical_name]
    unique_names = [n for n in dict.fromkeys(names) if n != result.query_text]
    if not unique_names:
        return None
    lines = [f"resolvekit.resolve(text={n!r})" for n in unique_names]
    return "\n  ".join(lines)


def render_refinement_hint(  # noqa: PLR0911 (per-hint dispatch is naturally branchy)
    result: ResolutionResult, hint: RefinementHint
) -> str | None:
    """Map one RefinementHint value to a runnable resolve() argument string.

    Returns None when the hint is present but no actionable data exists to
    produce a concrete or placeholder line (e.g. ENTITY_TYPES with no
    candidate carrying an entity_type).
    """
    from resolvekit.core.model.result import RefinementHint

    qt = result.query_text
    if qt is None:
        return None
    prefix = f"resolvekit.resolve(text={qt!r}, "

    if hint == RefinementHint.ENTITY_TYPES:
        entity_type = next(
            (c.entity_type for c in result.candidates if c.entity_type), None
        )
        if entity_type is None:
            return None
        return f"{prefix}context=ResolutionContext(entity_types={{{entity_type!r}}}))"

    if hint == RefinementHint.COUNTRY:
        # Infer ISO-2 from candidate entity_id / pack_id; placeholder when absent.
        country = next(
            (
                m.group(1)
                for c in result.candidates
                for field in (c.pack_id, c.entity_id)
                if field
                if (m := _COUNTRY_CODE_RE.search(field.upper()))
            ),
            None,
        )
        placeholder = country or "<your-iso2>"
        return f'{prefix}context=ResolutionContext(country="{placeholder}"))'

    if hint == RefinementHint.PARENT_IDS:
        entity_id = next((c.entity_id for c in result.candidates), None)
        placeholder = entity_id if entity_id else "<parent-entity-id>"
        return f'{prefix}context=ResolutionContext(parent_ids=["{placeholder}"]))'

    if hint == RefinementHint.LANGUAGES:
        return f'{prefix}context=ResolutionContext(languages=["<bcp47>"]))'

    if hint == RefinementHint.DID_YOU_MEAN:
        return did_you_mean_lines(result)

    return None


def refinement_hint(result: ResolutionResult) -> str | None:
    """Return a runnable resolve() line based on refinement_hints.

    Considers ``result.refinement_hints`` in priority order (ENTITY_TYPES →
    COUNTRY → PARENT_IDS → LANGUAGES → DID_YOU_MEAN); returns the first
    hint that maps to a non-trivial, runnable line.  Returns None when no
    hint is actionable, or when query_text / refinement_hints are absent.
    """
    from resolvekit.core.model.result import _REFINEMENT_HINT_PRIORITY

    if result.query_text is None:
        return None
    if not result.refinement_hints:
        return None

    hints_set = set(result.refinement_hints)
    for hint in _REFINEMENT_HINT_PRIORITY:
        if hint not in hints_set:
            continue
        line = render_refinement_hint(result, hint)
        if line is not None:
            return line
    return None


def disambiguate_hint(result: ResolutionResult) -> str | None:
    """Return a runnable disambiguation hint when query_text is available.

    Prefer exact-name selectors (one ``resolve()`` call per candidate
    canonical name) — they're the most precise proven fix and avoid
    accidentally narrowing to a single outlier type. Only fall back to a
    type narrowing when no canonical names are available, and even then,
    only suggest it if filtering by a single type would actually reduce
    the candidate set to one.
    """
    if result.query_text is None:
        return None
    lines = did_you_mean_lines(result)
    if lines is not None:
        return lines
    type_buckets: dict[str, int] = {}
    for c in result.candidates:
        if c.entity_type:
            type_buckets[c.entity_type] = type_buckets.get(c.entity_type, 0) + 1
    disambiguating_type = next((t for t, n in type_buckets.items() if n == 1), None)
    if disambiguating_type is not None:
        return (
            f"resolvekit.resolve(text={result.query_text!r}, "
            f"context=ResolutionContext(entity_types={{{disambiguating_type!r}}}))"
        )
    return None


def result_repr_html(result: ResolutionResult) -> str:
    """Rich HTML rendering for Jupyter notebooks with sklearn-scoped CSS.

    Each call gets a unique container ID (``rk-result-N``) so styles
    from one cell never bleed into another.  All user-supplied strings
    are HTML-escaped before interpolation.
    """
    from resolvekit.core.model.result import ResolutionStatus

    badge = status_badge_html(result.status)
    table_rows: list[str] = [f"<tr><th>status</th><td>{badge}</td></tr>"]
    if result.entity_id:
        table_rows.append(
            f"<tr><th>entity</th><td><code>{escape(result.entity_id)}</code></td></tr>"
        )
    if result.confidence is not None:
        table_rows.append(
            f"<tr><th>confidence</th><td>{result.confidence:.3f}</td></tr>"
        )
    if result.pack_id:
        table_rows.append(f"<tr><th>pack</th><td>{escape(result.pack_id)}</td></tr>")
    if result.candidates:
        names = ", ".join(
            escape(c.canonical_name or c.entity_id) for c in result.candidates[:5]
        )
        table_rows.append(
            f"<tr><th>candidates ({len(result.candidates)})</th><td>{names}</td></tr>"
        )
    if result.reasons:
        reasons = ", ".join(r.value for r in result.reasons)
        table_rows.append(f"<tr><th>reasons</th><td>{reasons}</td></tr>")
    if result.status == ResolutionStatus.AMBIGUOUS:
        hint = disambiguate_hint(result)
        if hint is not None:
            table_rows.append(
                f"<tr><th>disambiguate</th><td><code>{escape(hint)}</code></td></tr>"
            )
    rows_html = "\n".join(table_rows)
    return scoped_table(prefix="rk-result", rows_html=rows_html, css_class="rk-result")


def result_list_repr_html(result_list: ResolutionResultList) -> str:
    """Sklearn-scoped HTML rendering for Jupyter notebooks.

    Each call gets a unique container ID (``rk-resultlist-N``) so the
    ``rk-results`` table styles never leak across cells; user-supplied
    strings are HTML-escaped.
    """
    container_id = next_container_id("rk-resultlist")
    scope = f"#{container_id} >"

    rows = []
    for r in result_list:
        entity_id = escape(r.entity_id or "")
        conf = f"{r.confidence:.2f}" if r.confidence is not None else ""
        canonical = escape((r.entity.canonical_name if r.entity else None) or "")
        pack_id = escape(r.pack_id or "")
        sv = r.status.value
        rows.append(
            f"<tr>"
            f'<td class="rk-status rk-{sv}">{sv}</td>'
            f"<td>{entity_id}</td>"
            f"<td>{conf}</td>"
            f"<td>{canonical}</td>"
            f"<td>{pack_id}</td>"
            f"</tr>"
        )
    body = "\n".join(rows)
    rows_html = (
        "<thead><tr><th>status</th><th>entity_id</th><th>confidence</th>\n"
        f"<th>canonical_name</th><th>pack_id</th></tr></thead>\n"
        f"<tbody>{body}</tbody>"
    )
    extra_style = (
        f"  {scope} table.rk-results th {{\n    border-bottom: 1px solid #ddd;\n  }}"
    )
    return scoped_table(
        prefix="rk-resultlist",
        rows_html=rows_html,
        css_class="rk-results",
        extra_style=extra_style,
        _container_id=container_id,
    )
