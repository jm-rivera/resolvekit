"""Benchmark dataset build pipeline."""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from benchmarks.build.provenance import (
    BuildRecord,
    dataset_sha256,
    write_provenance,
)
from benchmarks.build.sources import (
    ambiguous,
    cldr,
    geo_admin,
    geo_cities,
    geonames,
    no_match,
    synthetic,
    wikidata,
)
from benchmarks.build.spec import DATASET_NAMES, DATASET_SPECS, DatasetSpec
from benchmarks.core.kernel import Query

if TYPE_CHECKING:
    from resolvekit.core.store import EntityStore

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_DIR = Path(__file__).parent.parent.parent / ".calibration_cache"

# CLDR: covers all ISO 3166-1 country codes once in a single language pass.
_MONO_CLDR_LIMIT = 260
# Geonames: broad alias coverage; large enough to surface uncommon name variants.
_MONO_GEONAMES_LIMIT = 4000
# Wikidata: supplemental names beyond Geonames. After the country/-namespace filter,
# the useful cache yields ~1300 rows; the 2000 cap gives headroom for future refetches.
_MONO_WIKIDATA_LIMIT = 2000
# Synthetic: typo/variant generation to stress normalisation; dominates row count.
_MONO_SYNTHETIC_LIMIT = 3000

# Multilingual CLDR: 240 per language x 3 languages covers the full ISO set per lang.
_MULTI_CLDR_LIMIT = 240
# Multilingual GeoNames: country alternate names from the alternateNames dump, per lang.
_MULTI_GEONAMES_PER_LANG = 1000
# Multilingual Wikidata: 1000 per language to balance breadth and build time.
_MULTI_WIKIDATA_PER_LANG = 1000


def build_dataset(
    *,
    name: str,
    data_dir: Path = DATA_DIR,
    store: EntityStore | None = None,
    seed: int = 42,
) -> tuple[list[Query], BuildRecord]:
    if name not in DATASET_NAMES:
        raise ValueError(f"Unknown dataset {name!r}")

    spec = DATASET_SPECS[name]
    if spec.build_fn is None:
        if spec.notes:
            raise RuntimeError(
                f"Dataset {name!r} is committed and not rebuilt from upstream sources: "
                f"{spec.notes}"
            )
        raise RuntimeError(
            f"Dataset {name!r} requires the {spec.requires_pack!r} pack which is not "
            "built; see the benchmarks README for instructions."
        )

    data_dir.mkdir(parents=True, exist_ok=True)
    resolved_store = store if store is not None else _default_store()
    return spec.build_fn(name=name, data_dir=data_dir, store=resolved_store, seed=seed)


def build_all(*, data_dir: Path = DATA_DIR, seed: int = 42) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    store = _default_store()
    records: dict[str, BuildRecord] = {}
    for name in DATASET_NAMES:
        # Curated eval sets (build_fn is None) are maintained as committed CSVs
        # and regenerated via convert_eval_csv, not from upstream sources — they
        # have no build provenance, so skip them rather than record a failure.
        if DATASET_SPECS[name].build_fn is None:
            continue
        logger.info("building %s", name)
        try:
            _rows, record = build_dataset(
                name=name, data_dir=data_dir, store=store, seed=seed
            )
            records[name] = record
        except Exception as exc:
            logger.exception("build_dataset(%s) failed: %s", name, exc)
            records[name] = BuildRecord(
                dataset=name,
                row_count=0,
                sources=(),
                seed=seed,
                notes=f"build failed: {exc}",
            )
    write_provenance(data_dir=data_dir, datasets=records)


def _default_store() -> EntityStore:
    # Sample benchmark entities from the *shipped* resolver, not the gitignored
    # DC staging cache. Scoring runs against Resolver.auto(); sampling from the
    # same store keeps the two consistent, so a sampled entity always resolves —
    # entities that don't survive packaging can never become dead golds.
    from resolvekit import Resolver

    resolver = Resolver.auto()
    stores: dict[str, EntityStore] = getattr(resolver._runner, "_stores", {})
    if not stores:
        raise RuntimeError("Resolver has no loaded pack stores")
    for pack_id, store in stores.items():
        if pack_id.startswith("geo"):
            return store
    return next(iter(stores.values()))


_SourceCall = Callable[["EntityStore", int], list[Query]]


