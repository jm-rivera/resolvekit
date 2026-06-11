"""Parse evaluation harness for resolvekit.

Provides mention-level span metrics (precision, recall, F1, boundary exactness,
NIL correctness), a loader for the hand-authored adversarial gold set, and a
runner that scores a Resolver against that set.

Public exports:
    GoldSpan           -- a single gold span with expected entity id and type
    ParseEvalRow       -- one gold document (text + gold_spans tuple)
    load_parse_dataset -- load the eval_parse Parquet into ParseEvalRow records
    PredSpan           -- a predicted span from resolver.parse()
    ParseEvalResult    -- aggregated span-level metrics for one eval run
    span_metrics       -- score predictions vs. gold for one document
    ParseEvalReport    -- full result of a parse evaluation run
    run_parse_eval     -- score a gold set with resolver.parse()
"""

from __future__ import annotations

from benchmarks.parse.loader import GoldSpan, ParseEvalRow, load_parse_dataset
from benchmarks.parse.metrics import ParseEvalResult, PredSpan, span_metrics
from benchmarks.parse.runner import ParseEvalReport, run_parse_eval

__all__ = [
    "GoldSpan",
    "ParseEvalReport",
    "ParseEvalResult",
    "ParseEvalRow",
    "PredSpan",
    "load_parse_dataset",
    "run_parse_eval",
    "span_metrics",
]
