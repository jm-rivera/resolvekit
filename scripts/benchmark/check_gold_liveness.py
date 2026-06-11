"""Gold-liveness sweep — finds benchmark rows whose answer can never be scored correct.

For every committed benchmark dataset, checks that each row's gold answer set
(``expected_ids`` plus, for ``eval_parse``, the ``expected_id`` inside
``expected_spans``) still points to a live entity in the loaded packs.

The scoring contract (``benchmarks/core/metrics.py``) marks a row correct only when
``expected_ids`` intersects the resolver's ``match_ids`` — and the resolvekit adapter
emits ``match_ids = (result.entity_id,)``, always a live entity id. So a row whose
gold ids are *all* dead (no entity exists for any of them) is a guaranteed miss that
looks like a model weakness but is really benchmark drift: an entity id that changed
or was removed when the packs were rebuilt, or a gold written in the wrong id-space.

Liveness is checked against ``Resolver.auto()`` — the same store the committed
``latest.json`` was scored against, including any locally-cached remote tiers. A
dataset that comes back ~100% dead means its deep tier is not loaded locally (a tier
artifact, not bad golds); the report flags that case instead of crying wolf.

Configuration: edit LivenessConfig in __main__ (no argparse).
Run: uv run python -m scripts.benchmark.check_gold_liveness
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from resolvekit import Resolver

_REPO_ROOT = Path(__file__).parent.parent.parent

# A dataset coming back more dead than this is treated as a missing-tier artifact
# (its deep entities aren't loaded locally), not a wall of bad golds.
_TIER_ARTIFACT_THRESHOLD = 0.80


@dataclass(frozen=True, kw_only=True)
class LivenessConfig:
    """Paths and reporting options for the sweep.

    Args:
        data_dir: Directory holding the committed ``<dataset>.parquet`` files.
        datasets: Dataset names to check; empty means every parquet in data_dir.
        examples_per_dataset: How many dead-gold rows to print per dataset.
    """

    data_dir: Path = _REPO_ROOT / "benchmarks" / "data"
    datasets: tuple[str, ...] = ()
    examples_per_dataset: int = 8


@dataclass
class _DatasetReport:
    name: str
    total_rows: int = 0
    scored_rows: int = 0  # rows that carry at least one gold id
    dead_rows: int = 0
    examples: list[tuple[str, str, list[str]]] = field(default_factory=list)

    @property
    def dead_fraction(self) -> float:
        return self.dead_rows / self.scored_rows if self.scored_rows else 0.0

    @property
    def likely_tier_artifact(self) -> bool:
        return self.scored_rows > 0 and self.dead_fraction >= _TIER_ARTIFACT_THRESHOLD


def _gold_ids(row: dict) -> list[str]:
    """Collect every candidate gold id for a row, across both id carriers."""
    ids: list[str] = list(row.get("expected_ids") or [])

    spans_raw = row.get("expected_spans")
    if spans_raw:
        for span in json.loads(spans_raw):
            span_id = span.get("expected_id")
            if span_id:
                ids.append(span_id)

    return ids


def _check_dataset(
    *, path: Path, resolver: Resolver, examples_cap: int
) -> _DatasetReport:
    report = _DatasetReport(name=path.stem)
    get_entity = resolver._runner.get_entity

    frame = pl.read_parquet(path)
    columns = set(frame.columns)
    # Read only the columns we need, tolerating eval_parse's extra span column.
    wanted = [c for c in ("query", "expected_ids", "expected_spans") if c in columns]

    for row in frame.select(wanted).iter_rows(named=True):
        report.total_rows += 1
        gold = _gold_ids(row)
        if not gold:
            continue  # no answer set → metrics skip it; not a liveness failure
        report.scored_rows += 1

        live = [gid for gid in gold if get_entity(gid) is not None]
        if not live:
            report.dead_rows += 1
            if len(report.examples) < examples_cap:
                report.examples.append((row.get("query", ""), "", gold))

    return report


def run(*, config: LivenessConfig) -> int:
    """Sweep every dataset and print a drift report.

    Returns:
        The number of datasets with genuine dead-gold rows (tier artifacts excluded).
    """
    resolver = Resolver.auto()

    names = config.datasets or tuple(
        sorted(p.stem for p in config.data_dir.glob("*.parquet"))
    )

    reports = [
        _check_dataset(
            path=config.data_dir / f"{name}.parquet",
            resolver=resolver,
            examples_cap=config.examples_per_dataset,
        )
        for name in names
    ]

    print(f"\n{'dataset':<28} {'rows':>6} {'scored':>7} {'dead':>6} {'dead %':>8}")
    print("-" * 60)
    for r in reports:
        flag = "  ← likely missing tier" if r.likely_tier_artifact else ""
        print(
            f"{r.name:<28} {r.total_rows:>6} {r.scored_rows:>7} "
            f"{r.dead_rows:>6} {r.dead_fraction * 100:>7.1f}%{flag}"
        )

    genuine = [r for r in reports if r.dead_rows and not r.likely_tier_artifact]
    for r in genuine:
        print(f"\n=== {r.name}: {r.dead_rows} dead-gold rows (sample) ===")
        for query, _, gold in r.examples:
            print(f"  {query!r:40} gold={gold}")

    artifacts = [r for r in reports if r.likely_tier_artifact]
    if artifacts:
        names_str = ", ".join(r.name for r in artifacts)
        print(
            f"\nSkipped as missing-tier artifacts (not bad golds): {names_str}. "
            "Re-run with those packs' remote tiers downloaded to check them."
        )

    print(
        f"\n{len(genuine)} dataset(s) with genuine dead-gold rows; "
        f"{sum(r.dead_rows for r in genuine)} rows total."
    )
    return len(genuine)


if __name__ == "__main__":
    run(config=LivenessConfig())
