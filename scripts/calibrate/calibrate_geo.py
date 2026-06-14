#!/usr/bin/env python3
"""Train and evaluate geo calibrators.

Fits multiple calibrator variants (Platt, isotonic, with different
rebalancing strategies), prints diagnostics, and saves the best one
to .calibration_output/geo/.

Run via:
    uv run python -m scripts.calibrate.calibrate_geo

To customize, edit the kwargs in the ``__main__`` block at the bottom of
the file (or import ``run()`` and pass a CalibrationRunConfig from a notebook).
"""

from __future__ import annotations

import json
import logging
import random
import shutil
from enum import StrEnum
from pathlib import Path

from resolvekit.builder.utils import sha256_file
from resolvekit.calibration.dataset import LabeledExample
from resolvekit.calibration.evaluation import CalibrationMetrics, evaluate_calibration
from resolvekit.calibration.fitting import fit_isotonic, fit_platt
from resolvekit.calibration.models import Calibrator
from scripts.calibrate.calibrate_common import (
    CalibrationRunConfig,
    build_countries_resolver,
    run_calibration,
)

logger = logging.getLogger(__name__)

DOMAIN = "geo"

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_CALIBRATOR = (
    PROJECT_ROOT / "src/resolvekit/_data/geo/countries/geo_calibrator.json"
)


class GeoCalibrationMethod(StrEnum):
    """Calibrator variants fitted for the geo domain."""

    PLATT_RAW = "platt_raw"
    PLATT_BALANCED = "platt_balanced"
    PLATT_1TO1 = "platt_1to1"
    ISOTONIC_BALANCED = "isotonic_balanced"
    ISOTONIC_1TO1 = "isotonic_1to1"


def _geo_fit_methods(
    *,
    train: list[LabeledExample],
    eval: list[LabeledExample],
    rng: random.Random,
    domain: str,
) -> dict[GeoCalibrationMethod, tuple[Calibrator, CalibrationMetrics]]:
    """Fit geo calibrator variants on the given train/eval split.

    Trains five variants: raw Platt, 2:1-balanced Platt and Isotonic,
    1:1-balanced Platt and Isotonic.
    """
    train_pos = [e for e in train if e.label == 1]
    train_neg = [e for e in train if e.label == 0]

    eval_scores = [e.raw_score for e in eval if e.raw_score is not None]
    eval_labels = [e.label for e in eval if e.label is not None]

    results: dict[GeoCalibrationMethod, tuple[Calibrator, CalibrationMetrics]] = {}

    def fit_and_eval(
        key: GeoCalibrationMethod,
        train_scores: list[float],
        train_labels: list[int],
        method: str,
    ) -> None:
        if method == "platt":
            cal = fit_platt(train_scores, train_labels, domain=domain)
        else:
            cal = fit_isotonic(train_scores, train_labels, domain=domain)
        calibrated = [cal.predict(s) for s in eval_scores]
        metrics = evaluate_calibration(calibrated, eval_labels)
        results[key] = (cal, metrics)

    # Platt on raw (unbalanced) training data
    raw_train = train_pos + train_neg
    rng.shuffle(raw_train)
    raw_scores = [e.raw_score for e in raw_train if e.raw_score is not None]
    raw_labels = [e.label for e in raw_train if e.label is not None]

    fit_and_eval(GeoCalibrationMethod.PLATT_RAW, raw_scores, raw_labels, "platt")

    # Platt / Isotonic on 2:1 downsampled negatives
    max_neg = min(len(train_neg), 2 * len(train_pos))
    bal_neg = train_neg[:max_neg]
    bal_train = train_pos + bal_neg
    rng.shuffle(bal_train)
    bal_scores = [e.raw_score for e in bal_train if e.raw_score is not None]
    bal_labels = [e.label for e in bal_train if e.label is not None]

    fit_and_eval(GeoCalibrationMethod.PLATT_BALANCED, bal_scores, bal_labels, "platt")
    fit_and_eval(
        GeoCalibrationMethod.ISOTONIC_BALANCED, bal_scores, bal_labels, "isotonic"
    )

    # Platt / Isotonic on 1:1 balanced
    max_neg_11 = min(len(train_neg), len(train_pos))
    bal11_train = train_pos + train_neg[:max_neg_11]
    rng.shuffle(bal11_train)
    bal11_scores = [e.raw_score for e in bal11_train if e.raw_score is not None]
    bal11_labels = [e.label for e in bal11_train if e.label is not None]

    fit_and_eval(GeoCalibrationMethod.PLATT_1TO1, bal11_scores, bal11_labels, "platt")
    fit_and_eval(
        GeoCalibrationMethod.ISOTONIC_1TO1, bal11_scores, bal11_labels, "isotonic"
    )

    return results


