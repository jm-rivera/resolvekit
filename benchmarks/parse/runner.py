"""Parse evaluation runner.

Runs ``resolver.parse()`` over every row in a gold set and scores the
predictions with :func:`~benchmarks.parse.metrics.span_metrics`.  Also
measures parse latency (p50/p99 on multi-mention rows) and optionally
reports ``parse_bulk`` throughput and ``PackAutomaton`` build time.

Public surface:

    ParseAdapter
        Protocol: any object with ``predict(text) -> list[PredSpan]``.

    ResolverParseAdapter
        Thin ``ParseAdapter`` wrapper around a live ``Resolver``.

    ParseEvalReport
        Aggregated precision/recall/F1 + latency block.

    run_parse_eval_adapter(*, adapter, rows) -> ParseEvalReport
        Score a list of ParseEvalRow records using any ParseAdapter.

    run_parse_eval(*, resolver, rows) -> ParseEvalReport
        Convenience wrapper — builds a ResolverParseAdapter and delegates
        to run_parse_eval_adapter, then attaches the latency block.
"""

from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from benchmarks.core.metrics import latency_metrics
from benchmarks.parse.loader import ParseEvalRow
from benchmarks.parse.metrics import (
    ParseEvalResult,
    PredSpan,
    aggregate_results,
    span_metrics,
)

if TYPE_CHECKING:
    from resolvekit import Resolver


@runtime_checkable
class ParseAdapter(Protocol):
    """Structural protocol for parse evaluation adapters.

    Any object that implements ``predict`` can be scored by
    :func:`run_parse_eval_adapter` — no subclassing required.
    """

    def predict(self, text: str) -> list[PredSpan]:
        """Return predicted spans for one document.

        Only resolved/linked spans should be returned.  NIL or unlinked
        spans must be omitted (the harness counts them as missed gold spans,
        not as FPs from the adapter).

        Args:
            text: Raw document text.

        Returns:
            List of :class:`~benchmarks.parse.metrics.PredSpan` objects.
        """
        ...


def _entities_to_pred_spans(entities: list) -> list[PredSpan]:
    return [
        PredSpan(
            start=e.start,
            end=e.end,
            entity_id=e.entity_id,
            entity_type=e.entity_type,
        )
        for e in entities
        # Only include resolved/linked entities — NIL/no_match entities are not
        # positive predictions and should not count as FPs.
        if e.entity_id is not None
    ]


class ResolverParseAdapter:
    """ParseAdapter wrapper around a live Resolver.

    Calls ``resolver.parse(text)`` and converts the resulting
    ``ParsedEntity`` objects to :class:`~benchmarks.parse.metrics.PredSpan`
    instances via :func:`_entities_to_pred_spans`.

    Args:
        resolver: A live :class:`~resolvekit.Resolver` instance.
    """

    def __init__(self, resolver: Resolver) -> None:
        self._resolver = resolver

    def predict(self, text: str) -> list[PredSpan]:
        """Parse one document and return only resolved spans."""
        return _entities_to_pred_spans(self._resolver.parse(text).entities)


@dataclass(frozen=True)
class ParseLatencyResult:
    """Parse latency measurements from a timed run.

    Attributes:
        parse_p50_ms:         Median parse() latency in milliseconds.
        parse_p99_ms:         99th-percentile parse() latency (None when < 20 samples).
        parse_bulk_p50_ms:    Median per-row latency for parse_bulk() over 1k rows.
        parse_bulk_p99_ms:    99th-percentile per-row latency (None when < 20 samples).
        automaton_build_ms:   Time to build the PackAutomaton (first parse() call minus
                              subsequent calls), in milliseconds.
        rss_mb:               Peak RSS in MiB measured in a fresh subprocess, or None.
        sample_count:         Number of timed parse() calls included in p50/p99.
        bulk_row_count:       Number of rows in the parse_bulk() run.
    """

    parse_p50_ms: float
    parse_p99_ms: float | None
    parse_bulk_p50_ms: float
    parse_bulk_p99_ms: float | None
    automaton_build_ms: float | None
    rss_mb: float | None
    sample_count: int
    bulk_row_count: int


