"""`python -m benchmarks` — run the canonical config and write artifacts.

For one-off runs, call `run_benchmark(...)` directly from the REPL or a
scratch script; `RunConfig` is the canonical CI configuration.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path

_RESULTS_DIR = Path(__file__).parent / "results"


@dataclass(frozen=True, kw_only=True)
class RunConfig:
    """Canonical CI configuration for `python -m benchmarks`.

    Edit fields directly in source for one-off runs, or pass a constructed
    instance to `main(config=RunConfig(...))`.

    Args:
        tools: Tool names to benchmark; ``None`` runs all registered tools.
        datasets: Dataset names to benchmark; ``None`` runs all available datasets.
        output: Optional path to write an additional Markdown report.
        measure_cold_start: Whether to measure cold-start latency.
        warmup: Number of warmup queries per tool/dataset combo.
        seed: Random seed for dataset shuffling.
    """

    tools: list[str] | None = None
    datasets: list[str] | None = None
    output: Path | None = None
    measure_cold_start: bool = True
    warmup: int = 100
    seed: int = 42


_DEFAULT_CONFIG = RunConfig()


def main(*, config: RunConfig = _DEFAULT_CONFIG) -> int:
    """Run the canonical config and write artifacts.

    Writes ``benchmarks/results/latest.json`` and
    ``benchmarks/results/latest.md``, plus the optional ``config.output``
    Markdown path.

    Args:
        config: Run parameters; defaults to the canonical CI configuration.

    Returns:
        Exit code (0 on success).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from benchmarks.core.engine import run_benchmark

    report = run_benchmark(
        tools=config.tools,
        datasets=config.datasets,
        measure_cold_start=config.measure_cold_start,
        warmup=config.warmup,
        seed=config.seed,
    )

    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report.to_json(path=_RESULTS_DIR / "latest.json")
    report.to_markdown(path=_RESULTS_DIR / "latest.md")

    if config.output is not None:
        config.output.parent.mkdir(parents=True, exist_ok=True)
        report.to_markdown(path=config.output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
