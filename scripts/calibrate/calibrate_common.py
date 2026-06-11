"""Shared utilities for calibration scripts."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from resolvekit.builder.datapack_layout import iter_datapack_dirs
from resolvekit.calibration.dataset import (
    LabeledExample,
    label_examples,
    load_examples_jsonl,
    save_examples_jsonl,
)
from resolvekit.calibration.evaluation import CalibrationMetrics
from resolvekit.calibration.models import Calibrator, save_calibrator
from resolvekit.calibration.train import (
    ADAPTER_REGISTRY,
    query_stratified_split,
    run_adapters,
)
from resolvekit.core.api import Resolver

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path(".calibration_output")
DEFAULT_CACHE_DIR = Path(".calibration_cache")
# Canonical v1 layout — ``src/resolvekit/_data/<domain>/<subpath>/``.
DEFAULT_DATAPACKS_ROOT = Path("src/resolvekit/_data")
DEFAULT_SCORE_BINS: tuple[float, ...] = (
    0.50,
    0.55,
    0.60,
    0.65,
    0.70,
    0.75,
    0.80,
    0.85,
    0.90,
    0.95,
    1.01,
)


# Callable type for a domain-specific fitting loop. Receives the split products
# by keyword — train (training split), eval (eval split), rng (seeded Random),
# domain (e.g. "geo") — and returns {method enum: (calibrator, metrics)}.
type FitMethodsFn[M: StrEnum] = Callable[
    ..., dict[M, tuple[Calibrator, CalibrationMetrics]]
]


@dataclass(frozen=True, slots=True, kw_only=True)
class CalibrationRunConfig:
    """Orchestrator configuration for a single calibration run.

    Passed into :func:`run_calibration`; distinct from per-script entry
    settings objects (those are ``{Verb}Settings`` by convention).
    """

    domain: str
    build_resolver: Callable[..., Resolver]
    fit_methods: FitMethodsFn
    output_subdir: str
    eval_split: float = 0.2
    seed: int = 42
    limit_per_adapter: int | None = None
    examples_jsonl: Path | None = None
    save_examples: bool = False
    output_dir: Path = DEFAULT_OUTPUT_DIR
    cache_dir: Path = DEFAULT_CACHE_DIR
    extra_diagnostics: Callable[[list[LabeledExample]], None] | None = None


class CalibrationMetricKey(StrEnum):
    """Metrics available for calibrator selection."""

    BRIER_SCORE = "brier_score"
    LOG_LOSS = "log_loss"
    ECE = "ece"
    ADAPTIVE_ECE = "adaptive_ece"


def run_calibration[M: StrEnum](
    *,
    config: CalibrationRunConfig,
    datapacks_root: Path = DEFAULT_DATAPACKS_ROOT,
    adapters: list[str] | None = None,
) -> Path:
    """Run the shared calibration workflow for a domain.

    Orchestrates: resolver build → store fetch → adapter run / JSONL reload
    → label → valid filter → score-distribution render →
    optional extra_diagnostics → train/eval split →
    fit_methods → comparison render → pick_best_and_save.

    Args:
        config: Orchestrator configuration (domain, builders, fit callable, etc.).
        datapacks_root: Root directory containing datapack modules.
        adapters: Adapter names to run. Defaults to all registered for the domain.

    The ``config.fit_methods`` callable receives these kwargs:
        train  (list[LabeledExample]) — training split
        eval   (list[LabeledExample]) — eval split
        rng    (random.Random)        — seeded RNG instance
        domain (str)                  — domain name (e.g. "geo")
    and returns ``dict[M, tuple[Calibrator, CalibrationMetrics]]``.

    Returns:
        Path to the saved best-calibrator JSON file
        (``<config.output_dir>/<config.output_subdir>/<domain>_calibrator_best.json``).
    """
    domain_output_dir = config.output_dir / config.output_subdir
    domain_output_dir.mkdir(parents=True, exist_ok=True)

    # ── 0. Build resolver and fetch store ────────────────────────────
    resolver = config.build_resolver(datapacks_root=datapacks_root)
    store = resolver.store_for_domain(config.domain)

    # ── 1. Generate or reload labeled examples ────────────────────────
    if config.examples_jsonl is not None and config.examples_jsonl.exists():
        labeled: list[LabeledExample] = load_examples_jsonl(config.examples_jsonl)
        logger.info(
            "Loaded %d labeled examples from %s", len(labeled), config.examples_jsonl
        )
    else:
        adapter_names = adapters or list(ADAPTER_REGISTRY.get(config.domain, {}).keys())
        all_pairs = run_adapters(
            config.domain,
            adapter_names,
            store,
            limit_per_adapter=config.limit_per_adapter,
            cache_dir=config.cache_dir,
        )

        t0 = time.time()
        labeled = label_examples(all_pairs, resolver)
        label_time = time.time() - t0
        logger.info(
            "Labeled %d pairs in %.1fs (%.0f qps)",
            len(all_pairs),
            label_time,
            len(all_pairs) / max(label_time, 0.001),
        )

        if config.save_examples:
            examples_path = domain_output_dir / f"{config.domain}_examples.jsonl"
            save_examples_jsonl(labeled, examples_path)
            logger.info("Examples saved to %s", examples_path)

    # ── 2. Filter to valid examples ───────────────────────────────────
    valid = [e for e in labeled if e.raw_score is not None and e.label is not None]

    # ── 3. Score distribution ─────────────────────────────────────────
    dist_rows = format_score_distribution(labeled=valid)
    print(render_score_distribution(rows=dist_rows))

    # ── 4. Optional per-domain diagnostics ───────────────────────────
    if config.extra_diagnostics is not None:
        config.extra_diagnostics(labeled)

    # ── 5. Train / eval split ─────────────────────────────────────────
    rng = random.Random(config.seed)
    train, eval_ = query_stratified_split(
        examples=valid, eval_split=config.eval_split, rng=rng
    )
    logger.info(
        "Split: train=%d eval=%d",
        len(train),
        len(eval_),
    )

    # ── 6. Fit calibrators ────────────────────────────────────────────
    results: dict[M, tuple[Calibrator, CalibrationMetrics]] = config.fit_methods(
        train=train, eval=eval_, rng=rng, domain=config.domain
    )

    # ── 7. Comparison summary ─────────────────────────────────────────
    comparison_rows = format_calibrator_comparison(results=results)
    print(render_calibrator_comparison(rows=comparison_rows))

    # ── 8. Save best calibrator ───────────────────────────────────────
    output_path = domain_output_dir / f"{config.domain}_calibrator_best.json"
    best_key, _ = pick_best_and_save(
        results=results,
        output_path=output_path,
        metric=CalibrationMetricKey.ADAPTIVE_ECE,
    )
    logger.info("Best by Adaptive ECE: %s → %s", best_key, output_path)
    return output_path


@dataclass(frozen=True, slots=True, kw_only=True)
class ScoreDistributionRow:
    """One row in a score-distribution table."""

    bin_label: str
    total: int
    pos: int
    neg: int
    accuracy: float
    pct_of_data: float


@dataclass(frozen=True, slots=True, kw_only=True)
class CalibratorComparisonRow:
    """One row in the calibrator comparison table."""

    method: str
    brier_score: float
    log_loss: float
    ece: float
    adaptive_ece: float


def format_score_distribution(
    *,
    labeled: Sequence[LabeledExample],
    bin_edges: Sequence[float] = DEFAULT_SCORE_BINS,
) -> list[ScoreDistributionRow]:
    """Build structured score-distribution rows from pre-filtered labeled examples.

    Args:
        labeled: Examples where ``raw_score`` and ``label`` are both non-None
            (i.e. already filtered to valid examples).
        bin_edges: Monotone sequence of bin boundaries (e.g. [0.50, 0.55, ..., 1.01]).

    Returns:
        One :class:`ScoreDistributionRow` per bin interval.
    """
    total_valid = len(labeled)
    rows: list[ScoreDistributionRow] = []
    for i in range(len(bin_edges) - 1):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        bin_ex = [
            e for e in labeled if e.raw_score is not None and lo <= e.raw_score < hi
        ]
        n_pos = sum(1 for e in bin_ex if e.label == 1)
        n_neg = len(bin_ex) - n_pos
        acc = n_pos / len(bin_ex) if bin_ex else 0.0
        pct = 100.0 * len(bin_ex) / total_valid if total_valid else 0.0
        rows.append(
            ScoreDistributionRow(
                bin_label=f"[{lo:.2f}, {hi:.2f})",
                total=len(bin_ex),
                pos=n_pos,
                neg=n_neg,
                accuracy=acc,
                pct_of_data=pct,
            )
        )
    return rows


def render_score_distribution(*, rows: list[ScoreDistributionRow]) -> str:
    """Render score-distribution rows as a formatted table string (6 columns).

    Args:
        rows: Rows produced by :func:`format_score_distribution`.

    Returns:
        Multi-line string with header, separator, and one data row per bin.
    """
    lines: list[str] = [
        "\n" + "=" * 70,
        "SCORE DISTRIBUTION ANALYSIS",
        "=" * 70,
        f"{'Bin':>14}  {'Total':>7}  {'Pos':>6}  {'Neg':>6}  {'Accuracy':>8}  {'% of data':>9}",
        "-" * 70,
    ]
    for row in rows:
        lines.append(
            f"  {row.bin_label:>12}  {row.total:>7}  {row.pos:>6}  {row.neg:>6}"
            f"  {row.accuracy:>7.1%}  {row.pct_of_data:>8.1f}%"
        )
    return "\n".join(lines)


def format_calibrator_comparison[M: StrEnum](
    *,
    results: dict[M, tuple[Calibrator, CalibrationMetrics]],
    method_order: Sequence[M] | None = None,
) -> list[CalibratorComparisonRow]:
    """Build comparison rows from a fit-results dict.

    Args:
        results: Mapping from method enum value to ``(calibrator, metrics)``.
        method_order: Order to emit rows. Defaults to ``results`` insertion order.

    Returns:
        One :class:`CalibratorComparisonRow` per method.
    """
    order = list(method_order) if method_order is not None else list(results)
    rows = []
    for key in order:
        if key not in results:
            continue
        _, metrics = results[key]
        rows.append(
            CalibratorComparisonRow(
                method=key,
                brier_score=metrics.brier_score,
                log_loss=metrics.log_loss,
                ece=metrics.ece,
                adaptive_ece=metrics.adaptive_ece,
            )
        )
    return rows


def render_calibrator_comparison(*, rows: list[CalibratorComparisonRow]) -> str:
    """Render comparison rows as a formatted table string.

    Args:
        rows: Rows produced by :func:`format_calibrator_comparison`.

    Returns:
        Multi-line string with header, separator, and one data row per method.
    """
    lines: list[str] = [
        "\n" + "=" * 70,
        "COMPARISON SUMMARY",
        "=" * 70,
        f"{'Method':<22}  {'Brier':>7}  {'LogLoss':>8}  {'ECE':>7}  {'AdapECE':>8}",
        "-" * 70,
    ]
    for row in rows:
        lines.append(
            f"  {row.method:<20}  {row.brier_score:>7.4f}  {row.log_loss:>8.4f}"
            f"  {row.ece:>7.4f}  {row.adaptive_ece:>8.4f}"
        )
    return "\n".join(lines)


def pick_best_and_save[M: StrEnum](
    *,
    results: dict[M, tuple[Calibrator, CalibrationMetrics]],
    output_path: Path,
    metric: CalibrationMetricKey = CalibrationMetricKey.ADAPTIVE_ECE,
) -> tuple[M, Calibrator]:
    """Select the best calibrator by *metric* and persist it to *output_path*.

    Before selecting by *metric*, filters out inverted variants — those where
    ``predict(0.9) <= predict(0.1)``. If every variant is inverted, raises
    ``ValueError`` rather than persisting a directionally-wrong calibrator.

    Args:
        results: Mapping from method enum value to ``(calibrator, metrics)``.
        output_path: Destination JSON file.
        metric: Which :class:`CalibrationMetricKey` to minimise. Defaults to
            ``ADAPTIVE_ECE``.

    Returns:
        ``(best_method_key, best_calibrator)`` tuple.

    Raises:
        ValueError: If all variants are inverted (predict(0.9) <= predict(0.1)).
    """
    filtered = {
        k: v for k, v in results.items() if v[0].predict(0.9) > v[0].predict(0.1)
    }
    if not filtered:
        raise ValueError(
            "All calibrator variants are inverted (predict(0.9) <= predict(0.1))"
            " — check training data / score features"
        )
    best_key = min(filtered, key=lambda k: getattr(filtered[k][1], metric.value))
    best_cal = filtered[best_key][0]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_calibrator(best_cal, output_path)
    return best_key, best_cal


def build_calibration_resolver(
    *,
    datapacks_root: Path = DEFAULT_DATAPACKS_ROOT,
    packs: list[str] | None = None,
) -> Resolver:
    """Build a Resolver from the datapack root directory.

    Supports the v1 flat layout (``<root>/<domain>/<subpath>/metadata.json``)
    as well as the legacy versioned layout
    (``<root>/<module_id>/<version>/metadata.json``). For the legacy layout,
    the highest-versioned subdir wins per module.

    Args:
        datapacks_root: Root directory containing datapack modules.
        packs: Optional pack filter forwarded to :meth:`Resolver.from_datapacks`.
            ``None`` loads all packs found under *datapacks_root*.

    Returns:
        Configured :class:`Resolver` instance.

    Raises:
        FileNotFoundError: If no datapacks are found under *datapacks_root*.
    """
    datapack_dirs: list[str | Path] = [
        *iter_datapack_dirs(datapacks_root=datapacks_root)
    ]
    if not datapack_dirs:
        raise FileNotFoundError(
            f"No datapacks found under {datapacks_root}. "
            "Build datapacks first or pass a valid datapacks_root."
        )
    return Resolver.from_datapacks(datapack_paths=datapack_dirs, domains=packs)


def build_countries_resolver(
    *, datapacks_root: Path = DEFAULT_DATAPACKS_ROOT
) -> Resolver:
    """Build a Resolver scoped to the geo.countries pack and adjacent geo packs.

    Loads ``geo/countries``, ``geo/continental_unions``, and ``geo/regions``
    from *datapacks_root* — the minimal set needed for countries-only calibration
    without pulling in the large admin/cities downloads.

    Args:
        datapacks_root: Root directory containing module subtrees.

    Returns:
        Configured :class:`Resolver` instance.

    Raises:
        FileNotFoundError: If any of the three required datapack dirs is missing.
    """
    geo_root = datapacks_root / "geo"
    pack_dirs: list[Path] = [
        geo_root / "countries",
        geo_root / "continental_unions",
        geo_root / "regions",
    ]
    for d in pack_dirs:
        if not d.exists():
            raise FileNotFoundError(f"Datapack missing: {d}")
    return Resolver.from_datapacks(
        datapack_paths=[str(p) for p in pack_dirs],
        domains=["geo"],
    )