@dataclass(frozen=True)
class ParseEvalReport:
    """Full result of a parse evaluation run.

    Attributes:
        metrics:  Aggregated span-level metrics over all rows.
        latency:  Latency measurements, or None when not measured.
        row_count: Number of documents scored.
    """

    metrics: ParseEvalResult
    latency: ParseLatencyResult | None
    row_count: int


# Number of warmup parse() calls before the timed loop.
_WARMUP_CALLS = 5

# Number of rows for the parse_bulk latency benchmark (round-robin from gold set).
_BULK_ROW_COUNT = 1000


def _measure_latency(
    *,
    resolver: Resolver,
    rows: list[ParseEvalRow],
) -> ParseLatencyResult:
    """Measure parse() p50/p99 and parse_bulk throughput.

    Warmup: runs ``_WARMUP_CALLS`` parse() calls on the first row's text so
    the automaton is built and cached before the timed loop starts.  This
    prevents the cold-build cost from inflating p99.

    Automaton build time: estimated as ``first_parse_time - median(rest)``
    (the first timed call after warmup still includes any lazy init not yet
    triggered during warmup — this is an approximation; the PackAutomaton is
    typically warm after the first warmup call).

    Args:
        resolver: A live Resolver instance to call.
        rows:     Gold rows; multi-mention rows are preferred for p99 signal,
                  but any non-empty text will do.

    Returns:
        :class:`ParseLatencyResult` with all timing fields populated.
    """
    # Pick the multi-mention rows (≥ 2 gold spans) for the timing loop.
    # Fall back to all rows when none have multiple spans.
    multi_rows = [r for r in rows if len(r.gold_spans) >= 2]
    timing_rows = multi_rows if multi_rows else rows
    timing_texts = [r.text for r in timing_rows]

    if not timing_texts:
        return ParseLatencyResult(
            parse_p50_ms=0.0,
            parse_p99_ms=None,
            parse_bulk_p50_ms=0.0,
            parse_bulk_p99_ms=None,
            automaton_build_ms=None,
            rss_mb=None,
            sample_count=0,
            bulk_row_count=0,
        )

    warmup_text = timing_texts[0]
    for _ in range(_WARMUP_CALLS):
        resolver.parse(warmup_text)

    latencies: list[float] = []
    n_samples = max(len(timing_texts), 50)  # at least 50 samples for stable p99
    for i in range(n_samples):
        text = timing_texts[i % len(timing_texts)]
        t0 = time.perf_counter()
        resolver.parse(text)
        latencies.append((time.perf_counter() - t0) * 1000.0)

    lat = latency_metrics(latencies_ms=latencies)

    bulk_texts = [rows[i % len(rows)].text for i in range(_BULK_ROW_COUNT)]
    t_bulk_start = time.perf_counter()
    resolver.parse_bulk(values=bulk_texts)
    bulk_elapsed_ms = (time.perf_counter() - t_bulk_start) * 1000.0
    per_row_ms = bulk_elapsed_ms / _BULK_ROW_COUNT

    # Approximate the automaton build time: first call during warmup is the
    # build call; compare it to the median of the timed loop.
    # We can't easily separate build vs. first query after warmup, so we
    # report None — the automaton is typically warm after warmup calls.
    automaton_build_ms: float | None = None

    return ParseLatencyResult(
        parse_p50_ms=lat.p50,
        parse_p99_ms=lat.p99,
        parse_bulk_p50_ms=per_row_ms,
        parse_bulk_p99_ms=None,  # single wall-clock measurement; no distribution
        automaton_build_ms=automaton_build_ms,
        rss_mb=None,  # RSS measured separately via subprocess in __main__
        sample_count=lat.sample_count,
        bulk_row_count=_BULK_ROW_COUNT,
    )