def _mono_cldr(store: EntityStore, seed: int) -> list[Query]:
    return cldr.build(
        store=store,
        limit=_MONO_CLDR_LIMIT,
        seed=seed,
        languages=["en"],
        cache_dir=CACHE_DIR,
    )


def _mono_geonames(store: EntityStore, seed: int) -> list[Query]:
    return geonames.build(
        store=store,
        limit=_MONO_GEONAMES_LIMIT,
        seed=seed,
        languages=["en"],
        cache_dir=CACHE_DIR,
    )


def _mono_wikidata(store: EntityStore, seed: int) -> list[Query]:
    return wikidata.build(
        store=store,
        limit=_MONO_WIKIDATA_LIMIT,
        seed=seed,
        languages=["en"],
        cache_dir=CACHE_DIR,
    )


def _mono_synthetic(store: EntityStore, seed: int) -> list[Query]:
    return synthetic.build(store=store, limit=_MONO_SYNTHETIC_LIMIT, seed=seed)


_MULTI_LANGS: tuple[str, ...] = ("es", "fr", "de")


def _multi_cldr(store: EntityStore, seed: int) -> list[Query]:
    return cldr.build(
        store=store,
        limit=_MULTI_CLDR_LIMIT * len(_MULTI_LANGS),
        seed=seed,
        languages=list(_MULTI_LANGS),
        cache_dir=CACHE_DIR,
    )


def _multi_geonames(store: EntityStore, seed: int) -> list[Query]:
    rows: list[Query] = []
    for lang in _MULTI_LANGS:
        rows.extend(
            geonames.build(
                store=store,
                limit=_MULTI_GEONAMES_PER_LANG,
                seed=seed,
                languages=[lang],
                cache_dir=CACHE_DIR,
            )
        )
    return rows


def _multi_wikidata(store: EntityStore, seed: int) -> list[Query]:
    rows: list[Query] = []
    for lang in _MULTI_LANGS:
        rows.extend(
            wikidata.build(
                store=store,
                limit=_MULTI_WIKIDATA_PER_LANG,
                seed=seed,
                languages=[lang],
                cache_dir=CACHE_DIR,
            )
        )
    return rows


_MONO_SOURCES: tuple[tuple[str, _SourceCall, dict[str, str]], ...] = (
    (
        "cldr",
        _mono_cldr,
        {"version": cldr.CLDR_VERSION, "url": cldr.CLDR_URL},
    ),
    (
        "geonames",
        _mono_geonames,
        {"version": "alternateNames-dump", "url": geonames.GEONAMES_URL},
    ),
    (
        "wikidata",
        _mono_wikidata,
        {"version": "sparql-2026-04", "url": wikidata.WIKIDATA_SPARQL_URL},
    ),
    (
        "synthetic",
        _mono_synthetic,
        {"version": "gecko-0.6.4"},
    ),
)

_MULTI_SOURCES: tuple[tuple[str, _SourceCall, dict[str, str]], ...] = (
    (
        "cldr",
        _multi_cldr,
        {"version": cldr.CLDR_VERSION, "url": cldr.CLDR_URL},
    ),
    (
        "geonames",
        _multi_geonames,
        {"version": "alternateNames-dump", "url": geonames.GEONAMES_URL},
    ),
    (
        "wikidata",
        _multi_wikidata,
        {"version": "sparql-2026-04", "url": wikidata.WIKIDATA_SPARQL_URL},
    ),
)


def _build_from_sources(
    *,
    name: str,
    data_dir: Path,
    seed: int,
    sources: tuple[tuple[str, _SourceCall, dict[str, str]], ...],
    store: EntityStore,
) -> tuple[list[Query], BuildRecord]:
    rows: list[Query] = []
    source_records: list[dict[str, str]] = []
    for source_name, call, meta in sources:
        chunk = call(store, seed)
        rows.extend(chunk)
        source_records.append({"source": source_name, "rows": str(len(chunk)), **meta})
    return _finalize(
        name=name,
        rows=rows,
        data_dir=data_dir,
        sources=tuple(source_records),
        seed=seed,
    )


def _finalize(
    *,
    name: str,
    rows: list[Query],
    data_dir: Path,
    sources: tuple[dict[str, str], ...],
    seed: int,
    notes: str | None = None,
) -> tuple[list[Query], BuildRecord]:
    deduped = _dedupe(_drop_synthetic_cross_source_collisions(rows))
    stamped = [_assign_id(row) for row in deduped]
    path = data_dir / f"{name}.parquet"
    _write_parquet(stamped, path)
    sha = dataset_sha256(path) if path.exists() else ""
    record = BuildRecord(
        dataset=name,
        row_count=len(stamped),
        sources=sources,
        seed=seed,
        sha256=sha,
        notes=notes,
    )
    return stamped, record


