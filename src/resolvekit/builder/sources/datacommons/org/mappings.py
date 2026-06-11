"""Static mappings and discovery defaults for org source values."""

from __future__ import annotations

from resolvekit.builder.sources.datacommons.constants import (
    ALT_NAME_PROPERTY,
    DESCRIPTION_PROPERTY,
    SHORT_DISPLAY_NAME_PROPERTY,
)
from resolvekit.builder.sources.datacommons.text import to_prefixed_entity_type

ORG_DOMAIN = "org"
ORG_DEFAULT_ENTITY_TYPE = "Organization"
ORG_DEFAULT_RELATION_TYPE = "related_to"
ORG_RELATION_TYPE_SUBSIDIARY = "subsidiary_of"
ORG_RELATION_TYPE_MEMBER = "member_of"

PARENT_ORGANIZATION_PROPERTY = "parentOrganization"
MEMBER_OF_PROPERTY = "memberOf"

ORG_ROOT_FAMILIES: tuple[str, ...] = (
    "Organization",
    "PoliticalParty",
    "DevelopmentFinanceProviderEnum",
    "LendingEntityEnum",
)

ORG_CODE_PROPERTIES = [
    "wikidataId",
    "dacCodeStr",
    "dacCodeInt",
    "unDataCode",
]

ORG_ALIAS_PROPERTIES = {
    ALT_NAME_PROPERTY: "alias",
    SHORT_DISPLAY_NAME_PROPERTY: "short_name",
}

ORG_ATTR_PROPERTIES = {
    DESCRIPTION_PROPERTY: "description",
}

ORG_UNFILTERED_ENTITY_TYPES: tuple[str, ...] = (
    "org.organization",
    "org.company",
    "org.corporation",
    # Dormant: the DC `NGO` class exists and is correctly rooted but is
    # unpopulated on the One.org instance. No catalog module ships for it; the
    # mapping is retained so it is recognised if upstream ever populates it.
    "org.ngo",
    "org.government_organization",
    "org.political_party",
    "org.development_finance_provider",
    "org.lending_entity",
    "org.igo",
    "org.data_source",
    "org.subsidiary",
)

_ORG_TYPE_MAPPING = {
    "IntergovernmentalOrganization": "org.igo",
    "InternationalOrganization": "org.igo",
    # Dormant — see ORG_UNFILTERED_ENTITY_TYPES note above.
    "NonGovernmentalOrganization": "org.ngo",
    "NGO": "org.ngo",
    "Corporation": "org.corporation",
    "Company": "org.company",
    "Source": "org.data_source",
    "Subsidiary": "org.subsidiary",
    "PoliticalParty": "org.political_party",
    "GovernmentOrganization": "org.government_organization",
    "DevelopmentFinanceProviderEnum": "org.development_finance_provider",
    "LendingEntityEnum": "org.lending_entity",
}


def to_org_entity_type(raw_entity_type: str) -> str:
    """Convert a raw Data Commons type into canonical ``org.<snake_case>``."""
    normalized = raw_entity_type.strip()
    if normalized in _ORG_TYPE_MAPPING:
        return _ORG_TYPE_MAPPING[normalized]
    return to_prefixed_entity_type(raw_entity_type, prefix="org")
