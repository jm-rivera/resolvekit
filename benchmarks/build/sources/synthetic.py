"""Synthetic builder — perturbation-based queries via Gecko."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from benchmarks.core.kernel import Query
from resolvekit.core.model import EntityRecord

if TYPE_CHECKING:
    from resolvekit.core.store import EntityStore

logger = logging.getLogger(__name__)

_HEAVY_MUTATIONS: frozenset[str] = frozenset(
    {"char_edit_long_moderate", "word_drop", "word_reorder", "word_truncation"}
)
_CASE_MUTATIONS: frozenset[str] = frozenset({"case_variation"})
_SPACING_MUTATIONS: frozenset[str] = frozenset({"spacing_error"})
_TRUNCATION_MUTATIONS: frozenset[str] = frozenset({"prefix_truncation"})


def build(
    *,
    store: EntityStore,
    limit: int | None = None,
    seed: int = 42,
    id_prefix: str = "country/",
) -> list[Query]:
    try:
        from resolvekit.calibration.adapters.synthetic import (
            synthetic_generate_geo_pairs,
        )
    except Exception as exc:
        logger.warning("Synthetic adapter unavailable: %s", exc)
        return []

    over_limit = None if limit is None else limit * 3
    prefixed = _PrefixFilteredStore(store, id_prefix=id_prefix)
    try:
        examples = synthetic_generate_geo_pairs(
            store=prefixed, seed=seed, limit=over_limit
        )
    except Exception as exc:
        logger.warning("Synthetic pair generation failed: %s", exc)
        return []

    rows: list[Query] = []
    for ex in examples:
        if not ex.expected_entity_id.startswith(id_prefix):
            continue
        mutation = ex.mutation_type or ""
        category, difficulty, capabilities = _classify(mutation)
        rows.append(
            Query(
                query_id="",
                text=ex.query_text,
                expected_ids=(ex.expected_entity_id,),
                language="en",
                entity_type="country",
                category=category,
                difficulty=difficulty,
                capabilities=capabilities,
                source="synthetic",
                notes=mutation or None,
            )
        )

    # Drop rows whose lowercased stem maps to more than one distinct expected_id
    # (e.g. "United" → dozens of countries) — unanswerable queries that inflate
    # error counts and obscure genuine capability signal.
    stem_to_ids: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in rows:
        stem_to_ids[(r.text.lower(), r.entity_type)].update(r.expected_ids)
    before = len(rows)
    rows = [r for r in rows if len(stem_to_ids[(r.text.lower(), r.entity_type)]) == 1]
    logger.debug(
        "Stem filter dropped %d unanswerable rows (%d remain)",
        before - len(rows),
        len(rows),
    )

    if limit is not None:
        rows = rows[:limit]
    return rows


def _classify(mutation: str) -> tuple[str, str, tuple[str, ...]]:
    if mutation in _CASE_MUTATIONS:
        return "case_noise", "medium", ("case_noise",)
    if mutation in _SPACING_MUTATIONS:
        return "canonical_unicode", "medium", ("unicode_normalization",)
    if mutation in _TRUNCATION_MUTATIONS:
        return "prefix_truncation", "medium", ("prefix_truncation",)
    if mutation in _HEAVY_MUTATIONS:
        return "heavy_noise", "hard", ("typo", "case_noise")
    return "typo", "medium", ("typo",)


class _PrefixFilteredStore:
    """Proxy around an EntityStore that restricts ``all_entity_ids`` by prefix.

    The synthetic adapter samples entities via ``store.all_entity_ids()`` and
    ``store.bulk_get_entities(...)``. This wrapper narrows that view so synthetic
    generation stays focused on the target entity family (e.g. ``country/``)
    when the backing store contains the full multi-pack universe.
    """

    def __init__(self, inner: EntityStore, *, id_prefix: str) -> None:
        self._inner = inner
        self._prefix = id_prefix

    def all_entity_ids(self) -> set[str]:
        return {
            eid for eid in self._inner.all_entity_ids() if eid.startswith(self._prefix)
        }

    def bulk_get_entities(self, entity_ids: list[str]) -> dict[str, EntityRecord]:
        """Return prefix-filtered entities with non-English names stripped.

        Each EntityRecord is copied keeping only names whose ``lang`` is
        ``None`` or ``'en'``. ``canonical_name`` is not filtered — it is
        always the English primary name.
        """
        raw = self._inner.bulk_get_entities(entity_ids)
        result: dict[str, EntityRecord] = {}
        for eid, rec in raw.items():
            en_names = [n for n in rec.names if n.lang in (None, "en")]
            result[eid] = rec.model_copy(update={"names": en_names})
        return result

    def __getattr__(self, item: str) -> Any:
        return getattr(self._inner, item)