def _dedupe(rows: list[Query]) -> list[Query]:
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    unique: list[Query] = []
    for row in rows:
        key = (row.text.lower(), row.language, tuple(sorted(row.expected_ids)))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _drop_synthetic_cross_source_collisions(rows: list[Query]) -> list[Query]:
    """Drop synthetic rows whose text matches any non-synthetic row for a different entity.

    A prefix-truncation of "Equatorial Guinea" yields "Guinea", but "Guinea" is
    itself a name for GIN. The gold demands the longer entity (GNQ), so the query
    is unanswerable: the text is a valid name for a different country in the
    dataset. The authority is all non-synthetic rows (canonicals AND aliases) —
    this catches alias-level collisions like "Republic of China" (a wikidata alias
    for TWN) when synthetic generation also produces it for CHN.
    Within-synthetic stem collisions are handled separately in ``synthetic.build``.
    """
    canonical: dict[tuple[str, str], set[tuple[str, ...]]] = defaultdict(set)
    for row in rows:
        if row.source != "synthetic":
            canonical[(row.text.lower(), row.entity_type)].add(
                tuple(sorted(row.expected_ids))
            )

    kept: list[Query] = []
    dropped = 0
    for row in rows:
        if row.source == "synthetic":
            names = canonical.get((row.text.lower(), row.entity_type))
            if names and tuple(sorted(row.expected_ids)) not in names:
                dropped += 1
                continue
        kept.append(row)
    if dropped:
        logger.debug(
            "Dropped %d synthetic rows colliding with canonical names", dropped
        )
    return kept


def _assign_id(row: Query) -> Query:
    anchor = row.expected_ids[0] if row.expected_ids else ""
    digest = hashlib.sha1(f"{row.source}|{row.text}|{anchor}".encode()).hexdigest()[:16]
    return Query(
        query_id=digest,
        text=row.text,
        expected_ids=row.expected_ids,
        language=row.language,
        entity_type=row.entity_type,
        category=row.category,
        difficulty=row.difficulty,
        capabilities=row.capabilities,
        source=row.source,
        notes=row.notes,
    )


def _write_parquet(rows: list[Query], path: Path) -> None:
    frame = pl.DataFrame(
        {
            "query_id": [r.query_id for r in rows],
            "query": [r.text for r in rows],
            "expected_ids": [list(r.expected_ids) for r in rows],
            "language": [r.language for r in rows],
            "entity_type": [r.entity_type for r in rows],
            "category": [r.category for r in rows],
            "difficulty": [r.difficulty for r in rows],
            "capabilities": [list(r.capabilities) for r in rows],
            "source": [r.source for r in rows],
            "notes": [r.notes for r in rows],
        },
        schema={
            "query_id": pl.Utf8,
            "query": pl.Utf8,
            "expected_ids": pl.List(pl.Utf8),
            "language": pl.Utf8,
            "entity_type": pl.Utf8,
            "category": pl.Utf8,
            "difficulty": pl.Utf8,
            "capabilities": pl.List(pl.Utf8),
            "source": pl.Utf8,
            "notes": pl.Utf8,
        },
    )
    frame.write_parquet(path, compression="zstd")


def _build_geo_countries_en(
    *, name: str, data_dir: Path, store: EntityStore, seed: int
) -> tuple[list[Query], BuildRecord]:
    return _build_from_sources(
        name=name,
        data_dir=data_dir,
        seed=seed,
        sources=_MONO_SOURCES,
        store=store,
    )


def _build_geo_countries_multilingual(
    *, name: str, data_dir: Path, store: EntityStore, seed: int
) -> tuple[list[Query], BuildRecord]:
    return _build_from_sources(
        name=name,
        data_dir=data_dir,
        seed=seed,
        sources=_MULTI_SOURCES,
        store=store,
    )


def _build_ambiguous(
    *, name: str, data_dir: Path, store: EntityStore, seed: int
) -> tuple[list[Query], BuildRecord]:
    return _finalize(
        name=name,
        rows=ambiguous.build(store=store, seed=seed),
        data_dir=data_dir,
        sources=({"source": "curated", "notes": "hand-authored ambiguous"},),
        seed=seed,
    )


