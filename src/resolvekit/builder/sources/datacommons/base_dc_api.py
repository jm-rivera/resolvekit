"""Base class for Data Commons domain fetch APIs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from resolvekit.builder.sources.datacommons.client import DataCommons
from resolvekit.builder.sources.datacommons.constants import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_LANGUAGE,
    DESCRIPTION_PROPERTY,
    SUBCLASS_OF_PROPERTY,
    TYPE_OF_PROPERTY,
)
from resolvekit.builder.sources.datacommons.node import (
    build_alias_rows_from_names,
    build_alias_rows_from_properties,
    build_code_rows,
    build_scalar_attrs,
    merge_alias_rows,
    node_string,
)


class BaseDcApi(ABC):
    """Shared Data Commons fetch logic parameterized by domain-specific constants.

    Subclasses set:
      _alias_properties  — property-to-alias-kind mapping (used by get_aliases)
      _code_properties   — list of DC property names for get_codes
      _attr_properties   — property-to-attr-key mapping (used by get_descriptions)
      _codes_chunk_size  — chunk size for get_codes; None falls back to DEFAULT_CHUNK_SIZE
    """

    _alias_properties: dict[str, str]
    _code_properties: list[str]
    _attr_properties: dict[str, str]
    _codes_chunk_size: int | None = None

    def __init__(self, runtime: DataCommons) -> None:
        self._runtime = runtime

    @abstractmethod
    def get_entity_types(self, entity_ids: list[str]) -> dict[str, str]:
        """Return the preferred type for each entity id; domain-specific logic varies."""

    def get_entity_names(
        self,
        entity_ids: list[str],
        *,
        lang: str = DEFAULT_LANGUAGE,
    ) -> dict[str, str]:
        return self._runtime.fetch_entity_names(entity_ids, lang=lang)

    def get_entity_name_rows(
        self,
        entity_ids: list[str],
        *,
        lang: str = DEFAULT_LANGUAGE,
        fallback_lang: str | None = None,
    ):
        return self._runtime.fetch_entity_name_rows(
            entity_ids,
            lang=lang,
            fallback_lang=fallback_lang,
        )

    def get_entities_by_type(self, *, raw_type: str) -> list[str]:
        raw = self._get_property_values(
            [raw_type],
            [TYPE_OF_PROPERTY],
            out=False,
        )
        nodes = raw.get(raw_type, {}).get(TYPE_OF_PROPERTY, [])
        entity_ids = [
            entity_id for node in nodes if (entity_id := node_string(node)) is not None
        ]
        return list(dict.fromkeys(entity_ids))

    def get_type_subclasses(self, *, raw_type: str) -> list[str]:
        raw = self._get_property_values(
            [raw_type],
            [SUBCLASS_OF_PROPERTY],
            out=False,
        )
        nodes = raw.get(raw_type, {}).get(SUBCLASS_OF_PROPERTY, [])
        subclasses = [
            subclass for node in nodes if (subclass := node_string(node)) is not None
        ]
        return list(dict.fromkeys(subclasses))

    def get_codes(self, entity_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        kwargs: dict[str, Any] = {}
        if self._codes_chunk_size is not None:
            kwargs["chunk_size"] = self._codes_chunk_size
        raw = self._get_property_values(entity_ids, self._code_properties, **kwargs)
        return build_code_rows(raw)

    def get_aliases(
        self,
        entity_ids: list[str],
        *,
        languages: list[str],
        canonical_names: dict[str, str] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        if canonical_names is None:
            canonical_names = self.get_entity_names(entity_ids, lang=DEFAULT_LANGUAGE)
        alias_props = self._get_property_values(
            entity_ids,
            list(self._alias_properties),
        )
        by_entity = build_alias_rows_from_properties(
            alias_props,
            property_roles=self._alias_properties,
            canonical_names=canonical_names,
        )

        for lang in languages:
            by_entity = merge_alias_rows(
                by_entity,
                build_alias_rows_from_names(
                    self.get_entity_name_rows(entity_ids, lang=lang),
                    canonical_names=canonical_names,
                ),
            )

        return {entity_id: by_entity.get(entity_id, []) for entity_id in entity_ids}

    def get_descriptions(self, entity_ids: list[str]) -> dict[str, dict[str, str]]:
        raw = self._get_property_values(entity_ids, [DESCRIPTION_PROPERTY])
        return build_scalar_attrs(raw, property_names=self._attr_properties)

    def get_property_labels(
        self,
        entity_ids: list[str],
        *,
        out: bool = True,
    ) -> dict[str, list[str]]:
        return self._runtime.fetch_property_labels(entity_ids, out=out)

    def _get_property_values(
        self,
        entity_ids: list[str],
        properties: list[str],
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        **kwargs: Any,
    ) -> dict[str, dict[str, list[Any]]]:
        return self._runtime.fetch_property_values(
            entity_ids,
            properties,
            chunk_size=chunk_size,
            **kwargs,
        )
