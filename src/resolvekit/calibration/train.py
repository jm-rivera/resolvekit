"""Calibration training pipeline.

Provides a programmatic API for generating calibration data, fitting
calibrators, and evaluating results. Used by scripts or notebooks:

    from resolvekit.calibration.train import train_calibrator

    result = train_calibrator(
        resolver=resolver,
        domain="geo",
        adapter_names=["cldr", "geonames"],
    )
    print(result.metrics)
"""

from __future__ import annotations

import logging
import random
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from resolvekit.calibration.adapters.cldr import cldr_generate_geo_pairs
from resolvekit.calibration.adapters.geonames import geonames_generate_geo_pairs
from resolvekit.calibration.adapters.multilingual_names import (
    multilingual_generate_geo_pairs,
)
from resolvekit.calibration.adapters.synthetic import (
    synthetic_generate_geo_pairs,
    synthetic_generate_org_pairs,
)
from resolvekit.calibration.adapters.wikidata import (
    wikidata_generate_geo_pairs,
    wikidata_generate_org_pairs,
)
from resolvekit.calibration.dataset import (
    LabeledExample,
    label_examples,
    save_examples_jsonl,
)
from resolvekit.calibration.evaluation import (
    CalibrationMetrics,
    evaluate_calibration,
    find_exact_code_min_score,
    find_f1_threshold,
)
from resolvekit.calibration.fitting import (
    fit_isotonic,
    fit_platt,
    fit_scoring_model,
    fit_stratified,
)
from resolvekit.calibration.models import (
    IsotonicCalibrator,
    PlattCalibrator,
    StratifiedCalibrator,
    save_calibrator,
)
from resolvekit.calibration.scoring_model import (
    LogisticScoringModel,
    save_scoring_model,
)

if TYPE_CHECKING:
    from resolvekit.core.api.resolver import Resolver
    from resolvekit.core.store import EntityStore

logger = logging.getLogger(__name__)

# Maps adapter names to callables per domain.
# Every value is a kwargs-only free function returning list[LabeledExample].
ADAPTER_REGISTRY: dict[str, dict[str, Callable[..., list[LabeledExample]]]] = {
    "geo": {
        "cldr": cldr_generate_geo_pairs,
        "geonames": geonames_generate_geo_pairs,
        "multilingual_names": multilingual_generate_geo_pairs,
        "wikidata": wikidata_generate_geo_pairs,
        "synthetic": synthetic_generate_geo_pairs,
    },
    "org": {
        "wikidata": wikidata_generate_org_pairs,
        "synthetic": synthetic_generate_org_pairs,
    },
}


@dataclass(frozen=True)
class TrainResult:
    """Result of a calibration training run."""

    calibrator: PlattCalibrator | IsotonicCalibrator | StratifiedCalibrator
    metrics: CalibrationMetrics | None
    n_pairs: int
    n_labeled: int
    n_train: int
    n_eval: int
    output_path: Path | None = None


def _deduplicate_examples(
    examples: list[LabeledExample],
) -> list[LabeledExample]:
    """Deduplicate by (query_text, expected_entity_id), keeping first occurrence."""
    seen: set[tuple[str, str]] = set()
    result: list[LabeledExample] = []
    for e in examples:
        key = (e.query_text.lower(), e.expected_entity_id)
        if key not in seen:
            seen.add(key)
            result.append(e)
    return result


def run_adapters(
    domain: str,
    adapter_names: list[str],
    store: EntityStore,
    *,
    limit_per_adapter: int | None = None,
    cache_dir: str | Path | None = None,
) -> list[LabeledExample]:
    """Run calibration adapters and return deduplicated pairs."""
    domain_registry = ADAPTER_REGISTRY.get(domain, {})
    all_pairs: list[LabeledExample] = []
    resolved_cache_dir = Path(cache_dir) if cache_dir is not None else None

    for name in adapter_names:
        fn = domain_registry.get(name)
        if fn is None:
            logger.warning("Unknown adapter '%s' for domain '%s'", name, domain)
            continue

        logger.info("Running adapter '%s'...", name)
        try:
            # Every adapter shares the uniform kwargs-only signature.
            pairs = fn(
                store=store, cache_dir=resolved_cache_dir, limit=limit_per_adapter
            )
        except Exception:
            logger.warning("Adapter '%s' failed", name, exc_info=True)
            pairs = []
        logger.info("  generated %d pairs", len(pairs))
        all_pairs.extend(pairs)

    if not all_pairs:
        raise ValueError("No pairs generated. Check adapter names and store.")

    # Cross-adapter dedup before labeling
    n_before = len(all_pairs)
    all_pairs = _deduplicate_examples(all_pairs)
    logger.info("Cross-adapter dedup: %d → %d pairs", n_before, len(all_pairs))

    return all_pairs


