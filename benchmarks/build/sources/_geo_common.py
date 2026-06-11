"""Shared helpers for admin/city dataset builders.

Enumerates entities of a given type from the shared sqlite store and yields
canonical, alias, and synthetic-typo variant rows.
"""

from __future__ import annotations

import logging
import random
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchmarks.core.kernel import Query

if TYPE_CHECKING:
    from resolvekit.core.model import EntityRecord
    from resolvekit.core.store import EntityStore

logger = logging.getLogger(__name__)

# Single source of truth; imported by build/__init__.py.
SHARED_SQLITE_PATH = Path("data/build/shared/geo/entities.sqlite")


def _download(*, url: str, cache_dir: Path | None) -> Path:
    """Fetch ``url`` via pooch (no hash check); return the local Path."""
    import pooch

    kwargs: dict[str, Any] = {"url": url, "known_hash": None}
    if cache_dir is not None:
        kwargs["path"] = cache_dir
    path = pooch.retrieve(**kwargs)
    if isinstance(path, list):
        path = path[0]
    return Path(path)


BENCHMARK_TYPE_BY_STORE: dict[str, str] = {
    "geo.country": "country",
    "geo.admin1": "admin1",
    "geo.admin2": "admin2",
    "geo.admin3": "admin3",
    "geo.admin4": "admin4",
    "geo.admin5": "admin5",
    "geo.city": "city",
}


def store_db_path(store: EntityStore) -> Path | None:
    """Return the backing sqlite path of a sqlite-backed store, else ``None``.

    Lets the admin/city builders sample entity ids directly from the *shipped*
    resolver store (the composed sqlite ``Resolver.auto()`` loads) rather than
    the gitignored DC staging cache — so sampling and scoring use the same
    entity set and no row can reference an entity that does not ship.
    """
    raw = getattr(store, "_db_path", None)
    return Path(raw) if raw is not None else None


def sample_entity_ids(
    *,
    entity_types: tuple[str, ...],
    per_type_limits: dict[str, int],
    seed: int,
    db_path: Path | None = None,
) -> list[tuple[str, str]]:
    """Return ``[(entity_id, store_entity_type)]`` sampled per type.

    When the shared sqlite is missing, returns an empty list.
    """
    if db_path is None:
        db_path = SHARED_SQLITE_PATH
    if not db_path.exists():
        logger.warning("entity sqlite missing at %s", db_path)
        return []

    rng = random.Random(seed)
    selected: list[tuple[str, str]] = []
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        for etype in entity_types:
            cap = per_type_limits.get(etype, 0)
            if cap <= 0:
                continue
            rows = conn.execute(
                "SELECT entity_id FROM entities WHERE entity_type = ?",
                (etype,),
            ).fetchall()
            candidates = [row["entity_id"] for row in rows]
            rng.shuffle(candidates)
            selected.extend((eid, etype) for eid in candidates[:cap])
    finally:
        conn.close()
    return selected


def build_entity_rows(
    *,
    store: EntityStore,
    entity_samples: list[tuple[str, str]],
    seed: int,
    typos_per_entity: int = 1,
) -> list[Query]:
    rng = random.Random(seed)
    rows: list[Query] = []
    for entity_id, store_type in entity_samples:
        entity = store.get_entity(entity_id)
        if entity is None:
            continue
        bench_type = BENCHMARK_TYPE_BY_STORE.get(store_type, "")
        if not bench_type:
            continue

        canonical = entity.canonical_name
        if _is_junk_name(canonical):
            continue

        rows.append(
            _make_row(
                text=canonical,
                entity_id=entity_id,
                entity_type=bench_type,
                category="canonical",
                difficulty="easy",
                capabilities=(),
                source="shared_entities_sqlite",
                notes="canonical",
            )
        )

        for alias in _english_aliases(entity=entity, limit=2):
            if _is_junk_name(alias):
                continue
            rows.append(
                _make_row(
                    text=alias,
                    entity_id=entity_id,
                    entity_type=bench_type,
                    category="alias",
                    difficulty="medium",
                    capabilities=("alias",),
                    source="shared_entities_sqlite",
                    notes="alias",
                )
            )

        base_for_typo = canonical
        if len(base_for_typo) < 5:
            continue
        for _ in range(typos_per_entity):
            perturbed = _char_typo(base_for_typo, rng=rng)
            if perturbed == base_for_typo or _is_junk_name(perturbed):
                continue
            rows.append(
                _make_row(
                    text=perturbed,
                    entity_id=entity_id,
                    entity_type=bench_type,
                    category="typo",
                    difficulty="medium",
                    capabilities=("typo",),
                    source="synthetic",
                    notes="char_edit",
                )
            )
    return rows


def _english_aliases(*, entity: EntityRecord, limit: int) -> list[str]:
    seen: set[str] = {entity.canonical_name.lower()}
    aliases: list[str] = []
    for nr in entity.names:
        if nr.kind == "canonical":
            continue
        if (nr.lang or "").lower() not in {"", "en"}:
            continue
        lowered = nr.value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        aliases.append(nr.value)
        if len(aliases) >= limit:
            break
    return aliases


def _is_junk_name(name: str) -> bool:
    cleaned = name.strip()
    if len(cleaned) < 2:
        return True
    if cleaned.startswith("wikidataId/"):
        return True
    return cleaned.lower() in {"n/a", "unknown"}


_TYPO_OPS: tuple[str, ...] = ("delete", "transpose", "substitute")
_ALPHABET = "abcdefghijklmnopqrstuvwxyz"


def _char_typo(name: str, *, rng: random.Random) -> str:
    if len(name) < 5:
        return name
    positions = [i for i, ch in enumerate(name) if ch.isalpha()]
    if not positions:
        return name
    op = rng.choice(_TYPO_OPS)
    idx = rng.choice(positions)
    if op == "delete":
        return name[:idx] + name[idx + 1 :]
    if op == "substitute":
        return name[:idx] + rng.choice(_ALPHABET) + name[idx + 1 :]
    swap = min(idx, len(name) - 2)
    return name[:swap] + name[swap + 1] + name[swap] + name[swap + 2 :]


def _make_row(
    *,
    text: str,
    entity_id: str,
    entity_type: str,
    category: str,
    difficulty: str,
    capabilities: tuple[str, ...],
    source: str,
    notes: str,
) -> Query:
    return Query(
        query_id="",
        text=text,
        expected_ids=(entity_id,),
        language="en",
        entity_type=entity_type,
        category=category,
        difficulty=difficulty,
        capabilities=capabilities,
        source=source,
        notes=notes,
    )
