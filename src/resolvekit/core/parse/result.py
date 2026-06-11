"""ParseResult — return type for parse() and parse_bulk().

``ParseResult`` wraps all ``ParsedEntity`` mentions detected in one call,
plus a ``dropped_spans`` debug channel for precision-gate rejections.

Modelled on ``BulkResult`` (``core/model/bulk_result.py``): mirrors
``summary()``, ``_repr_html_``, iteration, ``__len__``, and ``__getitem__``.

Key contracts:
- ``entities`` are ordered by ascending ``(row_idx, start)`` — the caller
  sorts before construction; ``ParseResult`` trusts that order.
- ``to_dataframe()`` is the ragged exploded shape: one row per entity.
  The ``row_idx`` column is included only when any entity carries a non-None
  ``row_idx`` (the ``parse_bulk`` path); it is omitted on the single-text
  ``parse()`` path where every ``row_idx`` is None.
- ``dropped_spans`` is always present (even if empty) as a debug channel.
  Use ``include_nil=True`` on the parse call to also surface NIL spans in
  ``entities``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple, overload

from resolvekit.core.model._repr import escape, next_container_id, scoped_table
from resolvekit.core.model.bulk_result import ResolutionSummary
from resolvekit.core.model.result import ResolutionResult, ResolutionStatus

if TYPE_CHECKING:
    import pandas as pd


class DroppedSpan(NamedTuple):
    """A detected span rejected by a precision gate before linking.

    Attributes:
        surface: The matched substring of the raw input.
        start: Start offset into the raw input string.
        end: End offset (exclusive) into the raw input string.
        pack_id: Pack that applied the gate.
        reason: Gate name, e.g. ``"short_input"``, ``"sentinel"``,
            ``"word_boundary"``, ``"below_threshold"``, ``"deny_list"``,
            ``"code_case_mismatch"``.
    """

    surface: str
    start: int
    end: int
    pack_id: str
    reason: str


@dataclass(slots=True, frozen=True)
class ParsedEntity:
    """One detected, linked (or NIL) mention with raw-input offsets.

    Attributes:
        surface: The matched substring of the RAW input (``raw[start:end]``).
        start: Start offset into the raw input string.
        end: End offset (exclusive) into the raw input string.
        entity_id: Linked entity id, or None for NIL spans.
        entity_type: Entity type of the link (e.g. ``"geo.country"``), or None.
        pack_id: Pack that produced the link (e.g. ``"geo"``), or None.
        status: RESOLVED / AMBIGUOUS / NO_MATCH (NIL).
        confidence: Calibrated confidence for emitted entities; near-miss float
            for NIL spans; None only for a NIL span the engine scored nothing for.
        resolution: Full ResolutionResult (candidates, provenance, ``.explain()``).
        row_idx: Row index for ``parse_bulk`` rows; None for single-text ``parse()``.
        output: Per-entity ``to=`` pivot value; None when no pivot is requested or
            for NIL spans. Populated by the output-pivot step; default None keeps
            the engine (which has no pivot knowledge) able to construct entities.
    """

    surface: str
    start: int
    end: int
    entity_id: str | None
    entity_type: str | None
    pack_id: str | None
    status: ResolutionStatus
    confidence: float | None
    resolution: ResolutionResult
    row_idx: int | None = None
    output: str | None = None


@dataclass(slots=True, frozen=True)
class ParseResult:
    """Outcome of ``parse()`` / ``parse_bulk()``: linked mentions + dropped-span debug channel.

    ``entities`` are ordered by ascending ``(row_idx, start)``.
    ``dropped_spans`` holds detected-then-gate-rejected spans for debugging
    (not emitted as entities, regardless of ``include_nil``).

    Attributes:
        entities: Linked (and, when ``include_nil=True``, NIL) mentions in
            input order.
        dropped_spans: Precision-gate rejections; always present, may be empty.
            These are distinct from NIL entities: a dropped span never made it
            to the linking step.
    """

    entities: list[ParsedEntity]
    dropped_spans: list[DroppedSpan]

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def summary(self) -> ResolutionSummary:
        """Return per-status counts for the detected mentions.

        Returns:
            :class:`~resolvekit.core.model.bulk_result.ResolutionSummary` with
            ``total``, ``resolved``, ``ambiguous``, ``no_match``, and ``error``
            counts.  ``error`` is typically 0 for parse results.
        """
        resolved = ambiguous = no_match = error = 0
        for e in self.entities:
            match e.status:
                case ResolutionStatus.RESOLVED:
                    resolved += 1
                case ResolutionStatus.AMBIGUOUS:
                    ambiguous += 1
                case ResolutionStatus.NO_MATCH:
                    no_match += 1
                case ResolutionStatus.ERROR:
                    error += 1
        return ResolutionSummary(
            total=len(self.entities),
            resolved=resolved,
            ambiguous=ambiguous,
            no_match=no_match,
            error=error,
        )

    # ------------------------------------------------------------------
    # Tabular export
    # ------------------------------------------------------------------

    def to_dataframe(self) -> pd.DataFrame:
        """Return entities as a pandas DataFrame (one row per entity).

        Column order: ``[row_idx,] surface, entity_id, entity_type, pack_id,
        status, confidence, start, end, to``.

        The ``row_idx`` column is included only when any entity has a non-None
        ``row_idx`` (the ``parse_bulk`` path).  On the single-text ``parse()``
        path every ``row_idx`` is None and the column is omitted to avoid
        noise.

        The ``to`` column holds :attr:`ParsedEntity.output` (per-entity pivot
        value; ``None`` when no ``to=`` argument was passed or for NIL spans).

        Returns:
            ``pandas.DataFrame`` with entities in the order they were stored.

        Raises:
            ImportError: If pandas is not installed.
        """
        try:
            import pandas as pd
        except ImportError as exc:
            raise ImportError(
                "to_dataframe() requires pandas. "
                "Install with: pip install 'resolvekit[pandas]'"
            ) from exc

        include_row_idx = any(e.row_idx is not None for e in self.entities)

        columns = ["row_idx"] if include_row_idx else []
        columns += [
            "surface",
            "entity_id",
            "entity_type",
            "pack_id",
            "status",
            "confidence",
            "start",
            "end",
            "to",
        ]

        records = []
        for e in self.entities:
            row: dict = {}
            if include_row_idx:
                row["row_idx"] = e.row_idx
            row["surface"] = e.surface
            row["entity_id"] = e.entity_id
            row["entity_type"] = e.entity_type
            row["pack_id"] = e.pack_id
            row["status"] = e.status.value
            row["confidence"] = e.confidence
            row["start"] = e.start
            row["end"] = e.end
            row["to"] = e.output
            records.append(row)

        if not records:
            return pd.DataFrame(columns=columns)

        return pd.DataFrame(records)

    # ------------------------------------------------------------------
    # Collection protocol
    # ------------------------------------------------------------------

    def __iter__(self):  # type: ignore[return]
        return iter(self.entities)

    def __len__(self) -> int:
        return len(self.entities)

    @overload
    def __getitem__(self, key: int) -> ParsedEntity: ...
    @overload
    def __getitem__(self, key: slice) -> list[ParsedEntity]: ...
    def __getitem__(self, key: int | slice) -> ParsedEntity | list[ParsedEntity]:
        return self.entities[key]

    # ------------------------------------------------------------------
    # Representations
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        s = self.summary()
        return (
            f"ParseResult(entities={s.total}, resolved={s.resolved}, "
            f"no_match={s.no_match}, dropped={len(self.dropped_spans)})"
        )

    def _repr_html_(self) -> str:
        """Scoped HTML with summary line and span table for Jupyter display.

        Each call gets a unique container ID (``rk-parse-N``) so styles from
        one cell never bleed into another.  All user-supplied strings are
        HTML-escaped before interpolation.  When ``dropped_spans`` is non-empty,
        appends a hint pointing users to ``include_nil=True``.
        """
        container_id = next_container_id("rk-parse")
        scope = f"#{container_id} >"

        s = self.summary()

        summary_html = (
            f"<p><b>ParseResult</b> — "
            f"total: {s.total} | "
            f"resolved: {s.resolved} | "
            f"no_match: {s.no_match} | "
            f"ambiguous: {s.ambiguous} | "
            f"dropped: {len(self.dropped_spans)}"
            f"</p>"
        )

        display_entities = self.entities[:10]
        row_htmls: list[str] = []
        for e in display_entities:
            surf = escape(e.surface)
            eid = escape(e.entity_id or "")
            etype = escape(e.entity_type or "")
            conf = f"{e.confidence:.2f}" if e.confidence is not None else ""
            pack = escape(e.pack_id or "")
            sv = e.status.value
            span = f"{e.start}:{e.end}"
            row_htmls.append(
                f"<tr>"
                f"<td>{surf}</td>"
                f"<td>{span}</td>"
                f"<td class='rk-s-{sv}'>{sv}</td>"
                f"<td>{eid}</td>"
                f"<td>{etype}</td>"
                f"<td>{conf}</td>"
                f"<td>{pack}</td>"
                f"</tr>"
            )
        if len(self.entities) > 10:
            row_htmls.append(
                f"<tr><td colspan='7'>… {len(self.entities) - 10} more rows</td></tr>"
            )

        rows_html = (
            "<thead><tr>"
            "<th>surface</th><th>span</th><th>status</th>"
            "<th>entity_id</th><th>entity_type</th><th>confidence</th><th>pack_id</th>"
            f"</tr></thead><tbody>{''.join(row_htmls)}</tbody>"
        )

        extra_style = (
            f"  {scope} table.rk-parse th {{\n"
            f"    border-bottom: 1px solid #ddd;\n"
            f"  }}\n"
            f"  {scope} .rk-s-resolved {{\n"
            f"    color: #22c55e;\n"
            f"  }}\n"
            f"  {scope} .rk-s-ambiguous {{\n"
            f"    color: #f59e0b;\n"
            f"  }}\n"
            f"  {scope} .rk-s-no_match {{\n"
            f"    color: #ef4444;\n"
            f"  }}\n"
            f"  {scope} .rk-s-error {{\n"
            f"    color: #ef4444;\n"
            f"  }}"
        )

        table_block = scoped_table(
            prefix="rk-parse",
            rows_html=rows_html,
            css_class="rk-parse",
            extra_style=extra_style,
            _container_id=container_id,
        )

        hint_html = ""
        if self.dropped_spans:
            n = len(self.dropped_spans)
            if any(d.reason == "below_threshold" for d in self.dropped_spans):
                hint_msg = (
                    f"{n} span(s) were dropped by precision gates. "
                    f"Pass <code>include_nil=True</code> to surface NIL entities in results."
                )
            else:
                hint_msg = (
                    f"{n} span(s) rejected by precision gates "
                    f"(sentinel / short-input) — not recoverable with include_nil=True."
                )
            hint_html = (
                f"<div style='margin-top:8px;padding:6px 10px;"
                f"background:#fffbeb;border-left:3px solid #f59e0b;font-size:0.9em;'>"
                f"<b>Tip:</b> {hint_msg}"
                f"</div>"
            )

        return f"{summary_html}\n{table_block}\n{hint_html}"
