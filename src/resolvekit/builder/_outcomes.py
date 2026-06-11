"""Internal helpers for assembling failure outcomes from setup errors."""

from __future__ import annotations

from resolvekit.builder.inspection import InspectionOutcome
from resolvekit.builder.models import BuildOutcome, BuildStatus
from resolvekit.builder.pipeline import STAGES


def _failed_outcome(*, run_id: str, started_at: str, exc: Exception) -> BuildOutcome:
    """Build a failed outcome for pre-execution setup errors."""
    return BuildOutcome(
        run_id=run_id,
        status=BuildStatus.FAILED,
        stage=STAGES[0],
        errors=[f"{type(exc).__name__}: {exc}"],
        started_at=started_at,
    )


def _failed_inspection_outcome(
    *, run_id: str, started_at: str, exc: Exception
) -> InspectionOutcome:
    """Build a failed inspection outcome for pre-execution adapter errors."""
    return InspectionOutcome(
        run_id=run_id,
        errors=[f"{type(exc).__name__}: {exc}"],
        started_at=started_at,
    )
