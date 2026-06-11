"""Synthetic perturbation adapter using Gecko for realistic corruption."""

from __future__ import annotations

import logging
import random
import string
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from gecko import mutator

from resolvekit.calibration.adapters._latin_filter import is_latin_recoverable
from resolvekit.calibration.dataset import LabeledExample
from resolvekit.core.model import EntityRecord

if TYPE_CHECKING:
    from resolvekit.core.store import EntityStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Gecko character-level mutator factory
# ---------------------------------------------------------------------------


def _make_char_mutator(rng: np.random.Generator) -> mutator.Mutator:
    """Equal-weight group of single-character edit operations."""
    return mutator.with_group(
        [
            mutator.with_delete(rng=rng),
            mutator.with_insert(charset=string.ascii_lowercase, rng=rng),
            mutator.with_substitute(charset=string.ascii_lowercase, rng=rng),
            mutator.with_transpose(rng=rng),
        ],
        rng=rng,
    )


# ---------------------------------------------------------------------------
# Word-level perturbation functions (Gecko doesn't cover these)
# ---------------------------------------------------------------------------


def _drop_word(name: str, rng: random.Random) -> str:
    """Remove one word from a multi-word name (requires 3+ words)."""
    words = name.split()
    if len(words) < 3:
        return name
    idx = rng.randrange(len(words))
    return " ".join(words[:idx] + words[idx + 1 :])


def _reorder_words(name: str, rng: random.Random) -> str:
    """Shuffle word order (requires 2+ words)."""
    words = name.split()
    if len(words) < 2:
        return name
    shuffled = words[:]
    rng.shuffle(shuffled)
    return " ".join(shuffled)


def _truncate_word(name: str, rng: random.Random) -> str:
    """Clip one long word to 3-4 characters."""
    words = name.split()
    candidates = [(i, w) for i, w in enumerate(words) if len(w) >= 5]
    if not candidates:
        return name
    i, word = rng.choice(candidates)
    keep = rng.randint(3, min(4, len(word) - 1))
    words[i] = word[:keep]
    return " ".join(words)


# ---------------------------------------------------------------------------
# Non-typo perturbation functions
# ---------------------------------------------------------------------------


def _case_variation(name: str, rng: random.Random) -> str:
    """Apply a random case transformation."""
    choice = rng.randint(0, 2)
    if choice == 0:
        return name.upper()
    elif choice == 1:
        return name.lower()
    else:
        # Swap case: Title -> tITLE
        return name.swapcase()


def _prefix_truncation(name: str, rng: random.Random) -> str:
    """Keep only the first N characters of the name as a prefix query."""
    # For multi-word names, truncate to first word(s)
    words = name.split()
    if len(words) >= 2:
        # Keep first 1-2 words
        keep = rng.randint(1, min(2, len(words) - 1))
        return " ".join(words[:keep])
    # For single-word names, keep a prefix (at least 4 chars)
    if len(name) < 6:
        return name
    keep = rng.randint(4, max(4, len(name) - 2))
    return name[:keep]


def _spacing_error(name: str, rng: random.Random) -> str:
    """Introduce spacing errors in multi-word names."""
    words = name.split()
    if len(words) < 2:
        return name
    choice = rng.randint(0, 1)
    if choice == 0:
        # Remove a space: "New York" -> "NewYork"
        idx = rng.randrange(len(words) - 1)
        words[idx] = words[idx] + words[idx + 1]
        del words[idx + 1]
        return " ".join(words)
    else:
        # Double a space: "New York" -> "New  York"
        idx = rng.randrange(len(words) - 1)
        words[idx] = words[idx] + " "
        return " ".join(words)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_entity_frame(
    entities: dict[str, EntityRecord],
    entity_ids: list[str],
) -> pd.DataFrame:
    """Build a DataFrame of (entity_id, name) from ALL indexed names."""
    rows: list[dict[str, str]] = []
    for eid in entity_ids:
        if eid not in entities:
            continue
        entity = entities[eid]
        # Collect all indexed names: canonical + all name records
        seen_norms: set[str] = set()
        all_names: list[str] = []

        cname = entity.canonical_name.strip()
        if len(cname) >= 2:
            all_names.append(cname)
            seen_norms.add(cname.lower())

        for nr in entity.names:
            val = nr.value.strip()
            val_lower = val.lower()
            if len(val) >= 2 and val_lower not in seen_norms:
                all_names.append(val)
                seen_norms.add(val_lower)

        for name in all_names:
            rows.append({"entity_id": eid, "name": name})

    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["entity_id", "name"])
    if df.empty:
        return df
    # Filter out names that look like entity IDs (contain '/')
    df = df[~df["name"].str.contains("/", na=False)]
    # Filter out code-like names (e.g. Wikidata QIDs like "Q12345")
    df = df[~df["name"].str.match(r"^Q\d+$", na=False)]
    # Filter out non-Latin names the retrieval pipeline can't handle
    df = df[df["name"].apply(is_latin_recoverable)]
    return df.reset_index(drop=True)


