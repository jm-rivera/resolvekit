# Changelog

## 0.1.1 (2026-06-11)

**Fixed.** Partial remote caches no longer error: after downloading a single
remote tier (e.g. `download("geo.admin1")`), `Resolver.auto()` raised
`MissingModuleDependencyError` demanding sibling tiers, and explicitly
requesting one tier via `module_ids` transitively queued every declared
sibling (a ~796 MB download). Declared dependencies on remote packs that are
not in the local cache are now skipped during loading and validation; bundled
and cached dependencies are still enforced.

**Docs.** Corrected the OECD DAC entry in NOTICE.md: OECD distributes its
content under CC BY 4.0 (attribution, commercial use permitted) since July
2024 — the previous wording incorrectly claimed a non-commercial restriction.
Also documented the DAC contribution to the org entity store and updated the
upstream URL.

## 0.1.0 (2026-06-11)

First public beta release.

**Resolution surface.** `resolve()` / `resolve_id()` scalar resolution, `bulk()` vectorized batch resolution (list, pandas, polars, ndarray, dict), `snap()` closest-match against a candidate list, `entity()` direct lookup by text, ID, or code, `parse()` / `parse_bulk()` entity-mention extraction (`resolvekit[parsing]`), and `Resolver.suggest()` typo-tolerant typeahead. Calibrated confidence on every result, with `ResolutionResult.explain()` scorecards.

**Entity data.** Geo and org domains, 16 modules total. Bundled in the wheel: countries, regions, continents, continental unions, and all six org modules (providers, lenders, political parties, companies, governments, data sources). Remote, fetched on first use from the pinned GitHub data release ([data-v2026.06](https://github.com/jm-rivera/resolvekit/releases/tag/data-v2026.06)): admin1 through admin5 and cities. Asset integrity is verified against SHA-256 checksums recorded in the shipped manifest.

**Codes and output.** 50+ country code systems (ISO 3166-1 alpha-2/alpha-3/numeric, M49, FIPS 10-4, Wikidata QID, DCID, IOC, ITU, and national-library authority IDs, among others), output pivot grammar (`to="name:fr"`, `iso3`, `continent`, ...), `configure(default_to=)` / `to()` output specs, and bundled country names in 10 languages.

**Graph and groups.** `members_of()` / `is_member()` / `known_groups()` with as-of date support, `related()` forward relation walks, `within()` reverse containment traversal.

**Bring your own data.** `Resolver.from_records()` standalone resolvers, `Resolver.augment()` overlays, `Crosswalk` and the `IGNORE` sentinel for caller-supplied overrides.

**Integrations.** pandas Series accessor (`resolvekit[pandas]`), polars Expr namespace (`resolvekit[polars]`).

Requires Python >= 3.12. Runtime dependencies: packaging, pooch, pydantic, rapidfuzz, symspellpy.

**Known limits.** Multilingual coverage is strongest in en/es/fr/de; `suggest()` fuzzy mode covers bundled tiers only (cities and admin2–5 are exact-prefix for now). See the [roadmap](https://jm-rivera.github.io/resolvekit/roadmap/) for what's next.
