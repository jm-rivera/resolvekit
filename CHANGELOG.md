# Changelog

## 0.1.5 (2026-06-12)

**Fixed.** Typo'd queries no longer abstain on bring-your-own-data packs.
`Resolver.from_records(...)` (the `custom` domain) had a fuzzy *reranker* but
no fuzzy *generator*, so a query with a within-token typo or an extra junk
token — `resolve("Andean Watr Trust")` against "Andean Water Trust" — produced
no candidates and returned NO_MATCH, even though `suggest()` corrected the same
typo. A new store-backed generating fuzzy-retrieval source now matches over the
pack's own names on the fuzzy tier, so these queries resolve (here at
confidence 0.89) the way the bundled geo/org packs already did. It is always on
and automatic: the engine's existing skip guard keeps it free on clean
exact-name queries, a 25k-name cap and a memoized name list bound the cost, and
exact-code and exact-name matches are never displaced. The capability lives in
shared infrastructure, so any programmatically-built pack inherits it.

## 0.1.4 (2026-06-12)

**Fixed.** Two ranking quirks on installs with remote geo data:
`suggest("germ")` returned Germ — an obscure French commune whose full name
happened to match — over Germany; the exact-match lift now requires minimum
prominence on prominence-ranked tiers, while org acronyms ("UN", "NATO")
keep it. And `resolve("Paris")` on bundled-only installs listed Mauritius as
a sub-threshold candidate via the alias "Moris" at edit distance 2; typo
corrections on queries of six characters or fewer now accept a single edit
only. Both eval gates pass, with overall accuracy improving to 0.8638.

## 0.1.3 (2026-06-12)

Disambiguation release: context hints as plain dicts, per-row context in bulk
operations, prominence-based tiebreaking, and ambiguous results that show
their candidates — plus ~30 verified fixes from a systematic stress-test of
the public API surface.

**Context hints as plain dicts.** Every resolution surface — `resolve()`,
`resolve_id()`, `bulk()`, `snap()`, `suggest()`, `parse()`, `parse_bulk()`,
their module-level wrappers, and the pandas/polars accessors — now accepts
`context=` as a plain dict, no import needed:
`resolve("Paris", context={"country": "FR"})`. The `country` key also takes
country names (`"France"`, `"Korea, Rep."`) and resolves them to ISO codes,
raising a did-you-mean error when the name is ambiguous (`"Korea"`) or
unknown. Unknown context keys raise `UnknownContextKeyError` listing the
valid ones (`country`, `entity_types`, `parent_ids`, `languages`,
`attributes`, `as_of`). `ResolutionContext` still works everywhere.

**Per-row context in bulk.** Context dict values may be a column instead of
a scalar: `df["city"].resolvekit.bulk(context={"country": df["iso"]})`
resolves each row under its own country (pandas Series, polars Expr/Series,
or plain list). Work is deduplicated to unique (text, context) pairs, so a
50k-row frame with a handful of countries costs what its unique pairs cost.
Query-cache keys are content-based now, so equal contexts share cache
entries.

**Ambiguous results teach the fix.** An AMBIGUOUS result's repr lists the
top candidates with their containing region (`Springfield, Vermont` /
`Springfield, New Jersey`) and, when the candidates span different
countries, ends with a copy-pasteable `context={'country': ...}` hint. All
refinement hints emit the dict form.

**Prominence-based tiebreaking.** A dominant entity now beats obscure
same-named peers instead of tying: with remote geo data, bare `"Paris"`
resolves to Paris, France over Paris, Texas and Paris, Illinois, and
`"Sudan"` resolves to the country over Sudan, Texas — while genuinely
ambiguous names (`"Springfield"`) stay AMBIGUOUS. City and admin prominence
is derived from Wikidata sitelink counts, with Data Commons population as
the fallback for unlinked entities; the confidence calibrator was retrained
on the full geo tier mix and decision gaps rescaled to match.
World Bank/IMF comma-form country names (`"Korea, Rep."`,
`"Congo, Dem. Rep."`) resolve via bundled aliases.

**`rk.suggest()`.** The typo-tolerant typeahead is now exported at module
level alongside `resolve()` and friends.

