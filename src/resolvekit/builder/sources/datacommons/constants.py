"""Shared constants for Data Commons source adapters."""

from __future__ import annotations

DATACOMMONS_SOURCE = "datacommons"
PUBLIC_DC_INSTANCE = "datacommons.org"
DEFAULT_DC_INSTANCE = "datacommons.one.org"
DEFAULT_CHUNK_SIZE = 1000
# Concurrent in-flight HTTP requests against a single instance. Kept low because
# the public Data Commons instances are fronted by a WAF that returns HTTP 429
# to bursty clients; pair with the 429-aware backoff in client._call_limited.
DEFAULT_MAX_CONCURRENT_REQUESTS = 4
DEFAULT_LANGUAGE = "en"
DEFAULT_ADAPTER_LANGUAGES: tuple[str, ...] = ("es", "fr", "de")
CANONICAL_ALIAS_TYPE = "canonical"
ALIAS_TYPE_ALIAS = "alias"
NODE_DCID_ATTR = "dcid"
NODE_VALUE_ATTR = "value"
NODE_PROVENANCE_ATTR = "provenanceId"

# Shared payload keys used by dc_api modules to build raw chunk dicts.
CODE_SYSTEM_KEY = "code_system"
CODE_VALUE_KEY = "code_value"
SOURCE_KEY = "source"
ALIAS_TEXT_KEY = "alias_text"
ALIAS_TYPE_KEY = "alias_type"
LANGUAGE_KEY = "language"

FETCH_RAW_MAX_WORKERS = 6

# Shared Data Commons schema property names used across domains.
SUBCLASS_OF_PROPERTY = "subClassOf"
TYPE_OF_PROPERTY = "typeOf"
ALT_NAME_PROPERTY = "alternateName"
SHORT_DISPLAY_NAME_PROPERTY = "shortDisplayName"
DESCRIPTION_PROPERTY = "description"
