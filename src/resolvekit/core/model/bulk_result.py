"""BulkResult — return type for bulk() when output is rich (not scalar to=).

Returned by ``bulk()`` ONLY when:
- ``to=None`` (Series of ResolutionResult)
- ``output="record"`` (Series-of-struct)
- ``output="frame"`` (flattened DataFrame)

For scalar ``to=`` (e.g. ``to="iso3"``), ``bulk()`` returns the native shape
directly (``pd.Series``, ``pl.Series``, ``np.ndarray``, or ``list``).

Note: ``source`` is a ``Sequence[ResolutionResult]`` (typically a ``list``),
so ``BulkResult`` instances are not hashable — don't use as dict keys or set members.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, overload

from resolvekit.core.model._repr import escape, next_container_id, scoped_table
from resolvekit.core.model.crosswalk import IGNORE as _IGNORE_SENTINEL
from resolvekit.core.model.crosswalk import Crosswalk
from resolvekit.core.model.result import ResolutionResult, ResolutionStatus

if TYPE_CHECKING:
    import pandas as pd
    import polars as pl

    from resolvekit.core.explain.scorecard import Scorecard, Verbosity


class ResolutionSummary(NamedTuple):
    """Counts from a bulk resolution batch.

    Attributes:
        total: Total number of rows.
        resolved: Rows with status RESOLVED.
        ambiguous: Rows with status AMBIGUOUS.
        no_match: Rows with status NO_MATCH.
        error: Rows with status ERROR.
    """

    total: int
    resolved: int
    ambiguous: int
    no_match: int
    error: int


@dataclass(slots=True, frozen=True)
class BulkResult:
    """Bulk resolution outcome with diagnostics and native-shape values.

    Attributes:
        values: The native output shape (``pd.Series``, ``pl.Series``,
            ``np.ndarray``, ``list``, or ``tuple``).
        source: Per-row ``ResolutionResult`` instances.
        kind: Which native shape is in ``values``.
    """

    values: Any
    source: Sequence[ResolutionResult]
    kind: Literal["pandas", "polars", "numpy", "list", "tuple", "dict"]

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    def _is_frame_values(self) -> bool:
        """Return True when ``values`` is a DataFrame (``output='frame'`` path)."""
        try:
            import pandas as pd

            if isinstance(self.values, pd.DataFrame):
                return True
        except ImportError:
            pass
        try:
            import polars as pl

            if isinstance(self.values, pl.DataFrame):
                return True
        except ImportError:
            pass
        return False

    def to_list(self) -> list[Any]:
        """Return results as a plain Python list.

        Raises:
            TypeError: If this ``BulkResult`` came from ``output='frame'`` —
                ``values`` is a DataFrame; access it directly or call
                ``unnest()``.
        """
        if self._is_frame_values():
            raise TypeError(
                "to_list() is not supported on output='frame' BulkResult; "
                "access .values directly (it's a DataFrame) or call .unnest()"
            )
        if isinstance(self.values, list):
            return self.values
        if isinstance(self.values, tuple):
            return list(self.values)
        if isinstance(self.values, dict):
            return list(self.values.values())
        try:
            return list(self.values)
        except TypeError:
            return list(self.source)

    def to_pandas(self) -> pd.Series:
        """Return results as a ``pandas.Series``.

        Raises:
            ImportError: If pandas is not installed.
            TypeError: If this ``BulkResult`` came from ``output='frame'`` —
                ``values`` is already a DataFrame; access it directly.
        """
        try:
            import pandas as pd
        except ImportError as exc:
            raise ImportError(
                "to_pandas() requires pandas. "
                "Install with: pip install 'resolvekit[pandas]'"
            ) from exc
        if self._is_frame_values():
            raise TypeError(
                "to_pandas() returns a Series; this BulkResult came from "
                "output='frame' (values is a DataFrame). Access .values directly."
            )
        if self.kind == "pandas":
            return self.values  # type: ignore[return-value]
        return pd.Series(self.to_list())

    def to_polars(self) -> pl.Series:
        """Return results as a ``polars.Series``.

        Raises:
            ImportError: If polars is not installed.
            TypeError: If this ``BulkResult`` came from ``output='frame'`` —
                ``values`` is already a DataFrame; access it directly.
        """
        try:
            import polars as pl
        except ImportError as exc:
            raise ImportError(
                "to_polars() requires polars. "
                "Install with: pip install 'resolvekit[polars]'"
            ) from exc
        if self._is_frame_values():
            raise TypeError(
                "to_polars() returns a Series; this BulkResult came from "
                "output='frame' (values is a DataFrame). Access .values directly."
            )
        if self.kind == "polars":
            return self.values  # type: ignore[return-value]
        return pl.Series(self.to_list())

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def summary(self) -> ResolutionSummary:
        """Return per-status counts for this batch.

        Returns:
            :class:`ResolutionSummary` with ``total``, ``resolved``,
            ``ambiguous``, ``no_match``, and ``error`` counts.
        """
        resolved = ambiguous = no_match = error = 0
        for r in self.source:
            match r.status:
                case ResolutionStatus.RESOLVED:
                    resolved += 1
                case ResolutionStatus.AMBIGUOUS:
                    ambiguous += 1
                case ResolutionStatus.NO_MATCH:
                    no_match += 1
                case ResolutionStatus.ERROR:
                    error += 1
        return ResolutionSummary(
            total=len(self.source),
            resolved=resolved,
            ambiguous=ambiguous,
            no_match=no_match,
            error=error,
        )

    @property
    def failures(self) -> BulkResult:
        """Sub-result containing only non-RESOLVED rows.

        Returns a new ``BulkResult`` filtered to rows where status is not
        ``RESOLVED``.  ``values`` is a plain ``list`` in the returned instance.

        For ``output='frame'`` results, ``values`` is sliced as a DataFrame
        (preserving columns) and ``kind`` is preserved so downstream code
        keeps working with the same shape.
        """
        fail_indices = [
            i
            for i, r in enumerate(self.source)
            if r.status != ResolutionStatus.RESOLVED
        ]
        fail_source = [self.source[i] for i in fail_indices]
        if self._is_frame_values():
            # Preserve the frame shape and original kind for downstream code.
            try:
                import pandas as pd

                if isinstance(self.values, pd.DataFrame):
                    return BulkResult(
                        values=self.values.iloc[fail_indices].reset_index(drop=True),
                        source=fail_source,
                        kind=self.kind,
                    )
            except ImportError:
                pass
            try:
                import polars as pl

                if isinstance(self.values, pl.DataFrame):
                    return BulkResult(
                        values=self.values[fail_indices],
                        source=fail_source,
                        kind=self.kind,
                    )
            except ImportError:
                pass
        fail_values: list[Any]
        try:
            # For dict kind, iterate values (not keys) so index-slicing works correctly.
            all_values = self.to_list() if self.kind == "dict" else list(self.values)
            fail_values = [all_values[i] for i in fail_indices]
        except (TypeError, IndexError):
            fail_values = list(fail_source)
        return BulkResult(
            values=fail_values,
            source=fail_source,
            kind="list",
        )

    def explain(
        self,
        *,
        verbosity: Literal["minimal", "standard", "full"] | Verbosity = "standard",
    ) -> list[Scorecard | None]:
        """Re-run resolution with tracing for each row and return scorecards.

        Iterates ``self.source`` and calls :meth:`ResolutionResult.explain` on
        each row that has a live resolver back-ref.  Detached rows (no live
        resolver — common in deserialized results) yield ``None`` in the
        returned list.

        Args:
            verbosity: Scorecard detail level forwarded to each
                ``result.explain(verbosity=...)`` call.

        Returns:
            A list of :class:`Scorecard` (one per ``self.source`` row, in
            order), with ``None`` for any detached row.

        Note:
            Re-runs the pipeline for every row — cost scales with batch size.
            Prefer ``result.explain()`` on individual rows when you only need
            a few diagnostics.
        """
        from resolvekit.core.errors_base import ExplainNotAvailableError

        scorecards: list[Scorecard | None] = []
        for r in self.source:
            try:
                scorecards.append(r.explain(verbosity=verbosity))
            except ExplainNotAvailableError:
                scorecards.append(None)
        return scorecards

    def unnest(self) -> Any:
        """Flatten ``self.source`` into columns: status, entity_id, confidence, pack_id, query_text.

        Returns:
            ``pd.DataFrame`` when ``kind == "pandas"``; ``pl.DataFrame`` when
            ``kind == "polars"``; otherwise a list of dicts (one per row).
        """
        records = [
            {
                "status": r.status.value,
                "entity_id": r.entity_id,
                "confidence": r.confidence,
                "pack_id": r.pack_id,
                "query_text": r.query_text,
            }
            for r in self.source
        ]
        if self.kind == "pandas":
            try:
                import pandas as pd
            except ImportError as exc:
                raise ImportError(
                    "unnest() with kind='pandas' requires pandas. "
                    "Install with: pip install 'resolvekit[pandas]'"
                ) from exc
            return pd.DataFrame.from_records(records)
        if self.kind == "polars":
            try:
                import polars as pl
            except ImportError as exc:
                raise ImportError(
                    "unnest() with kind='polars' requires polars. "
                    "Install with: pip install 'resolvekit[polars]'"
                ) from exc
            return pl.DataFrame(records)
        return records

    # ------------------------------------------------------------------
    # Review round-trip
    # ------------------------------------------------------------------

    def to_review(self, path: str | Path, *, top_n: int = 3) -> None:
        """Write ambiguous and no_match unique values to a CSV for human review.

        Each unique ``query_text`` that is AMBIGUOUS or NO_MATCH gets one row.
        Rows are deduped: a value that appears multiple times in ``source``
        produces a single review row.  RESOLVED and ERROR rows are omitted.
        ``query_text=None`` rows are skipped (can't key them).

        The file always includes the header even when there are zero hard cases
        (header-only file, no error raised).

        Columns: ``value``, ``status``, then for k in 1..top_n:
        ``cand_k_id``, ``cand_k_name``, ``cand_k_conf``, then
        ``chosen`` (empty), ``note`` (empty).

        Parameters
        ----------
        path:
            Destination file path; created / overwritten as UTF-8 text.
        top_n:
            Number of candidate columns to include.  Defaults to 3.
        """
        path = Path(path)

        fieldnames = ["value", "status"]
        for k in range(1, top_n + 1):
            fieldnames += [f"cand_{k}_id", f"cand_{k}_name", f"cand_{k}_conf"]
        fieldnames += ["chosen", "note"]

        seen: set[str] = set()
        rows: list[dict[str, Any]] = []
        for r in self.source:
            if r.status not in (ResolutionStatus.AMBIGUOUS, ResolutionStatus.NO_MATCH):
                continue
            qt = r.query_text
            if qt is None:
                continue
            if qt in seen:
                continue
            seen.add(qt)
            row: dict[str, Any] = {"value": qt, "status": r.status.value}
            for k in range(1, top_n + 1):
                idx = k - 1
                if idx < len(r.candidates):
                    cand = r.candidates[idx]
                    row[f"cand_{k}_id"] = cand.entity_id
                    row[f"cand_{k}_name"] = cand.canonical_name or ""
                    conf = cand.confidence
                    row[f"cand_{k}_conf"] = f"{conf:.4f}" if conf is not None else ""
                else:
                    row[f"cand_{k}_id"] = ""
                    row[f"cand_{k}_name"] = ""
                    row[f"cand_{k}_conf"] = ""
            row["chosen"] = ""
            row["note"] = ""
            rows.append(row)

        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def to_crosswalk(
        self,
        review: str | Path | None = None,
        *,
        strict: bool = True,
    ) -> Crosswalk:
        """Merge auto-resolved entries with a filled review file into a Crosswalk.

        Auto-map is built from all RESOLVED rows that have both ``query_text``
        and ``entity_id`` set (deduped).  If *review* is given, each row with
        a non-empty ``chosen`` column overrides (or adds to) the auto-map:
        ``chosen == "IGNORE"`` maps the value to the IGNORE sentinel; any other
        non-empty value is treated as an entity-id.  The review file's ``value``
        and ``chosen`` columns are the only ones read.

        Parameters
        ----------
        review:
            Optional path to a CSV produced by ``to_review`` and filled in
            by a human.  Missing ``value`` or ``chosen`` columns raise
            ``ValueError``.
        strict:
            Forwarded to :meth:`Crosswalk.from_dict`.  When ``True`` (default),
            ``bulk(crosswalk=...)`` raises ``CrosswalkError`` for unknown ids at
            apply time.

        Returns
        -------
        Crosswalk
            Ready for use as ``crosswalk=`` in the next ``bulk()`` call.

        Raises
        ------
        ValueError
            When *review* is given but lacks required columns (``value``,
            ``chosen``).
        """
        auto: dict[str, str] = {}
        for r in self.source:
            if (
                r.status == ResolutionStatus.RESOLVED
                and r.query_text is not None
                and r.entity_id is not None
                and r.query_text not in auto
            ):
                auto[r.query_text] = r.entity_id

        # Overlay manual decisions from the review file.
        # Values: str (entity-id) or _Ignore sentinel; typed as Any to keep
        # Crosswalk.from_dict happy (it accepts str | _Ignore | None).
        manual: dict[str, Any] = {}
        if review is not None:
            review_path = Path(review)
            with review_path.open(newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                # Validate required columns are present before iterating.
                if reader.fieldnames is None or not {
                    "value",
                    "chosen",
                }.issubset(set(reader.fieldnames)):
                    got = list(reader.fieldnames) if reader.fieldnames else []
                    raise ValueError(
                        f"review CSV must have columns 'value','chosen'; got {got}"
                    )
                for row in reader:
                    chosen = row["chosen"].strip()
                    if chosen == "":
                        continue  # still pending — skip
                    value = row["value"]
                    manual[value] = _IGNORE_SENTINEL if chosen == "IGNORE" else chosen

        # Manual overrides auto on key collision (human decided).
        merged: dict[str, Any] = {**auto, **manual}
        return Crosswalk.from_dict(merged, strict=strict)

    # ------------------------------------------------------------------
    # Collection protocol
    # ------------------------------------------------------------------

    def __iter__(self):  # type: ignore[return]
        return iter(self.source)

    def __len__(self) -> int:
        return len(self.source)

    @overload
    def __getitem__(self, key: int) -> ResolutionResult: ...
    @overload
    def __getitem__(self, key: slice) -> Sequence[ResolutionResult]: ...
    def __getitem__(
        self, key: int | slice
    ) -> ResolutionResult | Sequence[ResolutionResult]:
        return self.source[key]

    # ------------------------------------------------------------------
    # Representations
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        s = self.summary()
        return (
            f"BulkResult(total={s.total}, resolved={s.resolved}, "
            f"no_match={s.no_match}, ambiguous={s.ambiguous}, "
            f"error={s.error}, kind={self.kind!r})"
        )

    def _repr_html_(self) -> str:
        """Sklearn-scoped HTML with a cross-verb snap hint when NO_MATCH rows exist.

        Each call gets a unique container ID (``rk-bulk-N``) so styles from
        one cell never bleed into another.  All user-supplied strings are
        HTML-escaped before interpolation.  When any source row has
        ``status == NO_MATCH``, appends a suggestion box pointing users to
        ``rk.snap()``.
        """
        container_id = next_container_id("rk-bulk")
        scope = f"#{container_id} >"

        s = self.summary()
        has_no_match = s.no_match > 0

        summary_html = (
            f"<p><b>BulkResult</b> — "
            f"total: {s.total} | "
            f"resolved: {s.resolved} | "
            f"no_match: {s.no_match} | "
            f"ambiguous: {s.ambiguous} | "
            f"error: {s.error}"
            f"</p>"
        )

        display_rows = list(self.source[:10])
        row_htmls: list[str] = []
        for r in display_rows:
            eid = escape(r.entity_id or "")
            conf = f"{r.confidence:.2f}" if r.confidence is not None else ""
            name = escape((r.entity.canonical_name if r.entity else "") or "")
            pack = escape(r.pack_id or "")
            sv = r.status.value
            row_htmls.append(
                f"<tr>"
                f"<td class='rk-s-{sv}'>{sv}</td>"
                f"<td>{eid}</td>"
                f"<td>{conf}</td>"
                f"<td>{name}</td>"
                f"<td>{pack}</td>"
                f"</tr>"
            )
        if len(self.source) > 10:
            row_htmls.append(
                f"<tr><td colspan='5'>… {len(self.source) - 10} more rows</td></tr>"
            )
        rows_html = (
            "<thead><tr>"
            "<th>status</th><th>entity_id</th><th>confidence</th>"
            "<th>name</th><th>pack_id</th>"
            f"</tr></thead><tbody>{''.join(row_htmls)}</tbody>"
        )

        hint_html = ""
        if has_no_match:
            no_match_texts = [
                r.query_text
                for r in self.source
                if r.status == ResolutionStatus.NO_MATCH and r.query_text
            ][:3]
            examples = (
                ", ".join(escape(repr(t)) for t in no_match_texts)
                if no_match_texts
                else "..."
            )
            hint_html = (
                f"<div style='margin-top:8px;padding:6px 10px;"
                f"background:#fffbeb;border-left:3px solid #f59e0b;font-size:0.9em;'>"
                f"<b>Tip:</b> {s.no_match} row(s) had no match. "
                f"Try: <code>rk.snap(query=..., candidates=[...])</code> "
                f"for closest-match lookup on unresolved values "
                f"(e.g. {examples})."
                f"</div>"
            )

        extra_style = (
            f"  {scope} table.rk-bulk th {{\n"
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
        # scoped_table returns <div id><style>…</style><table>…</table></div>;
        # summary_html and hint_html live outside the <table> but inside the
        # same container div, so we build the container manually and delegate
        # the table+style block to scoped_table then embed it.
        table_block = scoped_table(
            prefix="rk-bulk",
            rows_html=rows_html,
            css_class="rk-bulk",
            extra_style=extra_style,
            _container_id=container_id,
        )
        return f"{summary_html}\n{table_block}\n{hint_html}"
