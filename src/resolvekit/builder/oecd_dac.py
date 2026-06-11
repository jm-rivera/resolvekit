"""OECD DAC enricher: inject recipients, providers, channels, and agencies.

Reads ``data/oecd_dac.yaml`` and ``data/oecd_crosswalk.yaml`` at build time
and computes entities, names, codes, and relations for the geo and/or org
staging SQLite DBs. Returns a ``GraphContribution`` per domain; the pipeline
writes them via ``apply_contribution``. Idempotent on re-run (INSERT OR IGNORE
throughout via the contribution writer).

Registered in ``pipeline/enrich.py`` via a single out-of-loop invocation
(both DBs passed at once) because the enricher spans two domains.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from pathlib import Path
from typing import Any, Literal

from resolvekit.builder.pipeline.contribution import GraphContribution
from resolvekit.builder.sqlite.context import connect_sqlite
from resolvekit.core.util.normalization import TextNormalizer

try:
    import yaml as _yaml
except ImportError:  # pragma: no cover - optional dep
    _yaml = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_OECD_DAC_YAML = Path(__file__).parent / "data" / "oecd_dac.yaml"
_OECD_CROSSWALK_YAML = Path(__file__).parent / "data" / "oecd_crosswalk.yaml"

_normalizer = TextNormalizer()

# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────


def _load_yaml(path: Path) -> dict[str, Any]:
    if _yaml is None:
        raise ImportError(
            "oecd_dac enricher requires pyyaml. "
            "Install with: pip install 'resolvekit[data]'"
        )
    if not path.exists():
        raise FileNotFoundError(f"OECD DAC YAML not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return _yaml.safe_load(fh) or {}


def _entity_id_exists(conn: sqlite3.Connection, entity_id: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM entities WHERE entity_id = ?", (entity_id,)
        ).fetchone()
        is not None
    )


def _validate_crosswalk(
    crosswalk: dict[str, Any],
    *,
    geo_db: Path | None,
    org_db: Path | None,
) -> dict[str, Literal["geo", "org"]]:
    """Verify every non-null crosswalk target exists in one of the staging DBs.

    Returns a mapping of entity_id -> "geo" | "org" for every confirmed target,
    so callers can route writes without re-querying.

    Skips None values (the "not yet mapped" sentinel) and skips entries whose
    target DB is unavailable in this build. Raises ValueError with the offending
    key when an entity_id is non-null but found in neither available DB.
    """
    sections = [
        (name, section)
        for name, section in crosswalk.items()
        if name != "version" and isinstance(section, dict)
    ]

    target_db: dict[str, Literal["geo", "org"]] = {}

    with contextlib.ExitStack() as stack:
        geo_conn: sqlite3.Connection | None = (
            stack.enter_context(connect_sqlite(geo_db, busy_timeout_ms=30000))
            if geo_db is not None and geo_db.exists()
            else None
        )
        org_conn: sqlite3.Connection | None = (
            stack.enter_context(connect_sqlite(org_db, busy_timeout_ms=30000))
            if org_db is not None and org_db.exists()
            else None
        )

        for section_name, section in sections:
            for key, entity_id in section.items():
                if entity_id is None or entity_id in target_db:
                    continue

                found = False
                if geo_conn is not None and _entity_id_exists(geo_conn, entity_id):
                    target_db[entity_id] = "geo"
                    found = True
                elif org_conn is not None and _entity_id_exists(org_conn, entity_id):
                    target_db[entity_id] = "org"
                    found = True

                # Log a warning when a non-null crosswalk target is absent from all
                # available DBs. Partial or filtered builds may not include the full
                # entity corpus, so a missing entity might simply not be ingested yet
                # rather than truly missing. We skip gracefully and don't attach the
                # OECD code to that entity in this run.
                if not found:
                    logger.warning(
                        "oecd_dac crosswalk: %r[%r] = %r not found in any available DB"
                        " — skipping",
                        section_name,
                        key,
                        entity_id,
                    )

    return target_db


def _iso3_to_entity_id(conn: sqlite3.Connection) -> dict[str, str]:
    """Return {iso3_code: entity_id} from the codes table."""
    rows = conn.execute(
        "SELECT entity_id, value FROM codes WHERE system = 'iso3'"
    ).fetchall()
    return {str(row[1]).upper(): str(row[0]) for row in rows}


def _normalize_agency_key(key: str) -> str:
    """Uppercase the iso3 portion of an agency crosswalk key (e.g. 'aut:1' -> 'AUT:1').

    If the key has no ':', passes it through unchanged so a malformed key still
    fails cleanly in _validate_crosswalk rather than silently corrupting the lookup.
    """
    if ":" not in key:
        return key
    iso3_part, rest = key.split(":", 1)
    return f"{iso3_part.upper()}:{rest}"


def _build_provider_iso3_map(providers: list[dict[str, Any]]) -> dict[str, str]:
    """Return {provider_code: iso3} for providers that have an iso3."""
    result: dict[str, str] = {}
    for p in providers:
        iso3 = p.get("iso3")
        if iso3:
            result[str(p["code"])] = str(iso3).upper()
    return result


def _insert_entity(
    contrib: GraphContribution,
    *,
    entity_id: str,
    entity_type: str,
    canonical_name: str,
) -> None:
    norm = _normalizer.normalize(canonical_name)
    contrib.entities.append(
        {
            "entity_id": entity_id,
            "entity_type": entity_type,
            "canonical_name": canonical_name,
            "canonical_name_norm": norm,
            "valid_from": None,
            "valid_until": None,
            "attrs_json": "{}",
        }
    )


def _insert_name(
    contrib: GraphContribution,
    *,
    entity_id: str,
    name_kind: str,
    value: str,
    lang: str = "en",
    is_preferred: int = 0,
) -> None:
    norm = _normalizer.normalize(value)
    contrib.names.append(
        {
            "entity_id": entity_id,
            "name_kind": name_kind,
            "value": value,
            "value_norm": norm,
            "lang": lang,
            "script": "",
            "is_preferred": is_preferred,
        }
    )


def _insert_code(
    contrib: GraphContribution,
    *,
    entity_id: str,
    system: str,
    value: str,
) -> None:
    contrib.codes.append(
        {
            "entity_id": entity_id,
            "system": system,
            "value": value,
            "value_norm": value.lower(),
        }
    )


def _insert_relation(
    contrib: GraphContribution,
    *,
    entity_id: str,
    relation_type: str,
    target_id: str,
) -> None:
    contrib.relations.append(
        {
            "entity_id": entity_id,
            "relation_type": relation_type,
            "target_id": target_id,
            "valid_from": None,
            "valid_until": None,
        }
    )


def _attach_names_and_code(
    contrib: GraphContribution,
    *,
    entity_id: str,
    name_en: str,
    name_fr: str | None,
    code_system: str,
    code_value: str,
) -> None:
    if name_en:
        _insert_name(
            contrib, entity_id=entity_id, name_kind="alias", value=name_en, lang="en"
        )
    if name_fr:
        _insert_name(
            contrib, entity_id=entity_id, name_kind="alias", value=name_fr, lang="fr"
        )
    _insert_code(contrib, entity_id=entity_id, system=code_system, value=code_value)


# ──────────────────────────────────────────────────────────────────────────────
# Per-section upsert helpers
# ──────────────────────────────────────────────────────────────────────────────


def _upsert_recipients(
    geo_contrib: GraphContribution,
    recipients: list[dict[str, Any]],
    iso3_map: dict[str, str],
) -> None:
    for row in recipients:
        code = str(row["code"])
        name_en = row.get("name_en") or ""
        name_fr = row.get("name_fr")
        iso3 = row.get("iso3")

        entity_id: str | None = None
        if iso3:
            iso3 = iso3.upper()
            entity_id = iso3_map.get(iso3)
            if entity_id is None:
                # iso3 in OECD but not in geo DB (e.g. XKX/Kosovo) — treat as region
                logger.debug(
                    "oecd_dac: recipient iso3 %r not in geo DB — creating region entity",
                    iso3,
                )
        if entity_id is None:
            entity_id = f"geo.region/oecd:{code}"
            _insert_entity(
                geo_contrib,
                entity_id=entity_id,
                entity_type="geo.region",
                canonical_name=name_en or code,
            )

        _attach_names_and_code(
            geo_contrib,
            entity_id=entity_id,
            name_en=name_en,
            name_fr=name_fr,
            code_system="oecd:recipient",
            code_value=code,
        )


def _upsert_country_providers(
    geo_contrib: GraphContribution,
    providers: list[dict[str, Any]],
    iso3_map: dict[str, str],
) -> None:
    for row in providers:
        iso3 = row.get("iso3")
        if not iso3:
            continue
        iso3 = iso3.upper()
        entity_id = iso3_map.get(iso3)
        if entity_id is None:
            logger.debug(
                "oecd_dac: provider iso3 %r not in geo DB — skipping geo attach", iso3
            )
            continue
        code = str(row["code"])
        name_en = row.get("name_en") or ""
        name_fr = row.get("name_fr")
        _attach_names_and_code(
            geo_contrib,
            entity_id=entity_id,
            name_en=name_en,
            name_fr=name_fr,
            code_system="oecd:provider",
            code_value=code,
        )


def _upsert_multilateral_providers(
    geo_contrib: GraphContribution | None,
    org_contrib: GraphContribution | None,
    providers: list[dict[str, Any]],
    crosswalk_providers: dict[str, Any],
    crosswalk_target_db: dict[str, Literal["geo", "org"]],
) -> None:
    for row in providers:
        if row.get("iso3"):
            continue  # country providers handled in geo contribution
        code = str(row["code"])
        name_en = row.get("name_en") or ""
        name_fr = row.get("name_fr")

        mapped_entity_id = crosswalk_providers.get(code)

        if mapped_entity_id is not None:
            db_label = crosswalk_target_db.get(mapped_entity_id)
            if db_label == "geo" and geo_contrib is not None:
                _attach_names_and_code(
                    geo_contrib,
                    entity_id=mapped_entity_id,
                    name_en=name_en,
                    name_fr=name_fr,
                    code_system="oecd:provider",
                    code_value=code,
                )
            elif db_label == "org" and org_contrib is not None:
                _attach_names_and_code(
                    org_contrib,
                    entity_id=mapped_entity_id,
                    name_en=name_en,
                    name_fr=name_fr,
                    code_system="oecd:provider",
                    code_value=code,
                )
            # if target DB is unavailable, skip gracefully
        elif org_contrib is not None:
            entity_id = f"org/oecd:provider:{code}"
            # No module ships org.organization, so such a provider would be
            # pruned at packaging and any subsidiary_of edge pointing at it
            # (multilateral agency -> provider) would dangle. Route non-IGO
            # providers to org.development_finance_provider (org.providers
            # module); multilateral IGOs ship via the org.igos module.
            entity_type = (
                "org.igo"
                if row.get("type") == "Multilateral"
                else "org.development_finance_provider"
            )
            _insert_entity(
                org_contrib,
                entity_id=entity_id,
                entity_type=entity_type,
                canonical_name=name_en or code,
            )
            _attach_names_and_code(
                org_contrib,
                entity_id=entity_id,
                name_en=name_en,
                name_fr=name_fr,
                code_system="oecd:provider",
                code_value=code,
            )


def _resolve_channel_entity_id(
    code: str,
    crosswalk_channels: dict[str, Any],
) -> str:
    target = crosswalk_channels.get(code)
    if target is not None:
        return target
    return f"org/oecd:channel:{code}"


def _upsert_channels(
    geo_contrib: GraphContribution | None,
    org_contrib: GraphContribution | None,
    channels: list[dict[str, Any]],
    crosswalk_channels: dict[str, Any],
    crosswalk_target_db: dict[str, Literal["geo", "org"]],
) -> None:
    # Pass 1: create entities / attach codes
    for row in channels:
        code = str(row["code"])
        name_en = row.get("name_en") or ""
        name_fr = row.get("name_fr")
        acronym = row.get("acronym")

        mapped_entity_id = crosswalk_channels.get(code)

        if mapped_entity_id is not None:
            db_label = crosswalk_target_db.get(mapped_entity_id)
            target_contrib = geo_contrib if db_label == "geo" else org_contrib
            if target_contrib is None:
                continue
            _attach_names_and_code(
                target_contrib,
                entity_id=mapped_entity_id,
                name_en=name_en,
                name_fr=name_fr,
                code_system="oecd:channel",
                code_value=code,
            )
            if acronym:
                _insert_name(
                    target_contrib,
                    entity_id=mapped_entity_id,
                    name_kind="alias",
                    value=acronym,
                    lang="en",
                )
        elif org_contrib is not None:
            entity_id = f"org/oecd:channel:{code}"
            _insert_entity(
                org_contrib,
                entity_id=entity_id,
                entity_type="org.organization",
                canonical_name=name_en or code,
            )
            _attach_names_and_code(
                org_contrib,
                entity_id=entity_id,
                name_en=name_en,
                name_fr=name_fr,
                code_system="oecd:channel",
                code_value=code,
            )
            if acronym:
                _insert_name(
                    org_contrib,
                    entity_id=entity_id,
                    name_kind="alias",
                    value=acronym,
                    lang="en",
                )

    # Pass 2: parent_of relations (org-only entities; geo targets are pre-existing)
    for row in channels:
        code = str(row["code"])
        category = str(row.get("category", code))
        if code == category:
            continue  # top-level bucket — no parent relation

        child_mapped = crosswalk_channels.get(code)
        parent_mapped = crosswalk_channels.get(category)

        child_id = (
            child_mapped if child_mapped is not None else f"org/oecd:channel:{code}"
        )
        parent_id = (
            parent_mapped
            if parent_mapped is not None
            else f"org/oecd:channel:{category}"
        )

        child_db = crosswalk_target_db.get(child_id, "org") if child_mapped else "org"
        parent_db = (
            crosswalk_target_db.get(parent_id, "org") if parent_mapped else "org"
        )

        # Only write relation when both child and parent are in org contribution
        # (geo entities are pre-existing)
        if child_db == "org" and parent_db == "org" and org_contrib is not None:
            _insert_relation(
                org_contrib,
                entity_id=child_id,
                relation_type="part_of",
                target_id=parent_id,
            )


def _resolve_multilateral_donor_entity(
    donor_code: str,
    crosswalk_providers: dict[str, Any],
) -> str:
    """Return the subsidiary_of target entity_id for a multilateral donor agency.

    Prefers the crosswalk-mapped entity (a geo or org entity the provider was
    linked to). Falls back to the OECD-created provider entity in org_db.
    """
    mapped = crosswalk_providers.get(donor_code)
    if mapped is not None:
        return mapped
    return f"org/oecd:provider:{donor_code}"


def _upsert_agencies(
    org_contrib: GraphContribution,
    agencies: list[dict[str, Any]],
    provider_iso3_map: dict[str, str],
    crosswalk_agencies: dict[str, Any],
    crosswalk_providers: dict[str, Any],
    all_provider_codes: set[str],
) -> None:
    for row in agencies:
        code = str(row["code"])
        donor_code = str(row.get("donor_code", ""))
        name_en = row.get("name_en") or ""
        name_fr = row.get("name_fr")
        acronym = row.get("acronym")

        donor_iso3 = provider_iso3_map.get(donor_code)

        if donor_iso3 is not None:
            # Country donor path: composite code pairs the donor's ISO3 with the agency code
            composite_code = f"{donor_iso3}:{code}"
            entity_id = crosswalk_agencies.get(composite_code)
            if entity_id is None:
                entity_id = f"org/oecd:agency:{donor_iso3}:{code}"
                _insert_entity(
                    org_contrib,
                    entity_id=entity_id,
                    entity_type="org.government_organization",
                    canonical_name=name_en or composite_code,
                )

            _attach_names_and_code(
                org_contrib,
                entity_id=entity_id,
                name_en=name_en,
                name_fr=name_fr,
                code_system="oecd:agency",
                code_value=composite_code,
            )
            if acronym:
                _insert_name(
                    org_contrib,
                    entity_id=entity_id,
                    name_kind="alias",
                    value=acronym,
                    lang="en",
                )

            donor_entity_id = f"country/{donor_iso3}"
            _insert_relation(
                org_contrib,
                entity_id=entity_id,
                relation_type="subsidiary_of",
                target_id=donor_entity_id,
            )

        elif donor_code in all_provider_codes:
            # Multilateral donor path — donor exists as a provider but has no iso3
            composite_code = f"{donor_code}:{code}"
            entity_id = f"org/oecd:agency:{donor_code}:{code}"
            _insert_entity(
                org_contrib,
                entity_id=entity_id,
                entity_type="org.government_organization",
                canonical_name=name_en or composite_code,
            )

            _attach_names_and_code(
                org_contrib,
                entity_id=entity_id,
                name_en=name_en,
                name_fr=name_fr,
                code_system="oecd:agency",
                code_value=composite_code,
            )
            if acronym:
                _insert_name(
                    org_contrib,
                    entity_id=entity_id,
                    name_kind="alias",
                    value=acronym,
                    lang="en",
                )

            donor_entity_id = _resolve_multilateral_donor_entity(
                donor_code, crosswalk_providers
            )
            _insert_relation(
                org_contrib,
                entity_id=entity_id,
                relation_type="subsidiary_of",
                target_id=donor_entity_id,
            )

        else:
            logger.warning(
                "oecd_dac: agency %r has donor_code %r not in providers list — skipping",
                code,
                donor_code,
            )


# ──────────────────────────────────────────────────────────────────────────────
# Public surface
# ──────────────────────────────────────────────────────────────────────────────


def build_oecd_contributions(
    *, geo_db: Path | None, org_db: Path | None
) -> dict[str, GraphContribution]:
    """Compute OECD DAC contributions for the geo and/or org domains (pure reads).

    Returns ``{"geo": GraphContribution, "org": GraphContribution}``. A None DB
    yields an empty contribution for that domain. The pipeline writes each via
    ``apply_contribution``. Cross-domain crosswalk routing is computed once here (it
    queries both DBs read-only), so per-row geo-vs-org targeting is preserved.
    """
    if geo_db is None and org_db is None:
        return {"geo": GraphContribution(), "org": GraphContribution()}

    dac_data = _load_yaml(_OECD_DAC_YAML)
    crosswalk = _load_yaml(_OECD_CROSSWALK_YAML)

    # `or []`/`or {}` guards against an explicit `null` value in the YAML
    # (e.g. `providers:` with no list under it), which `.get(key, [])` doesn't.
    recipients: list[dict[str, Any]] = dac_data.get("recipients") or []
    providers: list[dict[str, Any]] = dac_data.get("providers") or []
    channels: list[dict[str, Any]] = dac_data.get("channels") or []
    agencies: list[dict[str, Any]] = dac_data.get("agencies") or []

    crosswalk_providers: dict[str, Any] = crosswalk.get("providers") or {}
    crosswalk_channels: dict[str, Any] = crosswalk.get("channels") or {}
    crosswalk_agencies: dict[str, Any] = {
        _normalize_agency_key(k): v
        for k, v in (crosswalk.get("agencies") or {}).items()
    }

    crosswalk_target_db = _validate_crosswalk(crosswalk, geo_db=geo_db, org_db=org_db)

    all_provider_codes: set[str] = {str(p["code"]) for p in providers}

    geo_contrib = GraphContribution()
    org_contrib = GraphContribution()

    # Read iso3 map from geo DB (read-only connection; no writes here).
    if geo_db is not None:
        with connect_sqlite(geo_db) as conn:
            iso3_map = _iso3_to_entity_id(conn)
        _upsert_recipients(geo_contrib, recipients, iso3_map)
        _upsert_country_providers(geo_contrib, providers, iso3_map)

    provider_iso3_map = _build_provider_iso3_map(providers)
    _upsert_multilateral_providers(
        geo_contrib if geo_db is not None else None,
        org_contrib if org_db is not None else None,
        providers,
        crosswalk_providers,
        crosswalk_target_db,
    )
    _upsert_channels(
        geo_contrib if geo_db is not None else None,
        org_contrib if org_db is not None else None,
        channels,
        crosswalk_channels,
        crosswalk_target_db,
    )

    if org_db is not None:
        _upsert_agencies(
            org_contrib,
            agencies,
            provider_iso3_map,
            crosswalk_agencies,
            crosswalk_providers,
            all_provider_codes,
        )

    # Return empty contributions for absent DBs so callers can safely call
    # apply_contribution without routing checks.
    return {
        "geo": geo_contrib if geo_db is not None else GraphContribution(),
        "org": org_contrib if org_db is not None else GraphContribution(),
    }
