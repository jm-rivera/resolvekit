"""Enrichment stage: inject curated entity-graph data after reconcile.

Enrichments shape the staging entity graph so packaged datapacks contain
the right rows for resolution. Each enricher targets one entity type and
is idempotent: re-running a build yields zero net changes the second time
because inserts collide on the ``names`` PK and deletes target rows that
have already been removed.

Two flavors of enricher are supported:

* **Adders** — contribute additional ``names`` rows (e.g. formal designations,
  CLDR multilingual aliases, ``St.`` abbreviations). Return a ``GraphContribution``
  with the rows to insert.
* **Filters** — contribute entity ids to delete from the staging DB when those
  entities are known to corrupt resolution (UN aggregate placeholders,
  ``[former]`` historical states). Return a ``GraphContribution`` with
  ``entity_ids_to_delete`` populated.

Enrichers run against the *staging* layer — the shared geo store for geo
domains, and the run-local staging DB otherwise — so the resulting rows go
through the standard validate / package / QA path. Packaging then slices a
subset out without any domain-specific augmentation logic.

To register an enricher for a new entity type, append it to ``_ENRICHERS``
under the matching entity-type key.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from resolvekit.builder.containment import build_containment_contribution
from resolvekit.builder.country_geonames_aliases import (
    build_geonames_country_aliases_contribution,
)
from resolvekit.builder.entity_validity import build_entity_validity_contribution
from resolvekit.builder.formal_names import (
    COUNTRY_ENTITY_TYPE,
    build_formal_name_contribution,
)
from resolvekit.builder.groups import build_group_contribution
from resolvekit.builder.oecd_dac import build_oecd_contributions
from resolvekit.builder.pipeline.contribution import (
    GraphContribution,
    apply_contribution,
)
from resolvekit.builder.pipeline.geo_staging import canonical_staging_db
from resolvekit.builder.sqlite import rebuild_fts
from resolvekit.builder.sqlite.context import connect_sqlite, transaction
from resolvekit.core.util.normalization import TextNormalizer

if TYPE_CHECKING:
    from resolvekit.builder.pipeline.core import BuildContext

logger = logging.getLogger(__name__)

REGION_ENTITY_TYPE = "geo.region"

EnricherFn = Callable[[Path], GraphContribution]

# Per-table deltas reported for a domain whose staging DB is absent.
_ZERO_DELTAS: dict[str, int] = {
    "entities": 0,
    "names": 0,
    "codes": 0,
    "relations": 0,
}


def _build_multilingual_names_contribution(db_path: Path) -> GraphContribution:
    """Add multilingual country names from CLDR (en/es/fr/ru/zh/ar + extras).

    Source rows come from
    :func:`resolvekit.calibration.adapters.multilingual_names.generate_name_rows`,
    which reads CLDR territory names via the pooch-cached zip (or Babel
    fallback) and shapes them for direct INSERT. Returns a ``GraphContribution``
    with the name rows; the pipeline writes them via ``apply_contribution``.
    """
    # Import the leaf module directly to avoid loading the calibration
    # adapters package umbrella, which pulls gecko in via synthetic.py.
    # geo builds with the `data` extra (no `calibration`) would otherwise
    # fail with ModuleNotFoundError at this import.
    from resolvekit.calibration.adapters.multilingual_names import (
        generate_name_rows,
    )
    from resolvekit.core.store import SQLiteEntityStore

    store = SQLiteEntityStore(db_path)
    try:
        rows = generate_name_rows(store=store)
    finally:
        store.close()

    if not rows:
        return GraphContribution()

    return GraphContribution(names=rows)


def _build_st_aliases_contribution(db_path: Path) -> GraphContribution:
    """For every ``Saint X`` country alias, also emit ``St. X`` and ``St X``.

    The CLDR multilingual import already adds many ``St.``-prefixed short
    variants (e.g. ``St. Lucia``), but several long-form aliases like
    ``Saint Helena, Ascension and Tristan da Cunha`` and ``Saint Vincent
    and the Grenadines`` still abstain when queried with the abbreviated
    spelling. This enricher closes that gap by deriving abbreviation
    variants from the bag of existing English ``Saint X`` rows.

    Reads AFTER the multilingual enricher commits, so it picks up ``Saint X``
    rows that multilingual writing added (per-enricher commit ordering).
    """
    normalizer = TextNormalizer()

    with connect_sqlite(db_path) as conn:
        rows = conn.execute(
            """
            SELECT entity_id, value
            FROM names
            WHERE entity_id IN (
                SELECT entity_id FROM entities WHERE entity_type = ?
            )
            AND lang = 'en'
            AND value LIKE 'Saint %'
            """,
            (COUNTRY_ENTITY_TYPE,),
        ).fetchall()

    name_dicts: list[dict] = []
    for entity_id, value in rows:
        suffix = str(value)[len("Saint ") :]
        if not suffix:
            continue
        for variant in (f"St. {suffix}", f"St {suffix}"):
            name_dicts.append(
                {
                    "entity_id": str(entity_id),
                    "name_kind": "alias",
                    "value": variant,
                    "value_norm": normalizer.normalize(variant),
                    "lang": "en",
                    "script": "",
                    "is_preferred": 0,
                }
            )

    return GraphContribution(names=name_dicts)


_REGION_ALIASES_YAML_PATH = (
    Path(__file__).parent.parent / "data" / "region_aliases.yaml"
)


def _build_region_aliases_contribution(db_path: Path) -> GraphContribution:
    """Add curated short-form aliases for geo.region entities (pure read).

    Reads ``builder/data/region_aliases.yaml`` and emits alias name rows for
    undata-geo region entities whose canonical names include a "MDG Region:"
    prefix or an income-level suffix that prevents matching the plain
    geographic label (e.g. "Sub-Saharan Africa", "MENA", "Western Europe").

    Only emits rows for entity_ids that actually exist in ``db_path`` so the
    function is safe to run against partial staging DBs.
    """
    try:
        import yaml as _yaml
    except ImportError as e:
        raise ImportError(
            "region_aliases enricher requires pyyaml. "
            "Install with: pip install 'resolvekit[data]'"
        ) from e

    with _REGION_ALIASES_YAML_PATH.open("r", encoding="utf-8") as fh:
        data = _yaml.safe_load(fh) or {}

    entries = data.get("aliases", [])
    if not entries:
        return GraphContribution()

    with connect_sqlite(db_path) as conn:
        present_ids = {
            str(row[0])
            for row in conn.execute(
                "SELECT entity_id FROM entities WHERE entity_type = ?",
                (REGION_ENTITY_TYPE,),
            ).fetchall()
        }

    if not present_ids:
        return GraphContribution()

    normalizer = TextNormalizer()
    name_dicts: list[dict] = []
    for entry in entries:
        entity_id = str(entry["entity_id"])
        if entity_id not in present_ids:
            continue
        for alias in entry.get("aliases", []):
            alias_str = str(alias)
            name_dicts.append(
                {
                    "entity_id": entity_id,
                    "name_kind": "alias",
                    "value": alias_str,
                    "value_norm": normalizer.normalize(alias_str),
                    "lang": "en",
                    "script": "",
                    "is_preferred": 0,
                }
            )

    return GraphContribution(names=name_dicts)


# Patterns that flag UN-statistics aggregate or placeholder ``geo.region``
# entities. These rows are noise for resolution: they win exact-name matches
# for country-shaped queries (``Federal Republic of Germany`` →
# ``undata-geo/G00001020`` instead of ``country/DEU``) and false-positive on
# no-match queries (``not applicable`` → ``undata-geo/G00900010``).
_REGION_NOISE_ID_PATTERNS: tuple[str, ...] = (
    "undata-geo/G009%",  # admin placeholders ("Not applicable", "Bunkers", ...)
)
_REGION_NOISE_NAME_PATTERNS: tuple[str, ...] = (
    "%[former]%",
    "%: All cities or breakdown%",
    "%not elsewhere specified%",
)

# Specific geo.region aggregate entities whose canonical name collides with a
# country exact-name match. G00003070 ("Taiwan province of China") owns the
# exact_name claim on the UN long-form label and pre-empts country/TWN.
# This clause is intentionally independent of the entity_type filter so that
# the explicit ids are deleted regardless of their current type in the store.
_REGION_NOISE_EXPLICIT_IDS: tuple[str, ...] = ("undata-geo/G00003070",)


def _build_region_filter_contribution(db_path: Path) -> GraphContribution:
    """Identify UN-aggregate placeholder ``geo.region`` entities for removal.

    Returns a ``GraphContribution`` with ``entity_ids_to_delete`` populated.
    ``apply_contribution`` cascades the deletes across names/codes/relations/entities.

    Two independent SELECT clauses are UNIONed:
    * Pattern-based: entity_type-filtered noise by id/name patterns.
    * Explicit-id: unconditional deletion of specific entities by id,
      independent of entity_type (robust against future type changes).
    """
    id_clauses = [
        f"entity_id LIKE '{pattern}'" for pattern in _REGION_NOISE_ID_PATTERNS
    ]
    name_clauses = [
        f"canonical_name LIKE '{pattern}'" for pattern in _REGION_NOISE_NAME_PATTERNS
    ]
    where = " OR ".join(id_clauses + name_clauses)
    pattern_sql = f"SELECT entity_id FROM entities WHERE entity_type = ? AND ({where})"

    placeholders = ", ".join("?" * len(_REGION_NOISE_EXPLICIT_IDS))
    explicit_sql = f"SELECT entity_id FROM entities WHERE entity_id IN ({placeholders})"

    union_sql = f"{pattern_sql} UNION {explicit_sql}"

    with connect_sqlite(db_path) as conn:
        params: tuple = (REGION_ENTITY_TYPE, *_REGION_NOISE_EXPLICIT_IDS)
        ids = [str(row[0]) for row in conn.execute(union_sql, params)]

    if not ids:
        return GraphContribution()

    return GraphContribution(entity_ids_to_delete=ids)


# Registry of enrichers keyed by entity_type they target.
#
# Enricher contract:
#   • Receive ``db_path: Path``; must be idempotent.
#   • Return a ``GraphContribution`` with the rows to add or entity ids to
#     delete. The pipeline calls ``apply_contribution`` and commits before
#     the next enricher reads, preserving the multilingual→st_aliases
#     read-after-write dependency.
#   • **Must NOT call ``rebuild_fts``** — enrichers don't write, so they
#     structurally cannot. FTS rebuild is deferred to ``stage_enrich``
#     until *after* both the per-domain loop and the cross-domain OECD
#     pass have applied their contributions. This is the deferred-FTS-rebuild
#     invariant pinned by ``tests/builder/test_enrich_fts_ordering.py``.
#
# The stage runs an enricher only if its entity_type is present in the
# database being enriched. Multiple enrichers may share an entity_type —
# order is preserved.
#
# To add an enricher: append a function to the list under the matching
# entity-type key. Add a new key if the entity type is not yet present.
#
# NOTE — prominence enrichment runs out-of-band via
# ``scripts/build/enrich_prominence.py``, NOT through this registry.
# See that script's module docstring for details. Prominence is excluded
# here because the DC fetch is ~600K remote calls — far too slow for a
# plain ``build()`` — and because it must run against a fully-materialized
# shared store (after ``build_data``) then trigger a re-package pass.
_ENRICHERS: dict[str, list[EnricherFn]] = {
    COUNTRY_ENTITY_TYPE: [
        build_formal_name_contribution,
        _build_multilingual_names_contribution,
        _build_st_aliases_contribution,
        build_group_contribution,
        build_containment_contribution,
        build_geonames_country_aliases_contribution,
        build_entity_validity_contribution,
    ],
    REGION_ENTITY_TYPE: [
        _build_region_aliases_contribution,
        _build_region_filter_contribution,
    ],
}


def stage_enrich(context: BuildContext) -> None:
    """Apply registered enrichers to the canonical staging databases.

    For geo domains the canonical layer is the shared geo store; non-geo
    domains use the run-local staging DB. The stage records per-table deltas
    per enricher under ``staging_enrich`` for build-report observability.

    Domains are sourced from the build plan's recipes (not just the chunks
    discovered in the current pass) so enrichments still apply when discover was
    short-circuited because shared coverage was already complete.
    """
    report: dict[str, dict[str, Any]] = {}

    # FTS rebuilds are deferred until every enricher (per-domain loop *and* the
    # cross-domain OECD pass) has applied its contribution. Rebuilding eagerly
    # inside the per-domain loop would index a DB that the OECD pass then adds
    # more names to, dropping those later names from the index.
    dbs_needing_fts: set[Path] = set()

    domains_in_plan = sorted({recipe.domain for recipe in context.plan.recipes})
    for domain in domains_in_plan:
        db_path = canonical_staging_db(context, domain, phase="enrich")
        if db_path is None:
            continue

        domain_report = _enrich_database(db_path)
        if domain_report["names_changed"]:
            dbs_needing_fts.add(db_path)
        report[domain] = domain_report

    geo_db = canonical_staging_db(context, "geo", phase="enrich")
    org_db = canonical_staging_db(context, "org", phase="enrich")
    if geo_db is not None or org_db is not None:
        contribs = build_oecd_contributions(geo_db=geo_db, org_db=org_db)
        oecd_deltas: dict[str, dict[str, int]] = {}
        for domain_key, db in (("geo", geo_db), ("org", org_db)):
            if db is None:
                oecd_deltas[domain_key] = _ZERO_DELTAS.copy()
                continue
            with connect_sqlite(db, busy_timeout_ms=30000) as conn, transaction(conn):
                deltas = apply_contribution(
                    conn=conn, contribution=contribs[domain_key]
                )
            oecd_deltas[domain_key] = deltas
            if deltas["names"] != 0:
                dbs_needing_fts.add(db)
        report.setdefault("oecd_dac", {})["deltas"] = oecd_deltas

    for db_path in dbs_needing_fts:
        if db_path.exists():
            rebuild_fts(db_path)

    context.state.set_meta("staging_enrich", report)


def _enrich_database(db_path: Path) -> dict[str, Any]:
    """Run every applicable enricher against one database.

    For each enricher: call it (opens+closes its own read connection), then
    open a fresh write transaction and commit via ``apply_contribution`` before
    the next enricher reads. This preserves the multilingual→st_aliases
    read-after-write dependency.

    ``names_changed`` is the absolute total of names-row deltas so callers can
    decide whether to rebuild FTS regardless of direction.
    """
    present_types = _entity_types_present(db_path)

    results: dict[str, dict[str, dict[str, int]]] = {}
    names_changed = 0
    for entity_type, enrichers in _ENRICHERS.items():
        if entity_type not in present_types:
            continue
        per_enricher: dict[str, dict[str, int]] = {}
        for enricher in enrichers:
            contribution = enricher(db_path)  # opens+CLOSES its own read conn
            with (
                connect_sqlite(db_path, busy_timeout_ms=30000) as conn,
                transaction(conn),
            ):
                deltas = apply_contribution(conn=conn, contribution=contribution)
            # committed here; the NEXT enricher's read sees these rows
            per_enricher[getattr(enricher, "__name__", repr(enricher))] = deltas
            names_changed += abs(deltas["names"])
        results[entity_type] = per_enricher

    return {
        "results": results,
        "names_changed": names_changed,
    }


def _entity_types_present(db_path: Path) -> set[str]:
    """Return the distinct entity types found in a staging database."""
    with connect_sqlite(db_path) as conn:
        rows = conn.execute("SELECT DISTINCT entity_type FROM entities").fetchall()
    return {str(row[0]) for row in rows if row[0] is not None}
