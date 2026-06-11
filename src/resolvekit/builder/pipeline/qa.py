"""Quality gate checks for packaged domain artifacts."""

from __future__ import annotations

from pathlib import Path

from resolvekit.builder.models import QualityPolicy
from resolvekit.builder.sqlite import validate_domain_db

DRIFT_CHECKS: tuple[tuple[str, str], ...] = (
    ("entity_count", "max_entity_drop_pct"),
    ("names_coverage", "max_names_coverage_drop_pct"),
    ("codes_coverage", "max_codes_coverage_drop_pct"),
    ("relations_density", "max_relations_density_drop_pct"),
)


def suspicious_drift_issues(
    *,
    module_id: str,
    domain: str,
    current_metrics: dict[str, float | int],
    quality_policy: QualityPolicy,
    previous_db: Path | None,
) -> list[str]:
    """Return suspicious-drop findings vs the datapack this build replaced.

    *previous_db* is a snapshot of the prior on-disk pack, taken before this
    build overwrote it. ``None`` (first build) means no baseline → no findings.
    """
    if previous_db is None or not previous_db.exists():
        return []

    previous_metrics, _ = validate_domain_db(previous_db)

    def pct_drop(previous: float, current: float) -> float:
        if previous <= 0:
            return 0.0
        return max(0.0, (previous - current) / previous)

    checks = [
        (
            metric_key,
            float(getattr(quality_policy, threshold_attr)),
            pct_drop(
                float(previous_metrics[metric_key]),
                float(current_metrics[metric_key]),
            ),
        )
        for metric_key, threshold_attr in DRIFT_CHECKS
    ]

    problems = [
        f"{metric} drop {drop:.2%} > {limit:.2%}"
        for metric, limit, drop in checks
        if drop > limit
    ]
    return [f"{module_id}/{domain}: {problem}" for problem in problems]