def query_stratified_split(
    *,
    examples: list[LabeledExample],
    eval_split: float,
    rng: random.Random,
) -> tuple[list[LabeledExample], list[LabeledExample]]:
    """Split by query text so all examples for a query go to same split.

    Falls back to class-stratified split if the query split produces
    a split with only one class.
    """
    if eval_split <= 0.0:
        result = list(examples)
        rng.shuffle(result)
        return result, []

    query_groups: dict[str, list[LabeledExample]] = defaultdict(list)
    for e in examples:
        query_groups[e.query_text.lower()].append(e)

    query_keys = sorted(query_groups.keys())
    rng.shuffle(query_keys)

    n_eval_queries = max(1, int(len(query_keys) * eval_split))
    eval_query_keys = set(query_keys[:n_eval_queries])

    train_examples = []
    eval_examples = []
    for key in query_keys:
        if key in eval_query_keys:
            eval_examples.extend(query_groups[key])
        else:
            train_examples.extend(query_groups[key])

    rng.shuffle(train_examples)

    # Verify both splits have both classes
    if len({e.label for e in train_examples}) < 2 or (
        eval_examples and len({e.label for e in eval_examples}) < 2
    ):
        # Fallback to class-stratified split
        positives = [e for e in examples if e.label == 1]
        negatives = [e for e in examples if e.label == 0]
        rng.shuffle(positives)
        rng.shuffle(negatives)
        pos_split = max(1, int(len(positives) * (1.0 - eval_split)))
        neg_split = max(1, int(len(negatives) * (1.0 - eval_split)))
        # Ensure eval also gets at least one of each class; if impossible,
        # drop eval entirely so we don't produce misleading metrics.
        if pos_split >= len(positives) or neg_split >= len(negatives):
            logger.warning(
                "Not enough examples for a two-class eval split "
                "(positives=%d, negatives=%d). Training on all data with no eval.",
                len(positives),
                len(negatives),
            )
            train_examples = positives + negatives
            eval_examples = []
        else:
            train_examples = positives[:pos_split] + negatives[:neg_split]
            eval_examples = positives[pos_split:] + negatives[neg_split:]
        rng.shuffle(train_examples)

    return train_examples, eval_examples


