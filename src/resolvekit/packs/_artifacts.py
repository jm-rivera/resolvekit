"""Scoring artifact loader shared by all packs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resolvekit.calibration.models import Calibrator
    from resolvekit.core.engine.interfaces import ScoringModel


@dataclass(frozen=True)
class ScoringArtifacts:
    """A pack's optional scoring model + calibrator, either may be None."""

    model: ScoringModel | None = None
    calibrator: Calibrator | None = None


def load_scoring_artifacts(
    *,
    model_path: str | None,
    calibrator_path: str | None,
) -> ScoringArtifacts:
    """Load the optional scoring model and calibrator from disk.

    Imports the calibration loaders lazily so packs stay importable without
    the calibration extra installed; a None path yields a None field.
    """
    model: ScoringModel | None = None
    if model_path:
        from resolvekit.calibration.scoring_model import load_scoring_model

        model = load_scoring_model(model_path)

    calibrator: Calibrator | None = None
    if calibrator_path:
        from resolvekit.calibration.models import load_calibrator

        calibrator = load_calibrator(calibrator_path)

    return ScoringArtifacts(model=model, calibrator=calibrator)
