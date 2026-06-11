"""Raw-chunk fetch assembly for Data Commons geo source."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from resolvekit.builder.sources.datacommons import (
    build_raw_chunk,
    relation_rows_from_targets,
)
from resolvekit.builder.sources.datacommons.constants import (
    DATACOMMONS_SOURCE,
    DEFAULT_LANGUAGE,
    FETCH_RAW_MAX_WORKERS,
)
from resolvekit.builder.sources.datacommons.geo.dc_api import GeoDcApi
from resolvekit.builder.sources.datacommons.geo.mappings import (
    GEO_DEFAULT_ENTITY_TYPE,
    GEO_DEFAULT_RELATION_TYPE,
)
from resolvekit.builder.sources.datacommons.models import RawChunk
from resolvekit.builder.sources.datacommons.node import merge_alias_rows
from resolvekit.builder.sources.wikidata.aliases import fetch_wikidata_en_aliases


def fetch_raw_chunk(
    *,
    entity_ids: list[str],
    dc_api: GeoDcApi,
    languages: list[str],
    wikidata_cache_dir: Path | None = None,
) -> RawChunk:
    """Fetch and assemble one raw geo chunk payload."""
    if not entity_ids:
        return RawChunk()

    with ThreadPoolExecutor(max_workers=FETCH_RAW_MAX_WORKERS) as executor:
        names_f = executor.submit(
            dc_api.get_entity_names,
            entity_ids,
            lang=DEFAULT_LANGUAGE,
        )
        types_f = executor.submit(dc_api.get_entity_types, entity_ids)
        coords_f = executor.submit(dc_api.get_lat_long, entity_ids)
        codes_f = executor.submit(dc_api.get_codes, entity_ids)
        descriptions_f = executor.submit(dc_api.get_descriptions, entity_ids)
        parents_f = executor.submit(dc_api.get_parents, entity_ids)

        names = names_f.result()
        aliases_f = executor.submit(
            dc_api.get_aliases,
            entity_ids,
            languages=languages,
            canonical_names=names,
        )
        types = types_f.result()
        coords = coords_f.result()
        codes = codes_f.result()
        descriptions = descriptions_f.result()
        parents = parents_f.result()
        aliases = aliases_f.result()

    en_aliases = fetch_wikidata_en_aliases(
        codes_by_entity=codes,
        foreign_names_by_entity=_foreign_names_from_aliases(aliases),
        cache_dir=wikidata_cache_dir,
    )
    aliases = merge_alias_rows(aliases, en_aliases)

    admin_levels = dc_api.get_admin_levels(
        entity_ids,
        entity_types=types,
        parents_by_entity=parents,
    )
    attrs = {
        entity_id: {
            "source": DATACOMMONS_SOURCE,
            "raw_entity_type": types.get(entity_id, GEO_DEFAULT_ENTITY_TYPE),
            "source_class_family": dc_api.get_source_class_family(
                types.get(entity_id, GEO_DEFAULT_ENTITY_TYPE)
            ),
            **coords.get(entity_id, {}),
            **descriptions.get(entity_id, {}),
            **(
                {"admin_level": admin_levels[entity_id]}
                if entity_id in admin_levels
                else {}
            ),
        }
        for entity_id in entity_ids
    }

    return build_raw_chunk(
        entity_ids=entity_ids,
        canonical_names=names,
        entity_types=types,
        attrs_by_entity=attrs,
        aliases_by_entity=aliases,
        codes_by_entity=codes,
        relations_by_entity=relation_rows_from_targets(
            parents,
            relation_type=GEO_DEFAULT_RELATION_TYPE,
        ),
        default_entity_type=GEO_DEFAULT_ENTITY_TYPE,
    )


def _foreign_names_from_aliases(
    aliases: dict[str, list[dict[str, str]]],
) -> dict[str, set[str]]:
    """Collect non-English alias texts keyed by entity id.

    Used to populate the ``foreign_names_by_entity`` endonym set passed to
    the Wikidata precision filter — any text that equals a non-English name
    fetched during the build is treated as an endonym and dropped.
    """
    out: dict[str, set[str]] = {}
    for entity_id, rows in aliases.items():
        for row in rows:
            if row.get("language", "en") != "en":
                out.setdefault(entity_id, set()).add(str(row.get("alias_text", "")))
    return out
