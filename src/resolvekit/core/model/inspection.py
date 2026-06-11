"""Diagnostic models for Resolver.inspect."""

import html

from pydantic import BaseModel, ConfigDict, Field

from resolvekit.core.model._repr import scoped_table


class InspectMatch(BaseModel):
    """One match record returned by Resolver.inspect."""

    model_config = ConfigDict(frozen=True)

    entity_id: str
    canonical_name: str | None = None
    pack_id: str | None = None
    entity_type: str | None = None
    matched_field: str | None = None
    matched_value: str | None = None


class InspectionReport(BaseModel):
    """Diagnostic snapshot of how a query is matched across known data.

    The structured fields are the stable contract. The string representation
    is for human display only and may change without a version bump.
    """

    model_config = ConfigDict(frozen=True)

    query: str
    normalized: str
    exact_code_matches: list[InspectMatch] = Field(default_factory=list)
    exact_name_matches: list[InspectMatch] = Field(default_factory=list)
    fuzzy_candidates: list[InspectMatch] = Field(default_factory=list, max_length=5)

    def as_text(self) -> str:
        """Return a one-line human-readable summary (for diagnostics, not a stable contract)."""
        if not self.query:
            return "inspect: no input"

        parts: list[str] = [f"query={self.query!r}"]

        if self.exact_code_matches:
            ids = ", ".join(m.entity_id for m in self.exact_code_matches[:3])
            parts.append(f"code_matches=[{ids}]")
        if self.exact_name_matches:
            ids = ", ".join(m.entity_id for m in self.exact_name_matches[:3])
            parts.append(f"name_matches=[{ids}]")
        if self.fuzzy_candidates:
            top = self.fuzzy_candidates[0]
            parts.append(f"closest_fuzzy={top.entity_id!r}")
        elif not self.exact_code_matches and not self.exact_name_matches:
            parts.append("no matches")

        return "inspect: " + "; ".join(parts)

    def _repr_html_(self) -> str:  # explicit by design
        """Rich HTML rendering for Jupyter notebooks.

        Mirrors the table styling used by ResolutionResult._repr_html_.
        Renders three small tables (one per match category); empty
        categories are omitted.
        """
        q = html.escape(self.query)
        n = html.escape(self.normalized)

        if not self.query:
            return '<div style="font-family:monospace;font-size:0.9em">inspect: no input</div>'

        header = (
            f'<div style="font-family:monospace;font-size:0.9em">'
            f"<div><b>Inspect:</b> <code>{q!r}</code> "
            f"(normalized: <code>{n!r}</code>)</div>"
        )

        sections: list[str] = []

        def _match_table(caption: str, matches: list[InspectMatch]) -> str:
            thead = (
                "<thead><tr>"
                "<th>entity_id</th><th>field</th><th>value</th><th>pack</th>"
                "</tr></thead>"
            )
            rows = []
            for m in matches:
                eid = html.escape(m.entity_id)
                field = html.escape(m.matched_field or "")
                value = html.escape(m.matched_value or "")
                pack = html.escape(m.pack_id or "")
                rows.append(
                    f"<tr>"
                    f"<td><code>{eid}</code></td>"
                    f"<td>{field}</td>"
                    f"<td>{value}</td>"
                    f"<td>{pack}</td>"
                    f"</tr>"
                )
            tbody = "<tbody>" + "".join(rows) + "</tbody>"
            rows_html = f"<caption><b>{caption}</b></caption>{thead}{tbody}"
            return scoped_table(
                prefix="rk-inspect", rows_html=rows_html, css_class="rk-inspect"
            )

        if self.exact_code_matches:
            sections.append(_match_table("Exact code matches", self.exact_code_matches))
        if self.exact_name_matches:
            sections.append(_match_table("Exact name matches", self.exact_name_matches))
        if self.fuzzy_candidates:
            sections.append(_match_table("Fuzzy candidates", self.fuzzy_candidates))

        body = "<div>no matches</div>" if not sections else "".join(sections)
        return header + body + "</div>"

    @property
    def summary(self) -> str:
        """One-line human summary (equivalent to ``str(report)``; IDE-discoverable alias)."""
        return self.as_text()

    def __str__(self) -> str:
        return self.as_text()
