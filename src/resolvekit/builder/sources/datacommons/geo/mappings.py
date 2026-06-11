"""Static mappings and normalization helpers for geo source values."""

from __future__ import annotations

from typing import Any

from resolvekit.builder.sources.datacommons.constants import (
    ALT_NAME_PROPERTY,
    DESCRIPTION_PROPERTY,
    SHORT_DISPLAY_NAME_PROPERTY,
)
from resolvekit.builder.sources.datacommons.text import to_prefixed_entity_type

GEO_DOMAIN = "geo"
GEO_DEFAULT_ENTITY_TYPE = "Other"
GEO_DEFAULT_RELATION_TYPE = "contained_in"

ROOT_PLACE_DCID = "Earth"
UN_REGION_DCID = "UNGeoRegion"

PLACE_TYPE_COUNTRY = "Country"
PLACE_TYPE_GEO_REGION = "GeoRegion"
PLACE_TYPE_ADMINISTRATIVE_AREA = "AdministrativeArea"
PLACE_TYPE_CITY = "City"
PLACE_TYPE_PARENT_NODES = [PLACE_TYPE_ADMINISTRATIVE_AREA, PLACE_TYPE_GEO_REGION]
SPECIAL_PLACE_TYPES = {PLACE_TYPE_COUNTRY, PLACE_TYPE_GEO_REGION}

UN_DATA_LABEL_PROPERTY = "unDataLabel"

CENTROID_LAT_KEY = "centroid_lat"
CENTROID_LON_KEY = "centroid_lon"

ENTITY_TYPE_CHUNK_SIZE = 500
CODES_CHUNK_SIZE = 100
DISCOVERY_PARENT_BATCH_SIZE = 500
DISCOVERY_MAX_WORKERS = 20

LAT_LONG_PROPERTIES = ["latitude", "longitude"]
CODES_PROPERTIES = [
    "archinformLocationId",
    "babelnetId",
    "bbcThingsId",
    "brockhausEncyclopediaOnlineId",
    "civicusMonitorCountryId",
    "countryAlpha2Code",
    "countryAlpha3Code",
    "countryNumeric3Code",
    "countryNumericCode",
    "czechNkcrAutId",
    "encyclopediaBritannicaOnlineId",
    "encyclopediaLarousseOnlineId",
    "encyclopediaUniversalisId",
    "eurovoId",
    "facebookId",
    "fastId",
    "finlandYsoId",
    "fips104",
    "franceIdRefId",
    "franceNationalLibraryId",
    "gacsId",
    "gettyThesaurusOfGeographicNamesId",
    "gndId",
    "greatRussianEncyclopediaOnlineId",
    "gs1CountryCode",
    "hdsId",
    "iocCountryCode",
    "isoCode",
    "israelNationalLibraryId",
    "ituIsoIecObjectId",
    "ituLetterCode",
    "japanGeoNlpId",
    "leMondeDiplomatiqueSubjectId",
    "libraryOfCongressAuthorityId",
    "musicbrainzAreaId",
    "nationalDietLibraryId",
    "norwaySnlId",
    "osmRelationId",
    "quoraTopicId",
    "statoidsId",
    "stwThesaurusForEconomicsId",
    "swedishNationalEncyclopediaId",
    "uicAlphabeticalCountryCode",
    "uicNumericalCountryCode",
    "unDataCode",
    "unescoThesaurusId",
    "unitedKingdomParliamentThesaurusId",
    "unitedStatesNationalArchivesIdentifier",
    "viafId",
    "whosOnFirstId",
    "wikidataId",
    "wipoSt3Id",
    "worldcatIdentitiesId",
]

_CODE_SYSTEM_MAPPING = {
    "countryalpha2code": "iso2",
    "countryalpha3code": "iso3",
    "countrynumeric3code": "iso_numeric",
    "countrynumericcode": "iso_numeric",
    "isocode": "iso2",
    "wikidataid": "wikidata",
    "undatacode": "undata",
    "geonamesid": "geonames",
}

ALIAS_PROPERTIES = {
    ALT_NAME_PROPERTY: "alias",
    SHORT_DISPLAY_NAME_PROPERTY: "short_name",
    UN_DATA_LABEL_PROPERTY: "alias",
}

ATTR_PROPERTIES = {
    DESCRIPTION_PROPERTY: "description",
}


def to_geo_entity_type(
    raw_entity_type: str,
    attrs: dict[str, Any] | None = None,
) -> str:
    """Convert a raw Data Commons type into canonical ``geo.<snake_case>``."""
    normalized = raw_entity_type.strip()
    if normalized == PLACE_TYPE_GEO_REGION:
        entity_type = "geo.region"
    elif normalized == "ContinentalUnion":
        entity_type = "geo.continental_union"
    elif normalized == PLACE_TYPE_COUNTRY:
        entity_type = "geo.country"
    elif normalized == PLACE_TYPE_CITY:
        entity_type = "geo.city"
    elif normalized == "Region":
        entity_type = "geo.region"
    elif (direct_level := admin_level_from_raw_type(normalized)) is not None:
        entity_type = f"geo.admin{direct_level}"
    else:
        level = None if attrs is None else attrs.get("admin_level")
        level_text = str(level).strip() if level is not None else ""
        if level_text.isdigit() and normalized not in {
            PLACE_TYPE_COUNTRY,
            PLACE_TYPE_GEO_REGION,
            PLACE_TYPE_CITY,
        }:
            entity_type = f"geo.admin{level_text}"
        elif normalized == PLACE_TYPE_ADMINISTRATIVE_AREA:
            entity_type = "geo.admin1"
        elif normalized == "Organization":
            entity_type = "geo.organization"
        else:
            entity_type = to_prefixed_entity_type(raw_entity_type, prefix="geo")
    return entity_type


def admin_level_from_raw_type(raw_entity_type: str) -> int | None:
    """Extract admin depth from raw Data Commons administrative type labels."""
    normalized = raw_entity_type.strip()
    if not normalized.startswith(PLACE_TYPE_ADMINISTRATIVE_AREA):
        return None
    suffix = normalized.removeprefix(PLACE_TYPE_ADMINISTRATIVE_AREA).strip()
    if not suffix.isdigit():
        return None
    return int(suffix)


def to_name_kind(alias_type: str) -> str:
    """Map source alias types to canonical name kinds."""
    normalized = alias_type.casefold()
    if normalized in {"canonical", "endonym", "exonym"}:
        return normalized
    if normalized in {"abbr", "abbreviation"}:
        return "acronym"
    return "alias"


def normalize_code_system(raw_system: str) -> str:
    """Normalize source code-system names into canonical short keys."""
    lowered = raw_system.casefold().strip()
    return _CODE_SYSTEM_MAPPING.get(lowered, lowered)
