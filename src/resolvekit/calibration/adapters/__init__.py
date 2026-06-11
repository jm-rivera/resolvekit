"""Calibration data source adapters.

Each adapter is a kwargs-only free function returning ``list[LabeledExample]``
labeled training pairs read from an entity store already built by
``resolvekit.builder``.
"""

from resolvekit.calibration.adapters.cldr import cldr_generate_geo_pairs
from resolvekit.calibration.adapters.geonames import geonames_generate_geo_pairs
from resolvekit.calibration.adapters.multilingual_names import (
    EXTENDED_LANGUAGES,
    UN_OFFICIAL_LANGUAGES,
    generate_name_rows,
    multilingual_generate_geo_pairs,
)
from resolvekit.calibration.adapters.synthetic import (
    synthetic_generate_geo_pairs,
    synthetic_generate_org_pairs,
)
from resolvekit.calibration.adapters.wikidata import (
    wikidata_generate_geo_pairs,
    wikidata_generate_org_pairs,
)

__all__ = [
    "EXTENDED_LANGUAGES",
    "UN_OFFICIAL_LANGUAGES",
    "cldr_generate_geo_pairs",
    "generate_name_rows",
    "geonames_generate_geo_pairs",
    "multilingual_generate_geo_pairs",
    "synthetic_generate_geo_pairs",
    "synthetic_generate_org_pairs",
    "wikidata_generate_geo_pairs",
    "wikidata_generate_org_pairs",
]