def _build_known_norms(entities: dict[str, EntityRecord]) -> dict[str, set[str]]:
    """Per-entity set of known normalised names (to skip accidental exact matches)."""
    known: dict[str, set[str]] = {}
    for eid, entity in entities.items():
        norms = {entity.canonical_name_norm}
        norms.update(nr.value_norm for nr in entity.names)
        known[eid] = norms
    return known


# ---------------------------------------------------------------------------
# Pass name registry
# ---------------------------------------------------------------------------

PASS_NAMES = [
    "char_edit_short",
    "char_edit_long_mild",
    "char_edit_long_moderate",
    "word_drop",
    "word_reorder",
    "word_truncation",
    "case_variation",
    "prefix_truncation",
    "spacing_error",
]


# ---------------------------------------------------------------------------
# Shared perturbation core
# ---------------------------------------------------------------------------


def _synthetic_generate_pairs(
    *,
    store: EntityStore,
    seed: int,
    limit: int | None,
    name: str,
    domain: str,
) -> list[LabeledExample]:
    """Shared perturbation core for synthetic geo/org pair generation.

    Rebuilds RNGs from ``seed`` on every call — no cross-call state.
    """
    rng_np = np.random.default_rng(seed)
    rng_py = random.Random(seed)

    all_ids = sorted(store.all_entity_ids())

    # When limit is set, sample a bounded subset of entities instead
    # of hydrating the entire store.  Each entity yields ~3-6 pairs
    # across the perturbation passes; we over-sample by 2x to
    # account for deduplication and filtering.
    if limit is not None and len(all_ids) > limit * 2:
        rng_sample = random.Random(seed)
        entity_ids = sorted(rng_sample.sample(all_ids, min(len(all_ids), limit * 2)))
    else:
        entity_ids = all_ids

    entities = store.bulk_get_entities(entity_ids)

    df = _build_entity_frame(entities, entity_ids)
    if df.empty:
        return []

    names = df["name"]
    eids = df["entity_id"]
    filtered_entities = {eid: entities[eid] for eid in eids.unique() if eid in entities}
    known_norms = _build_known_norms(filtered_entities)

    # Length-adaptive character mutations:
    # Short names (<=8 chars) are fragile — 1 edit only.
    # Longer names can absorb more corruption — mix of 1 and 2 edits.
    # Names < 5 chars skip character mutations entirely (too fragile).
    char_mut = _make_char_mutator(rng_np)
    # Each entry is (pass_name, pd.Series of perturbed values).
    named_passes: list[tuple[str, pd.Series]] = []
    name_lens = names.str.len()

    # Character mutations only for names >= 5 chars
    char_eligible = name_lens >= 5

    # Short names (5-8 chars): 1 edit pass only
    short_mask = char_eligible & (name_lens <= 8)
    if short_mask.any():
        named_passes.append((PASS_NAMES[0], char_mut([names[short_mask]], 1.0)[0]))

    # Longer names: 60% get 1 edit, 40% get 2 edits
    long_mask = char_eligible & (name_lens > 8)
    if long_mask.any():
        long_names = names[long_mask]
        n_long = len(long_names)
        long_idx = list(range(n_long))
        rng_py.shuffle(long_idx)
        split = int(n_long * 0.6)
        mild_long = long_names.iloc[sorted(long_idx[:split])]
        moderate_long = long_names.iloc[sorted(long_idx[split:])]
        named_passes.append((PASS_NAMES[1], char_mut([mild_long], 1.0)[0]))
        mod_first = char_mut([moderate_long], 1.0)[0]
        named_passes.append((PASS_NAMES[2], char_mut([mod_first], 1.0)[0]))

    # Word-level passes
    split_names = names.str.split()
    word_counts = split_names.str.len()

    mask_3plus = word_counts >= 3
    if mask_3plus.any():
        named_passes.append(
            (
                PASS_NAMES[3],
                names[mask_3plus].apply(lambda n: _drop_word(n, rng_py)),
            )
        )

    mask_2plus = word_counts >= 2
    if mask_2plus.any():
        named_passes.append(
            (
                PASS_NAMES[4],
                names[mask_2plus].apply(lambda n: _reorder_words(n, rng_py)),
            )
        )

    long_word_mask = split_names.apply(lambda ws: any(len(w) >= 5 for w in ws))
    if long_word_mask.any():
        named_passes.append(
            (
                PASS_NAMES[5],
                names[long_word_mask].apply(lambda n: _truncate_word(n, rng_py)),
            )
        )

    # Case variation pass (all names)
    named_passes.append(
        (PASS_NAMES[6], names.apply(lambda n: _case_variation(n, rng_py)))
    )

    # Prefix truncation pass (names >= 6 chars or multi-word)
    prefix_mask = (name_lens >= 6) | (word_counts >= 2)
    if prefix_mask.any():
        named_passes.append(
            (
                PASS_NAMES[7],
                names[prefix_mask].apply(lambda n: _prefix_truncation(n, rng_py)),
            )
        )

    # Spacing error pass (multi-word names)
    if mask_2plus.any():
        named_passes.append(
            (
                PASS_NAMES[8],
                names[mask_2plus].apply(lambda n: _spacing_error(n, rng_py)),
            )
        )

    # Flatten all (pass_name, row_index, perturbed_value) tuples then
    # shuffle so every mutation type is represented proportionally even
    # when a limit truncates the collection early.
    all_items: list[tuple[str, int, str]] = []
    for pass_name, series in named_passes:
        for idx in series.index:
            all_items.append((pass_name, idx, series.loc[idx]))

    rng_py.shuffle(all_items)

    # Collect examples, deduplicating against known names and prior passes
    examples: list[LabeledExample] = []
    seen: set[tuple[str, str]] = set()

    for pass_name, idx, perturbed in all_items:
        original = names.loc[idx]
        eid = eids.loc[idx]

        if perturbed == original or len(perturbed.strip()) < 2:
            continue

        key = (perturbed.lower(), eid)
        if key in seen:
            continue
        if perturbed.lower() in known_norms.get(eid, set()):
            continue

        seen.add(key)
        examples.append(
            LabeledExample(
                query_text=perturbed,
                expected_entity_id=eid,
                source_adapter=name,
                domain=domain,
                mutation_type=pass_name,
            )
        )

        if limit is not None and len(examples) >= limit:
            return examples

    logger.info(
        "Synthetic adapter (%s): generated %d examples from %d name variants (%d entities)",
        domain,
        len(examples),
        len(df),
        df["entity_id"].nunique(),
    )
    return examples