def _build_no_match(
    *, name: str, data_dir: Path, store: EntityStore, seed: int
) -> tuple[list[Query], BuildRecord]:
    return _finalize(
        name=name,
        rows=no_match.build(store=store, seed=seed),
        data_dir=data_dir,
        sources=({"source": "curated", "notes": "hand-authored no-match"},),
        seed=seed,
    )


def _build_geo_admin(
    *, name: str, data_dir: Path, store: EntityStore, seed: int
) -> tuple[list[Query], BuildRecord]:
    return _finalize(
        name=name,
        rows=geo_admin.build(store=store, seed=seed),
        data_dir=data_dir,
        sources=(
            {
                "source": "shared_entities_sqlite",
                "notes": "geo admin1/admin2 sampled from shared entity store",
            },
            {"source": "synthetic", "version": "gecko-0.6.4"},
        ),
        seed=seed,
    )


def _build_geo_cities(
    *, name: str, data_dir: Path, store: EntityStore, seed: int
) -> tuple[list[Query], BuildRecord]:
    return _finalize(
        name=name,
        rows=geo_cities.build(store=store, seed=seed),
        data_dir=data_dir,
        sources=(
            {
                "source": "shared_entities_sqlite",
                "notes": "geo cities sampled from shared entity store",
            },
            {"source": "synthetic", "version": "gecko-0.6.4"},
        ),
        seed=seed,
    )


# Single source of truth for all known datasets.

DATASET_SPECS.update(
    {
        "geo_countries_en": DatasetSpec(
            name="geo_countries_en",
            build_fn=_build_geo_countries_en,
            source_limits={
                "cldr": _MONO_CLDR_LIMIT,
                "geonames": _MONO_GEONAMES_LIMIT,
                "wikidata": _MONO_WIKIDATA_LIMIT,
                "synthetic": _MONO_SYNTHETIC_LIMIT,
            },
        ),
        "geo_countries_multilingual": DatasetSpec(
            name="geo_countries_multilingual",
            build_fn=_build_geo_countries_multilingual,
            source_limits={
                "cldr": _MULTI_CLDR_LIMIT,
                "geonames": _MULTI_GEONAMES_PER_LANG,
                "wikidata": _MULTI_WIKIDATA_PER_LANG,
            },
        ),
        "ambiguous": DatasetSpec(
            name="ambiguous",
            build_fn=_build_ambiguous,
        ),
        "no_match": DatasetSpec(
            name="no_match",
            build_fn=_build_no_match,
        ),
        "geo_admin": DatasetSpec(
            name="geo_admin",
            build_fn=_build_geo_admin,
        ),
        "geo_cities": DatasetSpec(
            name="geo_cities",
            build_fn=_build_geo_cities,
        ),
        "eval_geo": DatasetSpec(
            name="eval_geo",
            build_fn=None,
            requires_pack=None,
            eval=True,
            notes=(
                "Committed geo eval set; edit benchmarks/data/eval_geo.csv "
                "and regenerate via scripts/data_maintenance/convert_eval_csv.py."
            ),
        ),
        "eval_org": DatasetSpec(
            name="eval_org",
            build_fn=None,
            requires_pack=None,
            eval=True,
            notes=(
                "Committed org eval set; edit benchmarks/data/eval_org.csv "
                "and regenerate via scripts/data_maintenance/convert_eval_csv.py. "
                "Scores low until the org pack is loaded — that is expected."
            ),
        ),
        "eval_parse": DatasetSpec(
            name="eval_parse",
            build_fn=None,
            requires_pack=None,
            eval=True,
            notes=(
                "Committed parse eval set (multi-span, adversarial); edit "
                "benchmarks/data/eval_parse.csv and regenerate via "
                "scripts/data_maintenance.convert_eval_csv. Scored exclusively "
                "through benchmarks/parse/ (mention-level P/R/F1); the "
                "single-response benchmarks/core engine excludes it to avoid "
                "a bogus 0%% accuracy row."
            ),
        ),
    }
)
assert set(DATASET_SPECS) == set(DATASET_NAMES), (
    f"DATASET_SPECS keys {sorted(DATASET_SPECS)} do not match "
    f"DATASET_NAMES {sorted(DATASET_NAMES)}"
)


__all__ = ["DATASET_SPECS", "BuildRecord", "DatasetSpec", "build_all", "build_dataset"]
