"""Release-record construction for build outcomes.

These helpers describe what a build produced so the outcome can report it.
The release ledger is written explicitly by ``scripts/release/release_data.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from resolvekit.builder.models import ReleaseRecord

if TYPE_CHECKING:
    from resolvekit.builder.pipeline.types import DomainArtifacts, ReleaseCandidate


def build_release_records(
    candidates: Sequence[ReleaseCandidate],
    *,
    run_id: str,
) -> list[ReleaseRecord]:
    """Describe each built candidate as a ``ReleaseRecord`` (no registry write)."""
    return [
        ReleaseRecord(
            module_id=release.recipe.module_id,
            version=release.version,
            run_id=run_id,
            output_path=release.output_path,
            domains=[release.recipe.domain],
            metrics=flatten_domain_metrics(release.domain_artifacts),
            reports={
                "changelog": str(release.output_path / "changelog.md"),
                "qa_report": str(release.output_path / "qa_report.json"),
            },
        )
        for release in candidates
    ]


def flatten_domain_metrics(
    domain_artifacts: dict[str, DomainArtifacts],
) -> dict[str, float | int]:
    """Flatten nested domain metrics to ``<domain>.<metric>`` keys."""
    return {
        f"{domain}.{metric_name}": value
        for domain, artifact in domain_artifacts.items()
        for metric_name, value in artifact.metrics.items()
    }
