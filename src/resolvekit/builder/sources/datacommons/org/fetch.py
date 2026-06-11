"""Raw-chunk fetch assembly for the bounded Data Commons org source."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from resolvekit.builder.sources.datacommons import build_raw_chunk
from resolvekit.builder.sources.datacommons.constants import (
    DATACOMMONS_SOURCE,
    DEFAULT_LANGUAGE,
    FETCH_RAW_MAX_WORKERS,
)
from resolvekit.builder.sources.datacommons.models import RawChunk
from resolvekit.builder.sources.datacommons.org.dc_api import OrgDcApi
from resolvekit.builder.sources.datacommons.org.mappings import ORG_DEFAULT_ENTITY_TYPE


def fetch_raw_chunk(
    *,
    entity_ids: list[str],
    dc_api: OrgDcApi,
    languages: list[str],
) -> RawChunk:
    """Fetch and assemble one raw org chunk payload."""
    if not entity_ids:
        return RawChunk()

    with ThreadPoolExecutor(max_workers=FETCH_RAW_MAX_WORKERS) as executor:
        names_f = executor.submit(
            dc_api.get_entity_names,
            entity_ids,
            lang=DEFAULT_LANGUAGE,
        )
        types_f = executor.submit(dc_api.get_entity_types, entity_ids)
        codes_f = executor.submit(dc_api.get_codes, entity_ids)
        descriptions_f = executor.submit(dc_api.get_descriptions, entity_ids)
        relations_f = executor.submit(dc_api.get_relations, entity_ids)

        names = names_f.result()
        aliases_f = executor.submit(
            dc_api.get_aliases,
            entity_ids,
            languages=languages,
            canonical_names=names,
        )
        types = types_f.result()
        codes = codes_f.result()
        descriptions = descriptions_f.result()
        relations = relations_f.result()
        aliases = aliases_f.result()

    attrs = {
        entity_id: {
            "source": DATACOMMONS_SOURCE,
            "raw_entity_type": types.get(entity_id, ORG_DEFAULT_ENTITY_TYPE),
            "source_class_family": dc_api.get_source_class_family(
                types.get(entity_id, ORG_DEFAULT_ENTITY_TYPE)
            ),
            **descriptions.get(entity_id, {}),
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
        relations_by_entity=relations,
        default_entity_type=ORG_DEFAULT_ENTITY_TYPE,
    )