**Resolution correctness.** Dotted abbreviations are no longer misclassified
as missing-value markers: `"U.S.A."` resolves to `country/USA` (it previously
resolved to an unrelated org entity) and `"U.K."` to `country/GBR`, while
genuine null markers (`#N/A`, `--`, `.`) still return no match. Mixed-case
inputs (`"fRaNcE"`, `"SUDan"`) resolve like their standard casings.
Zero-padded ISO numeric codes (`"004"`) now resolve, `to="iso_numeric"` emits
the canonical zero-padded form, and the pycountry-style `numeric` alias works
(`entity("France").numeric` → `"250"`). `snap()` accepts free-text candidate
labels as documented, alongside entity IDs. Punctuation-only inputs (`"."`,
`"?"`) return no match instead of an internal error. `EntityRecord.aliases`
no longer leaks the canonical name or duplicates.

**Crashes.** `bulk()` no longer crashes on polars Series input without a
pivot; `output="record"` builds primitive records that `to_polars()` accepts.
`ResolutionResult` pickles cleanly.

**Validation and errors.** Enum-like parameters are validated eagerly with
did-you-mean suggestions instead of silently accepting typos: `on_ambiguous`
(`resolve_id`), `on_missing`/`on_error`/`on_ambiguous` (`bulk`), `default_to`
types (`configure`), `confidence_threshold` and `domain` (`parse`),
`name:` language segments, and `ResolutionContext.country`.
`AmbiguousResolutionError` hints are candidate-aware (no longer suggesting
`entity_types=` when the tied candidates share one type) and `str()` previews
the top candidates. `to=<typo>` errors suggest the closest code system
instead of dumping all of them, and the `domain=`-with-auto-routing error no
longer references internals. `from_records()` reports the offending row and
column for empty name cells.

**Behavior consistency.** `configure()` no longer clears settings that are
omitted from the call; passing `None` explicitly resets a setting to its
default (`cache_dir`, `default_to`). Mutating a returned result's lists no
longer corrupts the query cache. `as_of=` accepts ISO date strings on
`members_of`/`is_member`/`related`/`within`. `bulk()` pandas output preserves
`None` under pandas 3. `available_entity_types()` returns the fine-grained
types that `entity_types=` accepts. BYOD labels containing
NFKC-compatibility characters (`™`, `№`) now round-trip; existing BYOD disk
caches are rebuilt automatically.

**API consistency.** Scalar `resolve()`/`resolve_id()` now coerce numeric
input the same way `bulk()` does (`resolve_id(840)` → `country/USA`; integral
floats like `840.0` from numeric dataframe columns coerce cleanly in both
paths), and non-string types raise the `TypeError` the docstring always
promised — `bool` included. `ResolutionContext(country=...)` accepts ISO
alpha-3 alongside alpha-2 (`"USA"` and `"US"` behave identically). The pandas
and polars accessors no longer convert caller mistakes into all-`None`
columns: parameter-validation errors propagate (polars previously garbled
them through `map_batches`), and `on_error` is exposed with the same
`"raise"` default as `bulk()`. `ResolutionResult.reasons`, `.candidates`,
and `.refinement_hints` are tuples now — the documented frozen contract is
real, not advisory. Commonly raised errors (`UnknownCodeSystemError`,
`UnknownOutputError`, `UnknownDomainError`, `OutputMissingError`,
`DataPackNotAvailableError`, `CrosswalkError`, `ExplainNotAvailableError`,
`NoModulesInstalledError`) are importable from top-level `resolvekit`;
`resolvekit.errors` remains the canonical home.

**Docs.** Corrected the `snap()` candidate guidance and the
`UnknownOutputError`/`UnknownCodeSystemError` reference entries; refreshed
stale confidence figures in the tutorials; documented that code
auto-detection is case-sensitive by design while `from_system` is
case-insensitive.

**Performance.** The SymSpell typo index is now built in a background daemon
thread during `Resolver` construction (default on), so the build cost no longer
lands on the first query that passes the exact-match tiers. Opt out with
`warm=False` on any constructor (`Resolver.auto(warm=False)`,
`Resolver.from_modules(warm=False)`, etc.) to keep construction fully lazy.
`resolvekit.warm()` and `Resolver.warm()` are new synchronous, idempotent,
thread-safe functions that build all lazy indexes and return when they're ready
— for servers or batch jobs that want deterministic readiness. The large-tier
SymSpell index (706k terms, ~6 s to build on remote-data installs) is now
cached as a locally-generated pickle under `<cache-dir>/compiled/` after its
first build (~150 MB, loads in ~1.4 s on subsequent processes), keyed by the
dictionary files and symspellpy version; existing bundled-only installs are
unaffected.

## 0.1.2 (2026-06-11)

**Fixed.** `download()` crashed on a clean install with "Missing package
'tqdm' required for progress bars": pooch's progress bar needs tqdm, which is
not a resolvekit dependency. Downloads now show a progress bar when tqdm is
installed and run silently when it isn't.

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
