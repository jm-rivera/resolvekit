"""Builder for org DataPacks."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from resolvekit.shared.build.base_builder import BaseDataPackBuilder


class OrgDataPackBuilder(BaseDataPackBuilder):
    """Builds org DataPack artifacts.

    Extends BaseDataPackBuilder with org-specific helpers:
    - add_org: Add entity with auto-prefixed type
    - add_acronym, add_short_name, add_legal_name: Name helpers
    - add_parent_org: Add parent organization relation
    - add_country_code: Add country code to entity attrs
    - add_external_code: Add external code identifiers
    """

    DOMAIN_PACK_ID = "org"
    FEATURE_SCHEMA_VERSION = "org.features.v1"

    def set_base_modules(self, base_paths: Sequence[str | Path]) -> None:
        """Set base modules for build-time entity linking.

        Args:
            base_paths: Paths to datapack directories in the base composition.
        """
        from resolvekit.packs.org.linker import OrgLinker
        from resolvekit.packs.org.normalizer import OrgNormalizer

        self._open_base_stores(base_paths)
        self._linker = OrgLinker()
        self._normalizer = OrgNormalizer()

    def add_org(
        self,
        entity_id: str,
        entity_type: str,
        canonical_name: str,
        canonical_name_norm: str,
        valid_from: str | None = None,
        valid_until: str | None = None,
        attrs: dict[str, Any] | None = None,
    ) -> None:
        """Add an organization entity with auto-prefixed type.

        If entity_type doesn't start with 'org.', it will be prefixed.
        """
        if not entity_type.startswith("org."):
            entity_type = f"org.{entity_type}"

        self.add_entity(
            entity_id=entity_id,
            entity_type=entity_type,
            canonical_name=canonical_name,
            canonical_name_norm=canonical_name_norm,
            valid_from=valid_from,
            valid_until=valid_until,
            attrs=attrs,
        )

    def add_acronym(
        self,
        entity_id: str,
        value: str,
        value_norm: str,
        lang: str | None = None,
        script: str | None = None,
        is_preferred: bool = False,
    ) -> None:
        """Add an acronym name variant."""
        self.add_name(
            entity_id=entity_id,
            name_kind="acronym",
            value=value,
            value_norm=value_norm,
            lang=lang,
            script=script,
            is_preferred=is_preferred,
        )

    def add_short_name(
        self,
        entity_id: str,
        value: str,
        value_norm: str,
        lang: str | None = None,
        script: str | None = None,
        is_preferred: bool = False,
    ) -> None:
        """Add a short name variant."""
        self.add_name(
            entity_id=entity_id,
            name_kind="short_name",
            value=value,
            value_norm=value_norm,
            lang=lang,
            script=script,
            is_preferred=is_preferred,
        )

    def add_legal_name(
        self,
        entity_id: str,
        value: str,
        value_norm: str,
        lang: str | None = None,
        script: str | None = None,
        is_preferred: bool = False,
    ) -> None:
        """Add a legal name variant."""
        self.add_name(
            entity_id=entity_id,
            name_kind="legal_name",
            value=value,
            value_norm=value_norm,
            lang=lang,
            script=script,
            is_preferred=is_preferred,
        )

    def add_parent_org(
        self,
        entity_id: str,
        parent_id: str,
        relation_type: str = "subsidiary_of",
    ) -> None:
        """Add a parent organization relation.

        Args:
            entity_id: The child organization entity ID
            parent_id: The parent organization entity ID
            relation_type: The relation type (default: "subsidiary_of")
        """
        self.add_relation(
            entity_id=entity_id,
            relation_type=relation_type,
            target_id=parent_id,
        )

    def add_country_code(
        self,
        entity_id: str,
        country_code: str,
    ) -> None:
        """Add country code to entity attrs.

        Args:
            entity_id: The entity ID
            country_code: ISO 3166-1 alpha-2 country code (2 characters)

        Raises:
            ValueError: If country_code is not 2 characters
        """
        if len(country_code) != 2:
            raise ValueError(f"Country code must be 2 characters, got: {country_code}")

        country_code = country_code.upper()

        if not self._conn:
            raise RuntimeError("Database not created. Call create_database first.")

        row = self._conn.execute(
            "SELECT attrs_json FROM entities WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()

        if row is None:
            raise ValueError(f"Entity not found: {entity_id}")

        existing_attrs = json.loads(row[0]) if row[0] else {}
        existing_attrs["country_code"] = country_code

        self._conn.execute(
            "UPDATE entities SET attrs_json = ? WHERE entity_id = ?",
            (json.dumps(existing_attrs), entity_id),
        )

    def add_external_code(
        self,
        entity_id: str,
        system: str,
        value: str,
        value_norm: str,
    ) -> None:
        """Add an external code identifier.

        This is a convenience wrapper around add_code for org-specific usage.
        """
        self.add_code(
            entity_id=entity_id,
            system=system,
            value=value,
            value_norm=value_norm,
        )
