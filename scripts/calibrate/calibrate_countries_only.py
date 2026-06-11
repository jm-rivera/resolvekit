#!/usr/bin/env python3
"""Primary countries calibrator for the geo domain.

Builds a Resolver scoped to geo.countries (avoiding the large admin/cities
downloads), fits Platt / Isotonic / Stratified calibrators on raw scores,
evaluates each, and saves the best to .calibration_output/geo/.

Run via:
    uv run python -m scripts.calibrate.calibrate_countries_only

To customize, edit the kwargs in the ``__main__`` block at the bottom of
the file (or import ``run()`` and pass a CalibrationRunConfig from a notebook).
"""

from __future__ import annotations

import logging
import random
from enum import StrEnum
from typing import Literal

from resolvekit.calibration.dataset import LabeledExample
from resolvekit.calibration.evaluation import CalibrationMetrics, evaluate_calibration
from resolvekit.calibration.fitting import fit_isotonic, fit_platt, fit_stratified
from resolvekit.calibration.models import Calibrator
from scripts.calibrate.calibrate_common import (
    DEFAULT_OUTPUT_DIR,
    CalibrationRunConfig,
    build_countries_resolver,
    run_calibration,
)

logger = logging.getLogger(__name__)

DOMAIN = "geo"


class CountriesCalibrationMethod(StrEnum):
    """Calibrator variants fitted for the geo.countries domain."""

    PLATT_RAW = "platt_raw"
    ISOTONIC_RAW = "isotonic_raw"
    STRATIFIED_PLATT = "stratified_platt"
    STRATIFIED_ISOTONIC = "stratified_isotonic"


def _countries_fit_methods(
    *,
    train: list[LabeledExample],
    eval: list[LabeledExample],
    rng: random.Random,
    domain: str,
) -> dict[CountriesCalibrationMethod, tuple[Calibrator, CalibrationMetrics]]:
    """Fit countries calibrator variants using stratified-bucket fitting.

    Trains four variants: raw Platt and Isotonic, plus two stratified
    (Platt and Isotonic) using query-length bucketing.
    """
    train_scores: list[float] = [e.raw_score for e in train if e.raw_score is not None]
    train_labels: list[int] = [e.label for e in train if e.label is not None]
    train_query_lens: list[int] = [len(e.query_text) for e in train]

    eval_scores: list[float] = [e.raw_score for e in eval if e.raw_score is not None]
    eval_labels: list[int] = [e.label for e in eval if e.label is not None]
    eval_query_lens: list[int] = [len(e.query_text) for e in eval]

    results: dict[
        CountriesCalibrationMethod, tuple[Calibrator, CalibrationMetrics]
    ] = {}

    def fit_and_eval(
        key: CountriesCalibrationMethod,
        method: Literal["platt", "isotonic", "stratified"],
        sub_method: Literal["platt", "isotonic"] = "platt",
    ) -> None:
        cal: Calibrator
        if method == "platt":
            cal = fit_platt(train_scores, train_labels, domain=domain)
        elif method == "isotonic":
            cal = fit_isotonic(train_scores, train_labels, domain=domain)
        else:
            cal = fit_stratified(
                train_scores,
                train_labels,
                train_query_lens,
                domain=domain,
                sub_method=sub_method,
            )

        calibrated = [
            cal.predict(s, query_len=ql)
            for s, ql in zip(eval_scores, eval_query_lens, strict=False)
        ]
        metrics = evaluate_calibration(calibrated, eval_labels)
        results[key] = (cal, metrics)
        print(
            f"  {key:<24}  Brier={metrics.brier_score:.4f}  "
            f"LogLoss={metrics.log_loss:.4f}  "
            f"ECE={metrics.ece:.4f}  AdapECE={metrics.adaptive_ece:.4f}"
        )

    print("\nFITTING CALIBRATORS (eval on held-out 20%):")
    fit_and_eval(CountriesCalibrationMethod.PLATT_RAW, "platt")
    fit_and_eval(CountriesCalibrationMethod.ISOTONIC_RAW, "isotonic")
    fit_and_eval(
        CountriesCalibrationMethod.STRATIFIED_PLATT, "stratified", sub_method="platt"
    )
    fit_and_eval(
        CountriesCalibrationMethod.STRATIFIED_ISOTONIC,
        "stratified",
        sub_method="isotonic",
    )

    return results


_COUNTRIES_ADAPTERS = ["cldr", "geonames", "synthetic", "multilingual_names"]

CONFIG = CalibrationRunConfig(
    domain=DOMAIN,
    build_resolver=build_countries_resolver,
    fit_methods=_countries_fit_methods,
    output_subdir=DOMAIN,
    output_dir=DEFAULT_OUTPUT_DIR,
    limit_per_adapter=4000,
)


def run(*, config: CalibrationRunConfig = CONFIG) -> None:
    """Run countries calibration with the given config."""
    run_calibration(config=config, adapters=_COUNTRIES_ADAPTERS)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run()
