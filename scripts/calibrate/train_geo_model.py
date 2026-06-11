#!/usr/bin/env python3
"""Train a logistic scoring model for the geo domain.

Uses the train_model() API from resolvekit.calibration.train, writing
outputs to .calibration_output/geo/.

Run via:
    uv run python -m scripts.calibrate.train_geo_model

To customize, edit the fields in the ``__main__`` block at the bottom of
the file (or import ``run()`` and pass a TrainGeoModelSettings from a notebook).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from resolvekit.calibration.train import train_model
from scripts.calibrate.calibrate_common import (
    DEFAULT_CACHE_DIR,
    DEFAULT_DATAPACKS_ROOT,
    DEFAULT_OUTPUT_DIR,
    build_calibration_resolver,
)

logger = logging.getLogger(__name__)

DOMAIN = "geo"


@dataclass(frozen=True, slots=True, kw_only=True)
class TrainGeoModelSettings:
    """Settings for the geo model training script."""

    adapters: list[str] | None = None
    datapacks_root: Path = DEFAULT_DATAPACKS_ROOT
    limit_per_adapter: int | None = None
    regularization: float = 1.0
    seed: int = 42
    output_dir: Path = DEFAULT_OUTPUT_DIR
    cache_dir: Path = DEFAULT_CACHE_DIR
    save_examples: bool = False


def run(*, settings: TrainGeoModelSettings) -> None:
    """Train a logistic scoring model for geo resolution.

    Args:
        settings: Training settings (resolver root, adapters, output paths, etc.).
    """
    domain_output_dir = settings.output_dir / DOMAIN
    domain_output_dir.mkdir(parents=True, exist_ok=True)

    resolver = build_calibration_resolver(datapacks_root=settings.datapacks_root)

    result = train_model(
        resolver,
        DOMAIN,
        adapter_names=settings.adapters,
        regularization=settings.regularization,
        limit_per_adapter=settings.limit_per_adapter,
        cache_dir=settings.cache_dir,
        output_path=domain_output_dir / "geo_scoring_model.json",
        examples_output=(domain_output_dir / "geo_examples_model.jsonl")
        if settings.save_examples
        else None,
        seed=settings.seed,
    )

    print(f"\nTrained on {result.n_train} examples, evaluated on {result.n_eval}")
    if result.metrics:
        m = result.metrics
        print(
            f"Eval: Brier={m.brier_score:.4f}  LogLoss={m.log_loss:.4f}  ECE={m.ece:.4f}  AdapECE={m.adaptive_ece:.4f}"
        )

    print("\nFeature weights:")
    for name, weight in zip(
        result.model.feature_names, result.model.weights, strict=False
    ):
        print(f"  {name:<24} {weight:+.4f}")
    print(f"  {'bias':<24} {result.model.bias:+.4f}")

    print(f"\nModel saved to {result.output_path}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run(settings=TrainGeoModelSettings())
