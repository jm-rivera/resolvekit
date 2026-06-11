"""Build the geo.continents datapack from the hardcoded seed source.

Continents are a closed, well-known set of eight entities (seven geographic
continents + the pan-American supercontinent "Americas") whose Wikidata Q-IDs
are stable constants.  No network fetch is needed; this script writes directly
from ``resolvekit.builder.sources.seed.continents``.

The script writes:
  src/resolvekit/_data/geo/continents/entities.sqlite
  src/resolvekit/_data/geo/continents/symspell.dict
  src/resolvekit/_data/geo/continents/metadata.json

It is safe to re-run; the pack is regenerated in place and the data_version
is read from the existing metadata.json (if present) so a plain rebuild does
not reset a CalVer that release_data.py already stamped.

Run via::

    uv run python -m scripts.build.build_continents
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from resolvekit.builder.sources.seed.continents import (
    CONTINENT_REUSE_EDGES,
    CONTINENTS,
    ENTITY_TYPE,
)
from resolvekit.builder.sqlite import (
    build_symspell_dictionary,
    connect_sqlite,
    ensure_sqlite_schema,
    rebuild_fts,
    transaction,
    validate_domain_db,
)
from resolvekit.builder.utils import sha256_file, utc_now_iso
from resolvekit.core.datapack import (
    ENTITY_SCHEMA_VERSION,
    NORMALIZER_VERSION,
    DataPackMetadata,
)
from resolvekit.core.linking.base_normalizer import BaseNormalizer
from resolvekit.core.util.normalization import TextNormalizer

logger = logging.getLogger(__name__)

# Shared code normalizer — write-side partner to the query-side normalizer.
_CODE_NORMALIZER = BaseNormalizer()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DATAPACKS_ROOT = _PROJECT_ROOT / "src" / "resolvekit" / "_data"
_OUTPUT_DIR = _DATAPACKS_ROOT / "geo" / "continents"

MODULE_ID = "geo.continents"
DOMAIN_PACK_ID = "geo"
FEATURE_SCHEMA_VERSION = "geo.features.v1"
DEFAULT_DATA_VERSION = "2026.06"


def _read_existing_data_version(output_dir: Path) -> str:
    """Return the on-disk data_version to avoid resetting a CalVer stamp."""
    meta_path = output_dir / "metadata.json"
    if not meta_path.exists():
        return DEFAULT_DATA_VERSION
    try:
        meta = DataPackMetadata.from_file(meta_path)
        return meta.data_version or DEFAULT_DATA_VERSION
    except Exception:
        return DEFAULT_DATA_VERSION


def build_continents_sqlite(db_path: Path, normalizer: TextNormalizer) -> None:
    """Materialize continent seed rows into a fresh SQLite file."""
    db_path.unlink(missing_ok=True)
    ensure_sqlite_schema(db_path)

    with connect_sqlite(db_path, busy_timeout_ms=30000) as conn, transaction(conn):
        for entry in CONTINENTS:
            name_norm = normalizer.normalize(entry.canonical_name)

            # entities row
            conn.execute(
                "INSERT OR IGNORE INTO entities"
                "(entity_id, entity_type, canonical_name, canonical_name_norm,"
                " valid_from, valid_until, attrs_json)"
                " VALUES (?, ?, ?, ?, NULL, NULL, ?)",
                (
                    entry.entity_id,
                    ENTITY_TYPE,
                    entry.canonical_name,
                    name_norm,
                    json.dumps({"source": "seed"}),
                ),
            )

            # codes: wikidata + dcid
            conn.execute(
                "INSERT OR IGNORE INTO codes(entity_id, system, value, value_norm)"
                " VALUES (?, ?, ?, ?)",
                (
                    entry.entity_id,
                    "wikidata",
                    entry.wikidata_qid,
                    _CODE_NORMALIZER.normalize_code("wikidata", entry.wikidata_qid),
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO codes(entity_id, system, value, value_norm)"
                " VALUES (?, ?, ?, ?)",
                (
                    entry.entity_id,
                    "dcid",
                    entry.entity_id,
                    _CODE_NORMALIZER.normalize_code("dcid", entry.entity_id),
                ),
            )

            # canonical name row (lang='en', is_preferred=1)
            conn.execute(
                "INSERT OR IGNORE INTO names"
                "(entity_id, name_kind, value, value_norm, lang, script, is_preferred)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    entry.entity_id,
                    "canonical",
                    entry.canonical_name,
                    name_norm,
                    "en",
                    "",
                    1,
                ),
            )

            # additional names
            for value, lang, name_kind in entry.names:
                value_norm = normalizer.normalize(value)
                # skip if identical to the canonical row already inserted
                if (
                    value == entry.canonical_name
                    and lang == "en"
                    and name_kind == "canonical"
                ):
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO names"
                    "(entity_id, name_kind, value, value_norm, lang, script, is_preferred)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        entry.entity_id,
                        name_kind,
                        value,
                        value_norm,
                        lang,
                        "",
                        1 if name_kind == "canonical" else 0,
                    ),
                )

        # Two continent-sourced containment reuse edges.
        # Q18 (South America) → m49/419 (Latin America & the Caribbean) and
        # Q49 (Northern America) → Q828 (Americas).
        # validate_domain_db(..., allow_external_relation_targets=True) in main()
        # accepts the external target m49/419 (lives in geo.regions).
        for source_id, target_id in CONTINENT_REUSE_EDGES:
            conn.execute(
                "INSERT OR IGNORE INTO relations"
                "(entity_id, relation_type, target_id, valid_from, valid_until)"
                " VALUES (?, ?, ?, NULL, NULL)",
                (source_id, "contained_in", target_id),
            )

    rebuild_fts(db_path)
    logger.info("Wrote %d continents to %s", len(CONTINENTS), db_path)


def main() -> None:
    """Build the geo.continents datapack."""
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data_version = _read_existing_data_version(_OUTPUT_DIR)

    normalizer = TextNormalizer()
    db_path = _OUTPUT_DIR / "entities.sqlite"
    symspell_path = _OUTPUT_DIR / "symspell.dict"
    meta_path = _OUTPUT_DIR / "metadata.json"

    build_continents_sqlite(db_path, normalizer)

    build_symspell_dictionary(db_path, symspell_path)
    logger.info("Wrote symspell dict to %s", symspell_path)

    metrics, issues = validate_domain_db(db_path, allow_external_relation_targets=True)
    if issues:
        logger.error("Validation issues: %s", issues)
        raise SystemExit(1)

    checksums = {
        "sqlite": sha256_file(db_path),
        "symspell": sha256_file(symspell_path),
    }

    metadata = DataPackMetadata(
        datapack_id=f"{MODULE_ID}-v{data_version}",
        module_id=MODULE_ID,
        domain_pack_id=DOMAIN_PACK_ID,
        module_dependencies=[],
        entity_schema_version=ENTITY_SCHEMA_VERSION,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        normalizer_version=NORMALIZER_VERSION,
        index_versions={"fts": "fts5", "symspell": "symspell.dict"},
        build_timestamp=utc_now_iso(),
        source_datasets=["seed"],
        artifacts={"symspell": symspell_path.name},
        description=None,
        checksums=checksums,
        distribution="bundled",
        remote_artifacts=None,
        data_version=data_version,
        pack_type="base",
        store_type="sqlite",
        store_file="entities.sqlite",
        quality_metrics={
            "entity_count": int(metrics.get("entity_count") or 0),
            "names_count": int(metrics.get("names_count") or 0),
            "codes_count": int(metrics.get("codes_count") or 0),
            "relations_count": int(metrics.get("relations_count") or 0),
            "names_coverage": float(metrics.get("names_coverage") or 0.0),
            "codes_coverage": float(metrics.get("codes_coverage") or 0.0),
            "relations_density": float(metrics.get("relations_density") or 0.0),
        },
    )

    metadata.to_file(meta_path)
    logger.info("Wrote metadata to %s", meta_path)
    logger.info(
        "geo.continents built: %d entities, %d names, %d codes",
        int(metrics.get("entity_count") or 0),
        int(metrics.get("names_count") or 0),
        int(metrics.get("codes_count") or 0),
    )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(
            "build_continents.py takes no CLI arguments. "
            "Configure it by editing the module-level constants."
        )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    main()
