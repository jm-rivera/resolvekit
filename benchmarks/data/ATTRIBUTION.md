# Benchmark Data Attribution

The Parquet files in this directory combine content from the following upstream
sources. Each row's `source` field identifies the origin.

## Upstream sources

### CLDR (Common Locale Data Repository) 46.0.0

- Feeds: `geo_countries_en`, `geo_countries_multilingual`
- Upstream: https://github.com/unicode-org/cldr-json (tag `46.0.0`)
- License: Unicode License (permissive; see
  https://www.unicode.org/license.txt)
- Provides canonical country names in `en`, `es`, `fr`, `de`.

### GeoNames alternateNames

- Feeds: `geo_countries_en`
- Upstream: https://download.geonames.org/export/dump/alternateNames.zip
  (and `countryInfo.txt`)
- License: Creative Commons Attribution 4.0 (CC BY 4.0).
  Attribution required: https://creativecommons.org/licenses/by/4.0/
- Provides country-level aliases and short forms, filtered to `en`.

### Wikidata SPARQL

- Feeds: `geo_countries_en`, `geo_countries_multilingual`
- Upstream: https://query.wikidata.org/sparql
- License: Creative Commons CC0 1.0 (public domain dedication)
- Provides labels and altLabels for country entities
  (`Q6256`, `Q3624078`, `Q10864048`, `Q515`).

### Synthetic (Gecko-generated)

- Feeds: `geo_countries_en`
- Tooling: https://pypi.org/project/gecko-syndata/ 0.6.4
- Derivative: perturbations applied to canonical names already in the resolvekit
  entity store (sourced from CLDR, Wikidata, and Data Commons).
- License: same as the underlying names the perturbations derive from.

### Curated (ambiguous, no_match)

- Feeds: `ambiguous`, `no_match`
- Hand-authored by the resolvekit maintainers.
- License: public domain (ours to release).

## Stretch datasets

`geo_admin` and `geo_cities` are populated from the shared entity store when
available. Populating them requires either the corresponding `geo.admin*` /
`geo.cities` datapacks to be downloaded locally. See `provenance.json` for
per-dataset build status.
