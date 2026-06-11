"""Groups enricher: inject curated group entities, aliases, and member_of relations.

Reads src/resolvekit/builder/data/groups.yaml and writes into the geo staging
SQLite DB. Idempotent on PKs: re-running produces zero net changes.

Registered as an enricher under COUNTRY_ENTITY_TYPE in pipeline/enrich.py
(countries are always present in geo DBs; group entities are created here).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from resolvekit.builder.pipeline.contribution import GraphContribution
from resolvekit.builder.sqlite.context import connect_sqlite
from resolvekit.core.util.normalization import TextNormalizer

try:
    import yaml as _yaml
except ImportError:  # pragma: no cover - optional dep
    _yaml = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

GEO_ORGANIZATION_ENTITY_TYPE = "geo.organization"
_GROUPS_YAML_PATH = Path(__file__).parent / "data" / "groups.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    if _yaml is None:
        raise ImportError(
            "groups enricher requires pyyaml. "
            "Install with: pip install 'resolvekit[data]'"
        )
    with path.open("r", encoding="utf-8") as fh:
        return _yaml.safe_load(fh)


def build_group_contribution(db_path: Path) -> GraphContribution:
    """Compute group entities, aliases, and member_of relations (pure read).

    Returns a ``GraphContribution`` with all rows to insert. The caller
    (pipeline) writes them via ``apply_contribution``. Idempotent on re-run.
    """
    data = _load_yaml(_GROUPS_YAML_PATH)
    groups = data.get("groups", [])
    if not groups:
        return GraphContribution()

    normalizer = TextNormalizer()

    # Read the iso3 map in a separate read connection before building rows.
    # Safe because groups only reads iso3 codes that pre-exist (never codes it
    # contributes), and enrichers run after reconcile so codes are already committed.
    with connect_sqlite(db_path) as conn:
        iso3_map: dict[str, str] = {
            str(row[1]).upper(): str(row[0])
            for row in conn.execute(
                "SELECT entity_id, value FROM codes WHERE system = 'iso3'"
            ).fetchall()
        }

    contribution = GraphContribution()
    for group in groups:
        group_contribution = _collect_group(group, normalizer, iso3_map)
        contribution.entities.extend(group_contribution.entities)
        contribution.names.extend(group_contribution.names)
        contribution.relations.extend(group_contribution.relations)
    return contribution


def _collect_group(
    group: dict[str, Any],
    normalizer: TextNormalizer,
    iso3_map: dict[str, str],
) -> GraphContribution:
    """Build one group's entity, alias, and relation rows as a contribution."""
    contribution = GraphContribution()
    entity_id: str = group["id"]
    entity_type: str = group.get("type", GEO_ORGANIZATION_ENTITY_TYPE)
    canonical_name: str = group["canonical_name"]
    canonical_name_norm = normalizer.normalize(canonical_name)
    valid_from: str | None = group.get("valid_from")
    valid_until: str | None = group.get("valid_until")

    # snapshot flag goes into attrs_json so it's visible to the resolver's
    # _is_snapshot_entity check.
    snapshot = bool(group.get("snapshot", False))
    attrs_json = '{"snapshot": true}' if snapshot else "{}"

    # If the entity already existed (DC-sourced, e.g. EuropeanUnion or GroupOf7) and
    # the YAML says snapshot=true, we'd want to UPDATE attrs_json. None of
    # the v1 snapshot entities reuse a DC entity_id (snapshots all use the
    # groups/* prefix), so this UPDATE path is omitted in v1. Add when needed.

    contribution.entities.append(
        {
            "entity_id": entity_id,
            "entity_type": entity_type,
            "canonical_name": canonical_name,
            "canonical_name_norm": canonical_name_norm,
            "valid_from": valid_from,
            "valid_until": valid_until,
            "attrs_json": attrs_json,
        }
    )

    for alias in group.get("aliases", []):
        alias_norm = normalizer.normalize(str(alias))
        contribution.names.append(
            {
                "entity_id": entity_id,
                "name_kind": "alias",
                "value": str(alias),
                "value_norm": alias_norm,
                "lang": "en",
                "script": "",
                "is_preferred": 0,
            }
        )

    for member in group.get("members", []):
        iso3 = str(member["iso3"]).upper()
        member_entity_id = iso3_map.get(iso3)
        if member_entity_id is None:
            logger.warning(
                "groups enricher: unknown iso3 %r for group %r — skipping",
                iso3,
                entity_id,
            )
            continue
        vf = member.get("valid_from")
        vu = member.get("valid_until")
        contribution.relations.append(
            {
                "entity_id": member_entity_id,
                "relation_type": "member_of",
                "target_id": entity_id,
                "valid_from": vf,
                "valid_until": vu,
            }
        )

    return contribution