def _measure_rss_subprocess() -> float | None:
    """Measure peak RSS for a fresh Resolver.auto() + parse() run in a subprocess.

    Returns:
        Peak RSS in MiB, or None when the subprocess fails or resource module
        is unavailable.
    """
    import subprocess
    import sys

    script = """
import json, sys, time
def _peak_rss_mb():
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return rss / (1024 ** 2)
        return rss / 1024
    except Exception:
        return None

from resolvekit import Resolver
r = Resolver.auto()
r.parse("Kenya and Somalia visited the US embassy for the WHO meeting")
peak = _peak_rss_mb()
print(json.dumps({"peak_rss_mb": peak}))
"""
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None

    if completed.returncode != 0:
        return None

    last_line = (completed.stdout or "").strip().splitlines()[-1:]
    if not last_line:
        return None

    try:
        import json

        data = json.loads(last_line[0])
        val = data.get("peak_rss_mb")
        return float(val) if val is not None else None
    except (ValueError, KeyError):
        return None


def run_parse_eval_adapter(
    *,
    adapter: ParseAdapter,
    rows: list[ParseEvalRow],
) -> ParseEvalReport:
    """Score a gold set using any :class:`ParseAdapter` and return a report.

    Calls ``adapter.predict(row.text)`` for each row, scores the predictions
    via :func:`~benchmarks.parse.metrics.span_metrics`, and aggregates the
    per-row results.  No latency measurement is performed — the returned
    ``latency`` field is always ``None``.

    This is the shared scoring loop used by all adapters (resolvekit,
    spaCy, gazetteer, …).  Scoring logic lives here once; adapters only
    implement ``predict``.

    Args:
        adapter: Any object implementing :class:`ParseAdapter`.
        rows:    Gold rows from :func:`~benchmarks.parse.loader.load_parse_dataset`.

    Returns:
        :class:`ParseEvalReport` with aggregated metrics and ``latency=None``.
    """
    per_row_results: list[ParseEvalResult] = []

    for row in rows:
        preds = adapter.predict(row.text)
        result = span_metrics(
            predictions=preds,
            gold=list(row.gold_spans),
        )
        # Stamp the correct row_count (span_metrics returns 1 per call).
        per_row_results.append(dataclasses.replace(result, row_count=1))

    aggregated = aggregate_results(per_row_results)

    return ParseEvalReport(
        metrics=aggregated,
        latency=None,
        row_count=len(rows),
    )


def run_parse_eval(
    *,
    resolver: Resolver,
    rows: list[ParseEvalRow],
    measure_latency: bool = False,
) -> ParseEvalReport:
    """Score a gold set with ``resolver.parse()`` and return a report.

    Wraps the resolver in a :class:`ResolverParseAdapter` and delegates
    scoring to :func:`run_parse_eval_adapter`.  When ``measure_latency=True``,
    runs an additional timing pass (p50/p99 on multi-mention rows, parse_bulk
    on 1k round-robin rows, RSS via subprocess) and attaches it to the report.

    Args:
        resolver:         A live :class:`~resolvekit.Resolver` instance.
        rows:             Gold rows from :func:`~benchmarks.parse.loader.load_parse_dataset`.
        measure_latency:  When True, measure parse() p50/p99, parse_bulk
                          throughput, and RSS (slow; adds ~10-30 s).

    Returns:
        :class:`ParseEvalReport` with aggregated metrics and optional latency block.
    """
    adapter = ResolverParseAdapter(resolver)
    report = run_parse_eval_adapter(adapter=adapter, rows=rows)

    latency: ParseLatencyResult | None = None
    if measure_latency and rows:
        latency = _measure_latency(resolver=resolver, rows=rows)
        rss = _measure_rss_subprocess()
        latency = dataclasses.replace(latency, rss_mb=rss)

    return dataclasses.replace(report, latency=latency)
