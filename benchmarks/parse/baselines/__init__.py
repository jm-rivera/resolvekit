"""Baseline parse adapters for the parse evaluation harness.

Each adapter implements the :class:`~benchmarks.parse.runner.ParseAdapter`
protocol so it can be scored by
:func:`~benchmarks.parse.runner.run_parse_eval_adapter`.

Adapters are lazy-loading: heavy optional dependencies (spaCy) are not
imported at module import time.

Public exports:

    GazetteerAdapter   — exact-match lookup; no heavy deps.
    SpacyNerAdapter    — spaCy NER → resolvekit; requires ``resolvekit[baselines]``.
"""

from __future__ import annotations

from benchmarks.parse.baselines.gazetteer import GazetteerAdapter
from benchmarks.parse.baselines.spacy_ner import SpacyNerAdapter

__all__ = ["GazetteerAdapter", "SpacyNerAdapter"]
