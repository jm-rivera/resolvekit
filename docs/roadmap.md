# Roadmap

resolvekit is an offline-first library for resolving messy place and organization strings to canonical entity IDs. It runs with no network call, no API key, and no rate limit: the country tier ships in the wheel, and deeper geographic tiers download on demand from a pinned data release. This is a 0.1 public beta. The resolution surface is stable enough to build on, but the data is still expanding, several documented limits remain, and the version is 0.1.x for a reason — expect API edges to move before 1.0.

Buckets are versions, not dates. Items move between buckets as beta feedback comes in — [issues](https://github.com/jm-rivera/resolvekit/issues) are the right place to push on priorities.

*Last updated alongside the 0.1.4 release (June 2026).*

## Now (0.1)

Resolution and lookup:

- `resolve()` / `resolve_id()` — scalar resolution returning a result or a pivoted value.
- `bulk()` — vectorized batch resolution over list, pandas Series, polars Series, ndarray, or dict, with deduplication and per-row error/ambiguity policies.
- `snap()` — closest match against a caller-supplied candidate list with a confidence floor.
- `entity()` — direct lookup by free text, entity ID, or explicit code (iso2, iso3, numeric, dcid, and arbitrary code kwargs).
- `parse()` / `parse_bulk()` — entity-mention extraction from free text via Aho-Corasick, with offsets and per-span resolution (`resolvekit[parsing]`).
- `Resolver.suggest()` — typo-tolerant typeahead returning ranked suggestions with match class and highlight ranges; fuzzy mode auto-enables on the bundled tiers.

Entity data:

- Geo, bundled in the wheel: countries (239 entities), regions, continents, continental unions.
- Geo, remote on demand: admin1 through admin5 and cities, fetched from the pinned data release.
- Org, all bundled: providers, lenders, political parties, companies, governments, data sources.

Codes and output:

- 50+ country code systems per entity, including ISO 3166-1 alpha-2/alpha-3/numeric, M49, FIPS 10-4, Wikidata QID, DCID, IOC, ITU, UN numeric, and 40+ national-library authority IDs.
- Output pivot grammar: `name`, `name:fr`, `name:zh:Hant`, plus computed properties iso2/iso3/numeric/name/flag/continent/aliases.
- `configure(default_to=)` and `to()` set a resolver-wide or call-scoped output spec with a fallback chain and on-missing policy.
- Bundled country names in 10 languages: en, fr, es, de, ru, ja, it, pt, zh, ar.

Graph and groups:

- `members_of()` / `is_member()` / `known_groups()` — group membership with as-of date support.
- `related()` — forward relation walk (e.g. contained_in) with relation-type and as-of filters.
- `within()` — reverse containment traversal filtered by entity type and as-of.

Bring-your-own-data:

- `Resolver.from_records()` — standalone resolver from a list of dicts, DataFrame, or CSV/JSON.
- `Resolver.augment()` — overlay that links user rows to base entities by code, optionally minting on miss.
- `Crosswalk` and the `IGNORE` sentinel — short-circuit `bulk()` for caller-supplied overrides.

Engineering surface:

- Calibrated confidence on every result (Platt/isotonic calibrators).
- pandas Series accessor and polars Expr namespace (`resolvekit[pandas]`, `resolvekit[polars]`).
- `ResolutionResult.explain()` resolution scorecard; resolver `diagnostics` namespace (inspect/search/cache).
- `extensions.py` custom-pack author surface under a v1 stability guarantee.
- Accuracy (offline, leading all compared offline tools): geo_countries_en 0.793, geo_admin 0.935, geo_cities 0.858, geo_countries_multilingual 0.632. Wheel ~9.5 MB; `Resolver.lite()` country-only path ~50–100 MB RSS.

## Next (0.2.x)

Country-code-system parity with country-converter. resolvekit already covers ISO2/3/numeric, IOC, continent, M49 regions, OECD, UN, EU/EEA/Schengen/Eurozone, G7/8/20, BRICS, Commonwealth, NATO, ASEAN, OPEC, MERCOSUR, AU, G77, World Bank income, OECD.DAC, and UN.LDC/LLDC/SIDS. The remaining coco schemes, grouped for batched data builds:

- Statistical-agency code systems: FAOcode (FAOSTAT), GBDcode (IHME Global Burden of Disease), IEA (v2021 and v2025), DACcode (numeric OECD DAC), ccTLD, GWcode (Gleditsch & Ward), FIFA, GEOnumeric (Eurostat Prodcom), BACI (CEPII), UNIDO — all 1:1 country-to-code maps.
- MRIO/IAM classification systems: EXIOBASE 1/2/3 (plus 3-letter and hybrid variants), WIOD, Eora, MESSAGE, IMAGE, REMIND, CC41, Cecilia2050 — region-aggregation strings widely used in sustainability/LCA work.
- Membership groups: APEC, CIS, and EFTA membership edges (the region entities already exist) plus BASIC and CoE. Also surface the UN-membership join year as a typed attribute; resolvekit already tracks UN membership via date-stamped membership edges, but the join-year scalar is not exposed.
- Continent_7 — surface the 7-continent split as a named output; the North/South America entities already exist, only the labelled pivot is missing.

Multilingual country names:

- Expand CLDR territory names from 10 to 20–30 locales (hi, ko, tr, nl, pl, sv, cs, hu, th, vi, bn, uk, …).
- Add Wikidata non-English alt-labels for countries (de/es/fr/ru/zh/ar) — the largest single lever on the multilingual benchmark score.
- Add ru/zh/ar to the multilingual benchmark — prerequisite for measuring progress on the three unvalidated UN languages.
- Verify and document `to=name:lang` against the 10 bundled languages, and wire input-language hints into scoring.

Highest-leverage deferred items:

- Alias hygiene at data build — drop code-shaped aliases that upstream sources file as English names (ISO 3166-2 strings like `FR-MF`, duplicates of an entity's own ISO/IOC codes; ~4% of bundled country name rows) and re-tag endonyms mislabeled as English (`Moris` for Mauritius). Needs a shared filter at the builder's ingest choke point, with care to keep typed acronyms (`UK`, `USA`) in the `suggest()` surface.
- ISO 3166-3 historic countries — add the 25 missing dissolved states (USSR, East Germany, Zaire, Czechoslovakia, South Yemen, …); the validity schema and as-of filter already exist, so this is data, not engineering. Alpha-4 code lookup follows once the entities land.
- Surface centroid lat/lon as typed fields and a `to=centroid` pivot — the coordinates are already stored on every geo entity.
- `AugmentResult.errors` — populate the list; the on_miss='error' path documents collected errors but never appends to it.

## Later

- Multilingual admin names — GeoNames alternate-name enrichment for admin1/2/3; admin entities already carry GeoNames codes.
- Script and transliteration handling — CJK/Cyrillic/Arabic tokenization for search indexes so native-script inputs match.
- Bundled minimal city tier — capitals and major cities so "Paris"/"Tokyo"/"Lagos" resolve without the 154 MB cities download.
- `suggest()` cities/admin fuzzy matching — currently exact-prefix only for cities and admin2–5; gated behind the same city-prominence data work.
- An `include_obsolete` surface and a documented historical-country corpus — make the existing validity/as-of capability discoverable as a parameter.
- Cross-namespace entity aliases — let one entity resolve under wikidataId/, geoId/, country/, nuts/ namespaces.
- Deeper org packs — international NGOs and org prominence data for suggest ranking; the org pack is thin relative to geo.
- Concordance/correspondence builder — scheme-to-scheme translation analogous to coco's correspondence dicts; relevant once the MRIO/IAM codes exist.

## Exploring

- List-to-list `match()` — correspondence between two arbitrary string lists; `snap()` and `resolve()` cover the single-value case, but demand for the list-alignment form is unvalidated.
- Reverse geocoding — coords-to-entity via a spatial index over stored centroids; fits the offline lane, but unproven that beta users need it over name/code resolution.
- Native polars plugin expression — a Rust extension expression for lazy/streaming plans instead of the current Python-level `bulk()` wrap.
- Memory-bounded streaming `bulk()` — chunk-aware resolution for dense-cardinality frames in constrained environments.
- OpenRefine Reconciliation API endpoint — an HTTP wrapper implementing the W3C reconciliation spec; a how-to exists, but shipping a service is a scope question.
- Debian iso-codes translations as a supplementary alias source — overlaps CLDR and carries LGPL-2.1 notice obligations that need clearing first.
- BYOD fuzzy name linking — an opt-in fuzzy `link_names` mode for augment; deferred over mislink risk, awaiting real demand.

## Non-goals

- Street-address parsing — libpostal's domain; needs a ~2 GB statistical model and house-number/postal data resolvekit does not carry.
- Online geocoding — inverts the offline-first contract of determinism, privacy, and no-network resolution.
- Probabilistic record linkage / deduplication — splink and dedupe solve pairwise table matching; resolvekit does single-string lookup against a fixed authority.
- Sanctions / PEP / watchlist matching — OpenSanctions's domain; different data, far higher false-match cost, and regulatory exposure.
- POI / physical-place keys — Placekey-style retail-location identity is online and street-level; resolvekit stops at city granularity.
- A shell CLI — resolvekit is a library; shell-style country conversion is country-converter's lane.
- ISO 639-3 languages, ISO 4217 currencies, ISO 15924 scripts as entities — each needs a new non-geo domain pack; orthogonal to the place+org mission for v1.
- Per-country currency codes and FX rates — the static ISO 4217 code is sourceable but out of scope absent demand; exchange-rate values require a runtime network call, conflicting with offline-first.
