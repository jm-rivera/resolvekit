"""Declarative dataset registry.

Each entry in DATASET_SPECS describes how to build one benchmark dataset.
``build_fn=None`` marks datasets that cannot be built locally (e.g. require
an upstream data pack not yet assembled). Callers should inspect
``requires_pack`` for a human-readable explanation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from benchmarks.build.provenance import BuildRecord
    from benchmarks.core.kernel import Query


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    build_fn: Callable[..., tuple[list[Query], BuildRecord]] | None
    requires_pack: str | None = None
    notes: str | None = None
    # When True, this dataset is a curated quality-evaluation set: a CI gate
    # enforces a resolvekit regression threshold on it, and resolvekit_typed
    # receives entity_type + language hints. All tools still run (scoped to the
    # entity types they support), so the eval tables show a per-type comparison.
    eval: bool = False
    # Per-source row limits that govern how this dataset is built, keyed by
    # source name (e.g. "cldr", "geonames"). None means no per-source limits
    # are recorded at the spec level (builder-internal defaults apply).
    source_limits: dict[str, int] | None = None


# Populated by benchmarks/build/__init__.py after its builder functions are
# defined; split into a separate module so the dataclass can be imported
# without pulling in the full build pipeline.
DATASET_SPECS: dict[str, DatasetSpec] = {}

# Source of truth for the set of known dataset names.  build/__init__.py
# asserts set(DATASET_SPECS) == set(DATASET_NAMES) after populating DATASET_SPECS.
DATASET_NAMES: tuple[str, ...] = (
    "geo_countries_en",
    "geo_countries_multilingual",
    "geo_admin",
    "geo_cities",
    "ambiguous",
    "no_match",
    "eval_geo",
    "eval_org",
    "eval_parse",
)
