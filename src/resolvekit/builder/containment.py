"""Containment enricher: mint M.49 sub-regions and emit ``contained_in`` edges.

Reads from ``builder/sources/seed/m49.py`` (a typed Python constant module,
not a network fetch) and writes into the geo staging SQLite DB.  Idempotent
on PKs: re-running produces zero net changes.

Registered as an enricher under COUNTRY_ENTITY_TYPE in pipeline/enrich.py
(countries are always present in geo DBs; sub-region entities are minted here).

Design:
- Each ``M49Region`` becomes a ``geo.subregion`` entity with entity_id
  ``m49/<code>``, a canonical ``names`` row (so ``lookup_name_exact``
  resolves it), an ``m49`` code row, alias ``names`` rows, and a
  ``contained_in`` relation pointing at its parent.
- Country-sourced ``contained_in`` edges (country → leaf node) are derived
  from ``M49_COUNTRY_ASSIGNMENTS`` by looking up iso3 in the DB.
- The two continent-sourced reuse edges (``Q18→m49/419``, ``Q49→Q828``) are
  NOT emitted here — those live in ``geo.continents`` and are written by
  ``build_continents.py``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from resolvekit.builder.pipeline.contribution import GraphContribution
from resolvekit.builder.sources.seed.m49 import M49_COUNTRY_ASSIGNMENTS, M49_REGIONS
from resolvekit.builder.sqlite.context import connect_sqlite
from resolvekit.core.util.normalization import TextNormalizer

logger = logging.getLogger(__name__)

GEO_REGION_ENTITY_TYPE = "geo.subregion"


def build_containment_contribution(db_path: Path) -> GraphContribution:
    """Compute M.49 region entities, names, codes, and ``contained_in`` relations.

    Returns a ``GraphContribution`` with all rows to insert.  The caller
    (pipeline) writes them via ``apply_contribution``.  Idempotent on re-run.

    Emits:
    - One ``entities`` row per ``M49Region`` (type ``geo.subregion``).
    - One canonical ``names`` row per region (lang ``en``, is_preferred 1).
    - Alias ``names`` rows for each declared alias.
    - One ``codes`` row per region (system ``m49``).
    - One region-sourced ``contained_in`` relation per region (region → parent).
    - One country-sourced ``contained_in`` relation per ``M49_COUNTRY_ASSIGNMENTS``
      entry where the iso3 is found in the DB.

    Does NOT emit the two continent-sourced reuse edges (``CONTINENT_REUSE_EDGES``)
    — those are owned by ``geo.continents`` and written by ``build_continents.py``.
    """
    normalizer = TextNormalizer()

    # Read the iso3→entity_id map from a separate read connection before building
    # rows.  Same pattern as groups.py.
    with connect_sqlite(db_path) as conn:
        iso3_map: dict[str, str] = {
            str(row[1]).upper(): str(row[0])
            for row in conn.execute(
                "SELECT entity_id, value FROM codes WHERE system = 'iso3'"
            ).fetchall()
        }

    contribution = GraphContribution()

    # ── Mint each M49Region ──────────────────────────────────────────────────
    for region in M49_REGIONS:
        name_norm = normalizer.normalize(region.canonical_name)

        # entities row
        contribution.entities.append(
            {
                "entity_id": region.entity_id,
                "entity_type": GEO_REGION_ENTITY_TYPE,
                "canonical_name": region.canonical_name,
                "canonical_name_norm": name_norm,
                "valid_from": None,
                "valid_until": None,
                "attrs_json": '{"source": "m49"}',
            }
        )

        # Canonical names row (lookup_name_exact reads the names table)
        contribution.names.append(
            {
                "entity_id": region.entity_id,
                "name_kind": "canonical",
                "value": region.canonical_name,
                "value_norm": name_norm,
                "lang": "en",
                "script": "",
                "is_preferred": 1,
            }
        )

        # Alias names rows
        for alias in region.aliases:
            contribution.names.append(
                {
                    "entity_id": region.entity_id,
                    "name_kind": "alias",
                    "value": alias,
                    "value_norm": normalizer.normalize(alias),
                    "lang": "en",
                    "script": "",
                    "is_preferred": 0,
                }
            )

        # m49 code row
        contribution.codes.append(
            {
                "entity_id": region.entity_id,
                "system": "m49",
                "value": region.code,
                "value_norm": region.code,
            }
        )

        # Region-sourced contained_in edge (region → parent)
        # parent_id may be another m49/* or a continent wikidataId/Q<n> — both
        # are valid because the *source* is the minted region.
        contribution.relations.append(
            {
                "entity_id": region.entity_id,
                "relation_type": "contained_in",
                "target_id": region.parent_id,
                "valid_from": None,
                "valid_until": None,
            }
        )

    # ── Country-sourced contained_in edges ──────────────────────────────────
    unknown_iso3: list[str] = []
    for iso3, leaf_id in M49_COUNTRY_ASSIGNMENTS.items():
        country_entity_id = iso3_map.get(iso3.upper())
        if country_entity_id is None:
            unknown_iso3.append(iso3)
            continue
        contribution.relations.append(
            {
                "entity_id": country_entity_id,
                "relation_type": "contained_in",
                "target_id": leaf_id,
                "valid_from": None,
                "valid_until": None,
            }
        )

    if unknown_iso3:
        logger.warning(
            "containment enricher: %d unknown iso3 code(s) skipped: %s",
            len(unknown_iso3),
            ", ".join(sorted(unknown_iso3)),
        )

    return contribution
