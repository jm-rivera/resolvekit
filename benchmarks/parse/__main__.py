"""`python -m benchmarks.parse` — run the parse evaluation and write results.

Edit ``RunConfig`` below to adjust dataset name, output path, or whether to
run the latency/RSS benchmark (slow; adds ~10-30 s).  No argparse -- this
module is configured by editing the frozen ``RunConfig`` dataclass and the
``if __name__ == "__main__"`` block.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

_RESULTS_DIR = Path(__file__).parent.parent / "results"


@dataclass(frozen=True, kw_only=True)
class RunConfig:
    """Configuration for `python -m benchmarks.parse`.

    Edit fields directly in the ``__main__`` block below for one-off runs.

    Args:
        dataset:         Name of the parse eval dataset to load (Parquet must exist).
        output:          Path to write the results JSON.
        measure_latency: When True, measure parse() p50/p99, parse_bulk on 1k
                         round-robin rows, and peak RSS via subprocess.  Adds
                         ~10-30 s; skip during quick iteration.
    """

    dataset: str = "eval_parse"
    output: Path = _RESULTS_DIR / "parse_latest.json"
    measure_latency: bool = False


_DEFAULT_CONFIG = RunConfig()


def main(*, config: RunConfig = _DEFAULT_CONFIG) -> int:
    """Run the parse eval and write ``parse_latest.json``.

    Writes a JSON file with top-level keys ``precision``, ``recall``, ``f1``,
    ``boundary_exact_rate``, ``nil_correct_rate``, ``true_positives``,
    ``false_positives``, ``false_negatives``, ``row_count``, and optionally
    a ``latency`` block when ``config.measure_latency`` is True.

    Args:
        config: Run parameters; defaults to the canonical configuration above.

    Returns:
        Exit code (0 on success).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    from benchmarks.parse.loader import load_parse_dataset
    from benchmarks.parse.runner import run_parse_eval
    from resolvekit import Resolver

    logger.info("loading dataset %r", config.dataset)
    rows = load_parse_dataset(name=config.dataset)
    logger.info("loaded %d rows", len(rows))

    logger.info("constructing Resolver.auto()")
    resolver = Resolver.auto()

    logger.info("running parse eval (measure_latency=%s)", config.measure_latency)
    report = run_parse_eval(
        resolver=resolver,
        rows=rows,
        measure_latency=config.measure_latency,
    )

    m = report.metrics

    output: dict = {
        "precision": m.precision,
        "recall": m.recall,
        "f1": m.f1,
        "boundary_exact_rate": m.boundary_exact_rate,
        "nil_correct_rate": m.nil_correct_rate,
        "true_positives": m.true_positives,
        "false_positives": m.false_positives,
        "false_negatives": m.false_negatives,
        "row_count": report.row_count,
        "dataset": config.dataset,
    }

    if report.latency is not None:
        output["latency"] = {
            "parse_p50_ms": report.latency.parse_p50_ms,
            "parse_p99_ms": report.latency.parse_p99_ms,
            "parse_bulk_p50_ms": report.latency.parse_bulk_p50_ms,
            "parse_bulk_p99_ms": report.latency.parse_bulk_p99_ms,
            "automaton_build_ms": report.latency.automaton_build_ms,
            "rss_mb": report.latency.rss_mb,
            "sample_count": report.latency.sample_count,
            "bulk_row_count": report.latency.bulk_row_count,
        }

    config.output.parent.mkdir(parents=True, exist_ok=True)
    config.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")

    logger.info(
        "wrote %s  precision=%.4f  recall=%.4f  f1=%.4f",
        config.output,
        m.precision,
        m.recall,
        m.f1,
    )
    print(
        f"precision={m.precision:.4f}  recall={m.recall:.4f}  "
        f"f1={m.f1:.4f}  "
        f"tp={m.true_positives}  fp={m.false_positives}  fn={m.false_negatives}"
    )
    return 0


if __name__ == "__main__":
    # Edit RunConfig fields here for one-off runs.
    config = RunConfig(
        dataset="eval_parse",
        output=_RESULTS_DIR / "parse_latest.json",
        measure_latency=False,
    )
    sys.exit(main(config=config))
