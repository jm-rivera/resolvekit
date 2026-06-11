"""Calibration dataset models and labeling."""

from __future__ import annotations

import logging
import random
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from resolvekit.core.api.resolver import Resolver
    from resolvekit.core.engine.runner import PipelineRunner
    from resolvekit.core.store.interface import EntityStore


class LabeledExample(BaseModel):
    """One labeled example for calibration training."""

    model_config = ConfigDict(frozen=True)

    query_text: str
    expected_entity_id: str  # ground-truth DCID
    source_adapter: str  # which adapter produced this
    domain: str  # "geo" or "org"
    mutation_type: str | None = None  # perturbation type (synthetic adapter only)
    top_entity_id: str | None = None  # what resolver returned
    raw_score: float | None = (
        None  # heuristic score (= confidence when calibrate is identity)
    )
    label: int | None = None  # 1 if correct, 0 if wrong
    features_dict: dict[str, float] | None = None  # vectorized features for ML training


class CalibrationDataset(BaseModel):
    """Collection of labeled examples."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    domain: str
    examples: list[LabeledExample]

    @property
    def labeled_examples(self) -> list[LabeledExample]:
        """Only examples with scores and labels populated."""
        return [
            e for e in self.examples if e.raw_score is not None and e.label is not None
        ]

    @property
    def scores(self) -> list[float]:
        return [e.raw_score for e in self.labeled_examples]  # type: ignore[misc]

    @property
    def labels(self) -> list[int]:
        return [e.label for e in self.labeled_examples]  # type: ignore[misc]


def save_examples_jsonl(examples: list[LabeledExample], path: str | Path) -> None:
    """Save examples as JSONL."""
    with Path(path).open("w", encoding="utf-8") as f:
        for ex in examples:
            f.write(ex.model_dump_json() + "\n")


def load_examples_jsonl(path: str | Path) -> list[LabeledExample]:
    """Load examples from JSONL."""
    examples = []
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                examples.append(LabeledExample.model_validate_json(line))
    return examples


def _get_pack_runner(resolver: Resolver, domain: str) -> PipelineRunner | None:
    """Get the domain-specific PipelineRunner from a multi-pack resolver.

    Returns None for single-pack resolvers (where routing isn't an issue).
    """
    from resolvekit.core.engine.multi_runner import MultiPackRunner

    runner = resolver._runner
    if isinstance(runner, MultiPackRunner) and domain in runner._runners:
        return runner._runners[domain]
    return None


def _get_iso2_for_entity(entity_id: str, store: EntityStore) -> str | None:
    """Return a country ISO 3166-1 alpha-2 code usable as a containment hint.

    Only returns a code when this entity can be VERIFIED as sub-national via
    the store's ``contained_in`` relations — i.e. a BFS over those relations
    reaches an entity that carries an exactly-2-character ``iso2`` code.

    Country-level entities (those whose own ``iso2`` code is exactly 2
    characters) return ``None`` — passing ``country=self`` would cause the
    containment constraint to filter the entity out (a country is not
    "contained in" itself).

    The approach does NOT use ISO 3166-2 subdivision prefixes (e.g. "US-CA")
    to infer the country, because many stores record those codes without a
    corresponding ``contained_in`` relation edge to the country entity.
    Without that edge the containment BFS can't verify containment and would
    filter the candidate out during resolution.

    Returns the lowercase 2-letter ISO 3166-1 code of the containing country,
    or None if the entity is a country itself, has no ``contained_in`` path to
    a country, or cannot be found.
    """
    entity = store.get_entity(entity_id)
    if entity is None:
        return None

    # If the entity itself has an exactly-2-char iso2 code it IS a country.
    for code in entity.codes:
        if code.system == "iso2" and len(code.value.strip()) == 2:
            return None

    # BFS over "contained_in" relations looking for a country parent.
    # Only return a code when the BFS actually finds a country, so we know
    # the containment constraint will pass for this entity.
    visited: set[str] = {entity_id}
    queue: list[str] = [entity_id]
    depth = 0
    max_depth = 5

    while queue and depth < max_depth:
        next_queue: list[str] = []
        for current in queue:
            parents = store.get_relations(current, "contained_in")
            for parent_id in parents:
                if parent_id in visited:
                    continue
                visited.add(parent_id)
                parent = store.get_entity(parent_id)
                if parent is None:
                    continue
                for code in parent.codes:
                    if code.system == "iso2" and len(code.value.strip()) == 2:
                        return code.value.strip().lower()
                next_queue.append(parent_id)
        queue = next_queue
        depth += 1

    return None


def label_examples(
    examples: list[LabeledExample],
    resolver: Resolver,
    *,
    include_features: bool = False,
    context_enrichment_rate: float = 0.0,
) -> list[LabeledExample]:
    """Run unlabeled examples through ResolveKit and auto-label.

    For each example:
    1. Run through the resolver pipeline via resolve_detailed() to get candidates
    2. Extract raw (pre-calibration) score from the top candidate
    3. label = 1 if top_entity_id == expected_entity_id, else 0

    Uses the runner directly to access scores.raw_score (pre-calibration).
    If the resolver has a calibrator loaded, result.confidence would be
    the calibrated score — using raw_score avoids training on
    already-calibrated data.

    Each example is resolved against its declared domain's pack runner
    directly, bypassing the router. This prevents AUTO-mode routing
    from sending examples to the wrong pack and contaminating
    domain-specific calibration data.

    Args:
        examples: Unlabeled examples to label.
        resolver: Loaded Resolver instance.
        include_features: If True, capture raw feature dicts from candidates.
        context_enrichment_rate: Fraction of examples (0.0-1.0) that will
            receive geographic context (country hint) derived from the
            expected entity's country.  Defaults to 0.0 (no enrichment).
            When > 0 a seeded RNG (seed=42) deterministically selects which
            examples are enriched.  Enrichment is best-effort: examples
            whose country cannot be determined are resolved without context.
    """
    logger = logging.getLogger(__name__)
    labeled: list[LabeledExample] = []
    n_labeled = 0
    n_no_candidates = 0
    n_exceptions = 0
    n_enriched = 0

    # Cache pack runners per domain to avoid repeated lookups
    pack_runners: dict[str, PipelineRunner | None] = {}

    # Provide as_of=today so temporal constraints fire during labeling.
    # Other context fields (entity_types, parent_ids, country) are left
    # empty because they depend on caller-provided hints that aren't
    # available during training.
    from resolvekit.core.model import ResolutionContext

    default_context = ResolutionContext(as_of=date.today())

    # Pre-build the enrichment selection set when needed.
    # Use a seeded RNG for reproducibility across runs.
    enrichment_rng = random.Random(42)
    should_enrich: list[bool] = []
    if context_enrichment_rate > 0.0:
        should_enrich = [
            enrichment_rng.random() < context_enrichment_rate for _ in examples
        ]

    for idx, ex in enumerate(examples):
        try:
            # Optionally enrich the context with a country hint derived from
            # the expected entity.  This fires containment constraints and
            # lets the model learn from containment_pass features.
            context = default_context
            if should_enrich and should_enrich[idx]:
                if ex.domain not in pack_runners:
                    pack_runners[ex.domain] = _get_pack_runner(resolver, ex.domain)
                target_runner_for_store = pack_runners[ex.domain]
                store = (
                    getattr(target_runner_for_store, "_store", None)
                    if target_runner_for_store is not None
                    else None
                )
                if store is not None:
                    iso2 = _get_iso2_for_entity(ex.expected_entity_id, store)
                    if iso2:
                        context = ResolutionContext(as_of=date.today(), country=iso2)
                        n_enriched += 1

            query, context = resolver._prepare_query(
                ex.query_text,
                context,
                None,
            )

            # Resolve against the example's declared domain pack directly,
            # bypassing the router.  For single-pack resolvers (where
            # _get_pack_runner returns None) we fall back to the top-level
            # runner which doesn't have a routing concern.
            if ex.domain not in pack_runners:
                pack_runners[ex.domain] = _get_pack_runner(resolver, ex.domain)

            target_runner = pack_runners[ex.domain]
            if target_runner is not None:
                pipeline_result = target_runner.resolve_detailed(
                    query,
                    context,
                )
            else:
                pipeline_result = resolver._runner.resolve_detailed(
                    query,
                    context,
                )

            result = pipeline_result.result
            candidates = pipeline_result.candidates

            # Extract top entity from candidates (sorted by score), not from
            # result.entity_id which is only set for RESOLVED status.
            # AMBIGUOUS / below-threshold NO_MATCH results may still have the
            # correct entity ranked first — labeling those as 0 would bias
            # the calibrator downward around the decision boundary.
            top_id: str | None = None
            if candidates:
                top_id = candidates[0].entity_id
            elif result.entity_id:
                top_id = result.entity_id

            raw_score: float | None = None
            if candidates:
                raw_score = candidates[0].scores.raw_score
            elif result.confidence is not None:
                raw_score = result.confidence

            if raw_score is None:
                n_no_candidates += 1
            else:
                n_labeled += 1

            label = 1 if top_id == ex.expected_entity_id else 0

            # Optionally capture the raw feature dict from the top candidate
            features_dict = None
            if include_features and candidates:
                feat = getattr(candidates[0], "features", None)
                if feat is not None and hasattr(feat, "to_dict"):
                    features_dict = feat.to_dict()

            labeled.append(
                ex.model_copy(
                    update={
                        "top_entity_id": top_id,
                        "raw_score": raw_score,
                        "label": label,
                        "features_dict": features_dict,
                    }
                )
            )
        except Exception:
            n_exceptions += 1
            logger.debug(
                "Resolution failed for %r",
                ex.query_text,
                exc_info=True,
            )
            labeled.append(ex)  # keep unlabeled

    logger.info(
        "Label stats: %d labeled, %d no-candidates, %d exceptions, "
        "%d enriched-with-country (of %d total)",
        n_labeled,
        n_no_candidates,
        n_exceptions,
        n_enriched,
        len(examples),
    )
    return labeled
