"""Low-level Data Commons API fetch helpers for the org adapter."""

from __future__ import annotations

from functools import cached_property
from typing import override

from resolvekit.builder.sources.datacommons.base_dc_api import BaseDcApi
from resolvekit.builder.sources.datacommons.constants import (
    SUBCLASS_OF_PROPERTY,
    TYPE_OF_PROPERTY,
)
from resolvekit.builder.sources.datacommons.node import (
    node_string,
    select_preferred_type,
    walk_type_families,
)
from resolvekit.builder.sources.datacommons.org.mappings import (
    MEMBER_OF_PROPERTY,
    ORG_ALIAS_PROPERTIES,
    ORG_ATTR_PROPERTIES,
    ORG_CODE_PROPERTIES,
    ORG_RELATION_TYPE_MEMBER,
    ORG_RELATION_TYPE_SUBSIDIARY,
    ORG_ROOT_FAMILIES,
    PARENT_ORGANIZATION_PROPERTY,
)


class OrgDcApi(BaseDcApi):
    """Data Commons org-domain fetch API backed by live schema families."""

    _alias_properties = ORG_ALIAS_PROPERTIES
    _code_properties = ORG_CODE_PROPERTIES
    _attr_properties = ORG_ATTR_PROPERTIES

    @override
    def get_entity_types(self, entity_ids: list[str]) -> dict[str, str]:
        raw = self._get_property_values(entity_ids, [TYPE_OF_PROPERTY])
        types: dict[str, str] = {}
        for entity_id, props in raw.items():
            raw_type = select_preferred_type(
                props.get(TYPE_OF_PROPERTY, []),
                rank_by_type=self._supported_type_ranks,
                allowed_types=self._supported_raw_types,
            )
            if raw_type is not None:
                types[entity_id] = raw_type
        return types

    def get_all_classes(self) -> list[str]:
        return self._runtime.fetch_all_classes()

    def get_supported_raw_types(self) -> list[str]:
        return sorted(
            self._supported_raw_types,
            key=lambda raw_type: (
                self._supported_type_ranks.get(raw_type, 0),
                raw_type,
            ),
        )

    def get_supported_root_families(self) -> list[str]:
        return list(ORG_ROOT_FAMILIES)

    def get_source_class_family(self, raw_type: str) -> str:
        return self._supported_type_families.get(raw_type, raw_type.strip())

    def get_relations(self, entity_ids: list[str]) -> dict[str, list[dict[str, str]]]:
        raw = self._get_property_values(
            entity_ids,
            [PARENT_ORGANIZATION_PROPERTY, MEMBER_OF_PROPERTY],
        )
        relation_type_by_property = {
            PARENT_ORGANIZATION_PROPERTY: ORG_RELATION_TYPE_SUBSIDIARY,
            MEMBER_OF_PROPERTY: ORG_RELATION_TYPE_MEMBER,
        }
        relations: dict[str, list[dict[str, str]]] = {}
        for entity_id, props in raw.items():
            entity_relations: list[dict[str, str]] = []
            for property_name, relation_type in relation_type_by_property.items():
                for n in props.get(property_name, []):
                    if target_id := node_string(n):
                        entity_relations.append(
                            {
                                "relation_type": relation_type,
                                "target_id": target_id,
                            }
                        )
            relations[entity_id] = entity_relations
        return relations

    @cached_property
    def _supported_type_walk(self) -> tuple[dict[str, int], dict[str, str]]:
        children_by_parent: dict[str, set[str]] = {}
        for class_id, parents in self._class_parent_map.items():
            for parent in parents:
                children_by_parent.setdefault(parent, set()).add(class_id)

        return walk_type_families(
            roots=ORG_ROOT_FAMILIES,
            fetch_children=lambda raw_type: sorted(
                children_by_parent.get(raw_type, ())
            ),
        )

    @property
    def _supported_type_ranks(self) -> dict[str, int]:
        return {
            raw_type: 100 + depth
            for raw_type, depth in self._supported_type_walk[0].items()
        }

    @property
    def _supported_type_families(self) -> dict[str, str]:
        return self._supported_type_walk[1]

    @cached_property
    def _supported_raw_types(self) -> set[str]:
        return set(self._supported_type_walk[0])

    @cached_property
    def _class_parent_map(self) -> dict[str, set[str]]:
        all_classes = self.get_all_classes()
        raw = self._get_property_values(all_classes, [SUBCLASS_OF_PROPERTY])
        parent_map: dict[str, set[str]] = {}
        for class_id in all_classes:
            parent_map[class_id] = {
                parent
                for node in raw.get(class_id, {}).get(SUBCLASS_OF_PROPERTY, [])
                if (parent := node_string(node)) is not None
            }
        return parent_map
