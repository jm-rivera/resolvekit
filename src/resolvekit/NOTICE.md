# Data Notices and Attributions

resolvekit bundles data derived from the following upstream sources. Where a
license requires attribution, that attribution is given below.

## GeoNames

- **Contributes:** place names, alternate names, and geographic hierarchy data
  used in the geo entity store (countries, admin divisions, cities).
- **Upstream:** https://www.geonames.org/ / https://download.geonames.org/export/dump/
- **License:** Creative Commons Attribution 4.0 International (CC BY 4.0)
  https://creativecommons.org/licenses/by/4.0/
- **Modifications:** data was extracted, filtered, normalized, and repackaged
  into SQLite.
- **Attribution required:** GeoNames data is used under CC BY 4.0. GeoNames is
  a trademark of GeoNames.

## Data Commons (Google)

- **Contributes:** canonical entity identifiers (`geoId/`, `country/`,
  `wikidataId/`, etc.) and entity metadata for geo and organisation entities.
- **Upstream:** https://datacommons.org/
- **License:** Creative Commons Attribution 4.0 International (CC BY 4.0)
  https://creativecommons.org/licenses/by/4.0/
- **Modifications:** data was extracted, filtered, normalized, and repackaged
  into SQLite.

## Wikidata

- **Contributes:** labels, aliases, and entity relationships for geo and
  organisation entities.
- **Upstream:** https://www.wikidata.org/
- **License:** Creative Commons CC0 1.0 Universal (public domain dedication)
  https://creativecommons.org/publicdomain/zero/1.0/

## Unicode CLDR (Common Locale Data Repository)

- **Contributes:** canonical country names and locale-specific display names
  across languages used in the entity store and resolver.
- **Upstream:** https://cldr.unicode.org/ / https://github.com/unicode-org/cldr-json
- **License:** Unicode License (permissive)
  https://www.unicode.org/license.txt

## OECD DAC (Development Assistance Committee)

- **Contributes:** DAC country codes and recipient classifications used in the
  geo entity store.
- **Upstream:** https://www.oecd.org/dac/financing-sustainable-development/development-finance-standards/dacandcrscodelists.htm
- **License:** OECD terms of use — data is freely available for non-commercial
  and research use with attribution.
  https://www.oecd.org/termsandconditions/

## HDX Python Country / UN M49

- **Contributes:** a small set of UN M49 official short-form country names in
  Spanish and French (e.g. "Botswana", "Bolivia (Estado Plurinacional de)")
  that are not present in Wikidata or CLDR. These are the lines marked
  `# UN-OCHA M49` in `builder/data/formal_names.yaml`; all other multilingual
  aliases are sourced from Wikidata (CC0) or CLDR.
- **Upstream:** https://github.com/OCHA-DAP/hdx-python-country (UN M49 standard,
  https://unstats.un.org/unsd/methodology/m49/)
- **License:** hdx-python-country library is MIT-licensed; the underlying M49
  country-name data is published by the UN Statistics Division.

## pycountry / Debian iso-codes

- **Contributes:** ISO 3166-1 and ISO 4217 code definitions used at BUILD time
  to validate and normalize country codes and currency codes.
- **Upstream:** https://github.com/flyingcircusio/pycountry (wraps Debian iso-codes,
  https://salsa.debian.org/iso-codes-team/iso-codes)
- **License:** GNU Lesser General Public License v2.1 (LGPL-2.1)
  https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html
- **Note:** pycountry and iso-codes are used at build time only and are not
  redistributed in the wheel data.