def _geo_extra_diagnostics(labeled: list[LabeledExample]) -> None:
    """Print per-adapter and per-mutation-type breakdowns (geo-only)."""
    # Per-adapter breakdown
    print("\n" + "=" * 70)
    print("PER-ADAPTER BREAKDOWN")
    print("=" * 70)
    adapter_names = sorted({e.source_adapter for e in labeled if e.source_adapter})
    for adapter_name in adapter_names:
        all_adapter_ex = [e for e in labeled if e.source_adapter == adapter_name]
        adapter_ex = [
            e for e in all_adapter_ex if e.raw_score is not None and e.label is not None
        ]
        no_cand = len(all_adapter_ex) - len(adapter_ex)
        if not all_adapter_ex:
            continue
        a_pos = sum(1 for e in adapter_ex if e.label == 1)
        a_neg = len(adapter_ex) - a_pos
        scores_pos = sorted([e.raw_score for e in adapter_ex if e.label == 1])
        scores_neg = sorted([e.raw_score for e in adapter_ex if e.label == 0])
        match_rate = a_pos / len(adapter_ex) if adapter_ex else 0
        no_cand_rate = no_cand / len(all_adapter_ex) if all_adapter_ex else 0
        print(f"\n  {adapter_name}:")
        print(
            f"    Pairs: {len(all_adapter_ex)}, No-candidate: {no_cand} ({no_cand_rate:.1%}), With candidates: {len(adapter_ex)}"
        )
        print(
            f"    Match rate: {a_pos}/{len(adapter_ex)} = {match_rate:.1%}  (pos={a_pos}, neg={a_neg})"
        )
        if scores_pos:
            print(
                f"    Positive scores: min={scores_pos[0]:.3f} "
                f"median={scores_pos[len(scores_pos) // 2]:.3f} "
                f"max={scores_pos[-1]:.3f}"
            )
        if scores_neg:
            print(
                f"    Negative scores: min={scores_neg[0]:.3f} "
                f"median={scores_neg[len(scores_neg) // 2]:.3f} "
                f"max={scores_neg[-1]:.3f}"
            )

    # Per-mutation-type breakdown (synthetic only)
    mutation_examples = [e for e in labeled if e.mutation_type]
    if mutation_examples:
        print("\n" + "=" * 70)
        print("PER-MUTATION-TYPE BREAKDOWN (synthetic)")
        print("=" * 70)
        mutation_types = sorted({e.mutation_type for e in mutation_examples})
        print(
            f"  {'Mutation type':<28}  {'Pairs':>6}  {'No-cand':>7}  {'NoCand%':>7}  {'Match':>6}  {'Match%':>7}"
        )
        print("  " + "-" * 68)
        for mt in mutation_types:
            mt_all = [e for e in mutation_examples if e.mutation_type == mt]
            mt_valid = [
                e for e in mt_all if e.raw_score is not None and e.label is not None
            ]
            mt_no_cand = len(mt_all) - len(mt_valid)
            mt_pos = sum(1 for e in mt_valid if e.label == 1)
            no_cand_pct = mt_no_cand / len(mt_all) if mt_all else 0
            match_pct = mt_pos / len(mt_valid) if mt_valid else 0
            print(
                f"  {mt:<28}  {len(mt_all):>6}  {mt_no_cand:>7}  {no_cand_pct:>6.1%}  {mt_pos:>6}  {match_pct:>6.1%}"
            )


CONFIG = CalibrationRunConfig(
    domain=DOMAIN,
    build_resolver=build_countries_resolver,
    fit_methods=_geo_fit_methods,
    output_subdir=DOMAIN,
    extra_diagnostics=_geo_extra_diagnostics,
)


def _refresh_calibrator_checksum(calibrator_path: Path) -> None:
    """Re-stamp the pack's metadata.json with the installed calibrator's checksum.

    Packaging records the calibrator checksum at build time; recalibrating in
    place replaces the file, so without this the loader rejects the pack on a
    calibrator checksum mismatch. Only the one checksum field changes — key order
    and the rest of the metadata are preserved.
    """
    metadata_path = calibrator_path.parent / "metadata.json"
    if not metadata_path.exists():
        logger.warning(
            "No metadata.json beside %s; checksum not refreshed", calibrator_path
        )
        return
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    checksums = metadata.get("checksums")
    if not isinstance(checksums, dict) or "calibrator" not in checksums:
        return
    checksums["calibrator"] = sha256_file(calibrator_path)
    metadata_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    logger.info("Refreshed calibrator checksum in %s", metadata_path)


def run(*, config: CalibrationRunConfig = CONFIG) -> None:
    """Run geo calibration with the given config."""
    best_path = run_calibration(config=config)
    shutil.copy2(best_path, _DATA_CALIBRATOR)
    _refresh_calibrator_checksum(_DATA_CALIBRATOR)
    logger.info("Installed calibrator → %s", _DATA_CALIBRATOR)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run()
