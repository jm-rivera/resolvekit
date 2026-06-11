"""Run parse baseline adapters and write a comparison report.

Loads the ``eval_parse`` gold set, constructs ``Resolver.auto()``, and runs
each available adapter through
:func:`~benchmarks.parse.runner.run_parse_eval_adapter`.  Results are written
to ``benchmarks/results/parse_baselines.json``.

spaCy/model absent → logs a skip message and continues; the gazetteer adapter
always runs.  Never crashes the harness.

Configuration: edit ``BaselineRunConfig`` in the ``__main__`` block below.
No argparse — follows the same convention as ``check_parse_eval_gate.py``.
Run: uv run python -m scripts.benchmark.run_parse_baselines
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from benchmarks.parse.runner import ParseEvalReport

_REPO_ROOT = Path(__file__).parent.parent.parent
_RESULTS_DIR = _REPO_ROOT / "benchmarks" / "results"


def _metrics_block(report: ParseEvalReport) -> dict[str, object]:
    """Flatten a ``ParseEvalReport`` into the JSON object stored per adapter."""
    m = report.metrics
    return {
        "precision": m.precision,
        "recall": m.recall,
        "f1": m.f1,
        "true_positives": m.true_positives,
        "false_positives": m.false_positives,
        "false_negatives": m.false_negatives,
        "nil_correct": m.nil_correct,
        "nil_total": m.nil_total,
        "nil_correct_rate": m.nil_correct_rate,
        "row_count": report.row_count,
    }


@dataclass(frozen=True, kw_only=True)
class BaselineRunConfig:
    """Configuration for the baseline comparison run.

    Edit fields directly in the ``__main__`` block for one-off runs.

    Args:
        dataset:       Name of the parse eval dataset to load (Parquet must exist).
        output:        Path to write the results JSON.
        run_spacy:     When True, attempt to run the spaCy NER adapter.
        run_gazetteer: When True, run the exact-match gazetteer adapter.
        domain:        Domain pack to use for both adapters (default ``"geo"``).
    """

    dataset: str = "eval_parse"
    output: Path = _RESULTS_DIR / "parse_baselines.json"
    run_spacy: bool = True
    run_gazetteer: bool = True
    domain: str = "geo"


_DEFAULT_CONFIG = BaselineRunConfig()


def run_baselines(*, config: BaselineRunConfig = _DEFAULT_CONFIG) -> int:
    """Run enabled baseline adapters and write ``parse_baselines.json``.

    Writes a JSON object keyed by adapter name, each value containing
    ``precision``, ``recall``, ``f1``, ``true_positives``, ``false_positives``,
    ``false_negatives``, ``nil_correct``, ``nil_total``, ``nil_correct_rate``,
    and ``row_count``.

    Args:
        config: Run parameters; defaults to the canonical configuration above.

    Returns:
        Exit code (0 on success; 0 even when spaCy is absent — skip is not a failure).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    from benchmarks.parse.loader import load_parse_dataset
    from benchmarks.parse.runner import run_parse_eval_adapter
    from resolvekit import Resolver

    logger.info("loading dataset %r", config.dataset)
    rows = load_parse_dataset(name=config.dataset)
    logger.info("loaded %d rows", len(rows))

    logger.info("constructing Resolver.auto()")
    resolver = Resolver.auto()

    results: dict[str, object] = {}

    # --- Gazetteer adapter -----------------------------------------------
    if config.run_gazetteer:
        from benchmarks.parse.baselines.gazetteer import GazetteerAdapter

        logger.info("running GazetteerAdapter (domain=%r)", config.domain)
        try:
            adapter = GazetteerAdapter(resolver, domain=config.domain)
            report = run_parse_eval_adapter(adapter=adapter, rows=rows)
            m = report.metrics
            results["gazetteer"] = _metrics_block(report)
            logger.info(
                "GazetteerAdapter: precision=%.4f recall=%.4f f1=%.4f",
                m.precision,
                m.recall,
                m.f1,
            )
        except Exception as exc:
            logger.warning("GazetteerAdapter failed: %s", exc)
            results["gazetteer"] = {"error": str(exc)}

    # --- spaCy NER adapter -----------------------------------------------
    if config.run_spacy:
        from benchmarks.parse.baselines.spacy_ner import SpacyNerAdapter

        logger.info("running SpacyNerAdapter (domain=%r)", config.domain)
        try:
            adapter = SpacyNerAdapter(resolver)  # type: ignore[assignment]
            report = run_parse_eval_adapter(adapter=adapter, rows=rows)
            m = report.metrics
            results["spacy_ner"] = _metrics_block(report)
            logger.info(
                "SpacyNerAdapter: precision=%.4f recall=%.4f f1=%.4f",
                m.precision,
                m.recall,
                m.f1,
            )
        except ImportError as exc:
            logger.info(
                "SpacyNerAdapter skipped — spaCy not installed or model missing: %s",
                exc,
            )
            results["spacy_ner"] = {"skipped": str(exc)}
        except OSError as exc:
            logger.info(
                "SpacyNerAdapter skipped — model not downloaded: %s",
                exc,
            )
            results["spacy_ner"] = {"skipped": str(exc)}
        except Exception as exc:
            logger.warning("SpacyNerAdapter failed unexpectedly: %s", exc)
            results["spacy_ner"] = {"error": str(exc)}

    # --- Write output -----------------------------------------------------
    config.output.parent.mkdir(parents=True, exist_ok=True)
    config.output.write_text(
        json.dumps(results, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    logger.info("wrote %s", config.output)

    return 0


if __name__ == "__main__":
    # Edit BaselineRunConfig fields here for one-off runs.
    config = BaselineRunConfig(
        dataset="eval_parse",
        output=_RESULTS_DIR / "parse_baselines.json",
        run_spacy=True,
        run_gazetteer=True,
        domain="geo",
    )
    sys.exit(run_baselines(config=config))