# ---------------------------------------------------------------------------
# Public free functions
# ---------------------------------------------------------------------------


def synthetic_generate_geo_pairs(
    *,
    store: EntityStore,
    seed: int = 42,
    cache_dir: str | Path | None = None,
    limit: int | None = None,
) -> list[LabeledExample]:
    """Generate synthetic perturbation pairs for geo entities.

    Sources names from ALL indexed name variants (canonical + aliases),
    applies diverse perturbation strategies (character typos, word-level,
    case, spacing, truncation), and filters non-Latin names.

    RNGs are rebuilt from ``seed`` on every call — no cross-call state.

    Args:
        store: Entity store to sample names from.
        seed: RNG seed for reproducibility.
        cache_dir: Unused (accepted for uniform ``run_adapters`` calling
            convention).
        limit: Maximum number of examples to return.
    """
    return _synthetic_generate_pairs(
        store=store,
        seed=seed,
        limit=limit,
        name="synthetic",
        domain="geo",
    )


def synthetic_generate_org_pairs(
    *,
    store: EntityStore,
    seed: int = 42,
    cache_dir: str | Path | None = None,
    limit: int | None = None,
) -> list[LabeledExample]:
    """Generate synthetic perturbation pairs for org entities.

    Sources names from ALL indexed name variants (canonical + aliases),
    applies diverse perturbation strategies (character typos, word-level,
    case, spacing, truncation), and filters non-Latin names.

    RNGs are rebuilt from ``seed`` on every call — no cross-call state.

    Args:
        store: Entity store to sample names from.
        seed: RNG seed for reproducibility.
        cache_dir: Unused (accepted for uniform ``run_adapters`` calling
            convention).
        limit: Maximum number of examples to return.
    """
    return _synthetic_generate_pairs(
        store=store,
        seed=seed,
        limit=limit,
        name="synthetic",
        domain="org",
    )