def train_calibrator(
    resolver: Resolver,
    domain: str,
    *,
    adapter_names: list[str] | None = None,
    method: Literal["platt", "isotonic", "stratified"] = "platt",
    limit_per_adapter: int | None = None,
    eval_split: float = 0.2,
    cache_dir: str | Path | None = None,
    output_path: str | Path | None = None,
    examples_output: str | Path | None = None,
    seed: int = 42,
) -> TrainResult:
    """Train a calibrator end-to-end: adapters -> label -> fit -> evaluate.

    Args:
        resolver: A loaded Resolver instance.
        domain: Domain to calibrate ("geo" or "org").
        adapter_names: Which data adapters to run (default: all for domain).
        method: "platt" or "isotonic".
        limit_per_adapter: Max examples per adapter.
        eval_split: Fraction held out for evaluation (0-1).
        cache_dir: Directory for caching adapter downloads.
        output_path: Save fitted calibrator JSON to this path.
        examples_output: Save labeled examples as JSONL.
        seed: Random seed for reproducibility.

    Returns:
        TrainResult with calibrator, metrics, and counts.
    """
    store = resolver.store_for_domain(domain)
    domain_registry = ADAPTER_REGISTRY.get(domain, {})

    if adapter_names is None:
        adapter_names = list(domain_registry.keys())

    all_pairs = run_adapters(
        domain,
        adapter_names,
        store,
        limit_per_adapter=limit_per_adapter,
        cache_dir=cache_dir,
    )

    # Label through resolver
    logger.info("Labeling %d pairs via resolver...", len(all_pairs))
    labeled = label_examples(all_pairs, resolver)
    labeled_valid = [
        e for e in labeled if e.raw_score is not None and e.label is not None
    ]

    n_correct = sum(1 for e in labeled_valid if e.label == 1)
    logger.info(
        "Labeled: %d/%d (%.1f%% match rate)",
        n_correct,
        len(labeled_valid),
        100.0 * n_correct / max(1, len(labeled_valid)),
    )

    # Score distribution by class
    pos_scores = sorted([e.raw_score for e in labeled_valid if e.label == 1])  # type: ignore[misc]
    neg_scores = sorted([e.raw_score for e in labeled_valid if e.label == 0])  # type: ignore[misc]
    if pos_scores:
        logger.info(
            "Positive scores (n=%d): min=%.3f median=%.3f max=%.3f",
            len(pos_scores),
            pos_scores[0],
            pos_scores[len(pos_scores) // 2],
            pos_scores[-1],
        )
    if neg_scores:
        logger.info(
            "Negative scores (n=%d): min=%.3f median=%.3f max=%.3f",
            len(neg_scores),
            neg_scores[0],
            neg_scores[len(neg_scores) // 2],
            neg_scores[-1],
        )

    if examples_output:
        save_examples_jsonl(labeled, Path(examples_output))
        logger.info("Examples saved to %s", examples_output)

    if len(labeled_valid) < 4:
        raise ValueError(f"Need at least 4 labeled examples, got {len(labeled_valid)}")

    rng = random.Random(seed)
    train_examples, eval_examples = query_stratified_split(
        examples=labeled_valid, eval_split=eval_split, rng=rng
    )

    logger.info("Train: %d  Eval: %d", len(train_examples), len(eval_examples))

    train_scores = [e.raw_score for e in train_examples]  # type: ignore[misc]
    train_labels = [e.label for e in train_examples]  # type: ignore[misc]

    # Fit
    logger.info("Fitting '%s' calibrator...", method)
    if method == "platt":
        calibrator = fit_platt(train_scores, train_labels, domain=domain)
    elif method == "isotonic":
        calibrator = fit_isotonic(train_scores, train_labels, domain=domain)
    elif method == "stratified":
        train_query_lens = [len(e.query_text) for e in train_examples]
        calibrator = fit_stratified(
            train_scores, train_labels, train_query_lens, domain=domain
        )
    else:
        raise ValueError(f"Unknown method: {method!r}")

    # Evaluate
    metrics = None
    if eval_examples:
        eval_scores = [e.raw_score for e in eval_examples]  # type: ignore[misc]
        eval_labels = [e.label for e in eval_examples]  # type: ignore[misc]
        calibrated = [
            calibrator.predict(s, query_len=len(e.query_text))
            for s, e in zip(eval_scores, eval_examples, strict=False)
        ]
        metrics = evaluate_calibration(calibrated, eval_labels)
        logger.info(
            "Eval metrics: Brier=%.4f, LogLoss=%.4f, ECE=%.4f, AdaptiveECE=%.4f",
            metrics.brier_score,
            metrics.log_loss,
            metrics.ece,
            metrics.adaptive_ece,
        )

    # Save
    saved_path = None
    if output_path:
        saved_path = Path(output_path)
        save_calibrator(calibrator, saved_path)
        logger.info("Calibrator saved to %s", saved_path)

    return TrainResult(
        calibrator=calibrator,
        metrics=metrics,
        n_pairs=len(all_pairs),
        n_labeled=len(labeled_valid),
        n_train=len(train_examples),
        n_eval=len(eval_examples),
        output_path=saved_path,
    )


# ---------------------------------------------------------------------------
# ML scoring model training
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelTrainResult:
    """Result of a scoring model training run."""

    model: LogisticScoringModel
    metrics: CalibrationMetrics | None
    n_pairs: int
    n_labeled: int
    n_with_features: int
    n_train: int
    n_eval: int
    output_path: Path | None = None


def train_model(
    resolver: Resolver,
    domain: str,
    *,
    adapter_names: list[str] | None = None,
    regularization: float = 1.0,
    limit_per_adapter: int | None = None,
    eval_split: float = 0.2,
    cache_dir: str | Path | None = None,
    output_path: str | Path | None = None,
    examples_output: str | Path | None = None,
    seed: int = 42,
) -> ModelTrainResult:
    """Train a logistic scoring model end-to-end.

    Mirrors ``train_calibrator`` but uses ``include_features=True`` and
    ``fit_scoring_model()`` instead of a calibrator fitter.

    Args:
        resolver: A loaded Resolver instance.
        domain: Domain to train for ("geo" or "org").
        adapter_names: Which data adapters to run (default: all for domain).
        regularization: LogisticRegression C parameter.
        limit_per_adapter: Max examples per adapter.
        eval_split: Fraction held out for evaluation (0-1).
        cache_dir: Directory for caching adapter downloads.
        output_path: Save fitted model JSON to this path.
        examples_output: Save labeled examples as JSONL.
        seed: Random seed for reproducibility.

    Returns:
        ModelTrainResult with model, metrics, and counts.
    """
    store = resolver.store_for_domain(domain)
    domain_registry = ADAPTER_REGISTRY.get(domain, {})

    if adapter_names is None:
        adapter_names = list(domain_registry.keys())

    all_pairs = run_adapters(
        domain,
        adapter_names,
        store,
        limit_per_adapter=limit_per_adapter,
        cache_dir=cache_dir,
    )

    # Label through resolver, capturing feature vectors.
    # ~10% of examples are enriched with the correct country hint so the model
    # can learn from containment_pass features (which only fire when a country
    # context is present).
    logger.info(
        "Labeling %d pairs via resolver (include_features=True)...", len(all_pairs)
    )
    labeled = label_examples(
        all_pairs, resolver, include_features=True, context_enrichment_rate=0.1
    )
    labeled_valid = [
        e for e in labeled if e.raw_score is not None and e.label is not None
    ]
    labeled_with_features = [e for e in labeled_valid if e.features_dict is not None]

    logger.info(
        "Labeled: %d/%d with features: %d",
        len(labeled_valid),
        len(labeled),
        len(labeled_with_features),
    )

    if examples_output:
        save_examples_jsonl(labeled, Path(examples_output))
        logger.info("Examples saved to %s", examples_output)

    if len(labeled_with_features) < 4:
        raise ValueError(
            f"Need at least 4 labeled examples with features, "
            f"got {len(labeled_with_features)}"
        )

    rng = random.Random(seed)
    train_examples, eval_examples = query_stratified_split(
        examples=labeled_with_features, eval_split=eval_split, rng=rng
    )

    logger.info("Train: %d  Eval: %d", len(train_examples), len(eval_examples))

    # Fit
    logger.info("Fitting logistic scoring model...")
    model = fit_scoring_model(train_examples, domain, regularization=regularization)

    # Evaluate
    metrics = None
    confidence_threshold = None
    exact_code_min_score = None
    if eval_examples:
        predicted = [
            model.predict_dict(e.features_dict)  # type: ignore[arg-type]
            for e in eval_examples
        ]
        eval_labels = [e.label for e in eval_examples]  # type: ignore[misc]
        metrics = evaluate_calibration(predicted, eval_labels)
        logger.info(
            "Eval metrics: Brier=%.4f, LogLoss=%.4f, ECE=%.4f, AdaptiveECE=%.4f",
            metrics.brier_score,
            metrics.log_loss,
            metrics.ece,
            metrics.adaptive_ece,
        )

        # Find threshold that maximizes F1
        confidence_threshold = find_f1_threshold(predicted, eval_labels)
        logger.info(
            "Optimal confidence threshold: %.2f",
            confidence_threshold,
        )

        # Find exact_code_min_score: 5th percentile of model scores for correct exact-code examples
        exact_code_min_score = find_exact_code_min_score(predicted, eval_examples)
        if exact_code_min_score is not None:
            logger.info("Exact code min score (5th pct): %.3f", exact_code_min_score)

    if confidence_threshold is not None or exact_code_min_score is not None:
        model = LogisticScoringModel(
            **{
                **model.model_dump(),
                "confidence_threshold": confidence_threshold,
                "min_gap": 0.08,
                "exact_code_min_score": exact_code_min_score,
            }
        )

    # Save
    saved_path = None
    if output_path:
        saved_path = Path(output_path)
        save_scoring_model(model, saved_path)
        logger.info("Model saved to %s", saved_path)

    return ModelTrainResult(
        model=model,
        metrics=metrics,
        n_pairs=len(all_pairs),
        n_labeled=len(labeled_valid),
        n_with_features=len(labeled_with_features),
        n_train=len(train_examples),
        n_eval=len(eval_examples),
        output_path=saved_path,
    )
