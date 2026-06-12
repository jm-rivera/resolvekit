# How to build typeahead autocomplete

Turn a partial query into a ranked list of entity suggestions with
`suggest()` — exact, prefix, infix, and typo-tolerant matches, ready to
wire into a search box.

`suggest()` is available as `rk.suggest()` at module level (added in v0.1.3)
and as `Resolver.suggest()` on any resolver instance. For scripts and notebooks,
the module-level form is the shortest path:

```python
import resolvekit as rk

for s in rk.suggest("germ", top_k=3):
    print(s.canonical_name, s.entity_id)
# Germany       country/DEU
# German Dem Rep  German_Dem_Rep
```

For production services that need fine-grained control (a specific module set,
`warm=False` for lazy startup, custom `Resolver.lite()` footprint), build a
resolver and call suggest on it directly:

```python
from resolvekit import Resolver

r = Resolver.lite()   # country-level geo; or Resolver.auto() for geo + org
```

`suggest()` bypasses the resolve pipeline and the query cache by design, so
calling it on every keystroke is safe — it never raises a verdict and never
caches per-prefix state. Empty, whitespace-only, or below-floor prefixes return
`[]`.

## Quick reference table

`rk.suggest()` and `r.suggest()` accept the same parameters:

| You pass | You get back |
|---|---|
| `rk.suggest("unit")` | up to 10 `SuggestionResult`, ranked best-first |
| `rk.suggest("germny")` | typo-tolerant fuzzy matches (Germany, …) |
| `rk.suggest("united", entity_type="geo.country")` | countries only |
| `rk.suggest("united", domain="geo")` | geo packs only (simple domain name) |
| `rk.suggest("germ", to="iso3")` | each suggestion's `display` rendered as ISO-3 |
| `rk.suggest("germny", fuzzy="never")` | prefix/infix only, no fuzzy |
| `rk.suggest("")` | `[]` |

## A basic call

`suggest()` returns a `list[SuggestionResult]`, sorted best-first, capped at
`top_k` (default 10).

```python
from resolvekit import Resolver

r = Resolver.lite()
for s in r.suggest("unit", top_k=5):
    print(s.canonical_name, s.entity_id, s.match_class.value)
# United States   country/USA   exact_prefix
# Mexico          country/MEX   exact_prefix
# United Kingdom  country/GBR   exact_prefix
# Venezuela       country/VEN   exact_prefix
# Tanzania        country/TZA   exact_prefix
```

Mexico, Venezuela, and Tanzania match because one of their aliases starts with
`"unit"` ("United Mexican States", "United Republic of Tanzania", …). The
`match_class` reflects the matched name, which isn't always the
`canonical_name` you display.

## Tolerate typos

With `fuzzy="auto"` (the default), `suggest()` runs fuzzy matching on the
bundled tiers — countries, regions, continental unions, and orgs — where the
name pool is small enough to stay fast. A misspelled prefix still surfaces the
right entity:

```python
for s in r.suggest("germny", top_k=3):
    print(s.canonical_name, s.match_class.value, s.fuzzy_score)
# Germany   fuzzy   83.33333333333334
# Greece    fuzzy   80.0
# Guernsey  fuzzy   72.72727272727273
```

`fuzzy_score` is the raw RapidFuzz `partial_ratio` (0–100), set only on fuzzy
matches. It's a similarity score, not a calibrated confidence — don't threshold
on it the way you would on `ResolutionResult.confidence`.

Force or suppress fuzzy with the `fuzzy` argument:

```python
r.suggest("germny", fuzzy="never")   # prefix/infix only
# []
```

!!! info "Why"
    `"auto"` runs fuzzy only where it pays off: tiers with at most 25,000
    eligible names, excluding `geo.city` and `geo.admin2`–`geo.admin5`. Those
    denylisted tiers still get exact and prefix matching — just not the
    brute-force fuzzy pass, which would blow the per-keystroke latency budget.
    Pass `fuzzy="always"` to override the gate when you've accepted the cost.

## Filter by type or domain

Scope the candidate pool with `entity_type` (a type prefix) or `domain` (a
simple pack name). Use `entity_type` to return countries only:

```python
r = Resolver.auto()
for s in r.suggest("united", top_k=3, entity_type="geo.country"):
    print(s.canonical_name, s.entity_type)
# United States   geo.country
# Mexico          geo.country
# United Kingdom  geo.country
```

`domain` takes a simple name like `"geo"` or `"org"`. A dotted value is a type,
not a domain, so it's rejected:

```python
# ✅ simple domain name
r.suggest("united", domain="geo")

# ❌ dotted value — raises ValueError pointing you at entity_type=
r.suggest("united", domain="geo.country")
# ValueError: Domain names must be simple strings (e.g., 'geo'), not dotted...
```

## Render the display with `to=`

By default each `SuggestionResult.display` is the `canonical_name`. Pass `to=`
to render it as a code or name variant instead — same grammar as
`resolve(to=...)`:

```python
for s in r.suggest("germ", top_k=2, entity_type="geo.country", to="iso3"):
    print(s.canonical_name, "->", s.display)
# Germany   -> DEU

for s in r.suggest("germ", top_k=2, entity_type="geo.country", to="name:fr"):
    print(s.canonical_name, "->", s.display)
# Germany   -> Allemagne
```

When an entity has no value for the requested output, `display` is `None` — the
miss is coerced to null, never raised, even on a resolver built with
`on_missing="raise"`. An unknown code system in `to=` raises `ValueError`
(`UnknownOutputError`) up front.

## Read match_class and ranking_quality

`match_class` tells you how the candidate was found. The values, best-first:

| `match_class` | Meaning |
|---|---|
| `exact_prefix` | the display/name starts with the query |
| `token_prefix` | a word inside the name starts with the query |
| `infix` | the query appears mid-name |
| `fuzzy` | a RapidFuzz near-match (typo tolerance) |

Results are sorted by a cascade — match class first, then whole-name matches
(the query equals the name in full), then fewer typos, then more-prominent
entities where the tier carries prominence, then shorter names. So an exact
prefix always outranks a fuzzy hit, and an entity whose complete name you typed
outranks one that merely starts with the same letters.

`ranking_quality` is an honesty hint about that ordering. It's `"ranked"` for
tiers that carry prominence data — countries and the region tiers (subregions,
regions, and continental unions) — and `"unranked"` otherwise (continents,
organizations, and the admin/city tiers), where the order is match-class plus
alphabetical. It's tier-based, not per-candidate: a country with no prominence
value still reports `"ranked"`.

```python
# Region tiers are prominence-ranked by their member countries:
for s in r.suggest("west", top_k=3, entity_type="geo.subregion"):
    print(f"{s.canonical_name:16} {s.ranking_quality}")
# Western Asia     ranked
# Western Africa   ranked
# Western Europe   ranked
```

## Whole-name and acronym matches rank first

When the query matches an entity's complete name — common for acronyms and short
codes — that entity is lifted to the top of its match class, ahead of
more-prominent entities that merely start with the same letters. Typing an
organization's acronym surfaces it directly:

```python
r.suggest("NATO", top_k=1)[0].canonical_name
# 'North Atlantic Treaty Organization'

r.suggest("EU", top_k=1)[0].canonical_name
# 'European Union'
```

The same rule is why `suggest("niger")` returns Niger — the exact name — ahead
of the more-populous Nigeria, which only starts with those letters.

## Highlight the matched span

`highlight_ranges` gives the character span of the query inside `display`, ready
to bold in a UI. Offsets are Unicode **code-point** offsets, end-exclusive, into
the `display` string:

```python
for s in r.suggest("new", top_k=4, entity_type="geo.country"):
    for start, end in s.highlight_ranges:
        print(f"{s.display!r:20} match {s.display[start:end]!r} at [{start}:{end}]")
    if not s.highlight_ranges:
        print(f"{s.display!r:20} (no span — matched on an alias)")
# 'Australia'          (no span — matched on an alias)
# 'New Zealand'        match 'New' at [0:3]
# 'Papua New Guinea'   match 'New' at [6:9]
# 'New Caledonia'      match 'New' at [0:3]
```

Two cases return an empty list: fuzzy matches (no reliable literal span) and
matches where the query hit an alias rather than the rendered `display`
(Australia matches "new" through an alias, but "new" isn't in "Australia").

!!! warning "Heads up"
    `highlight_ranges` uses Unicode code-point offsets, not UTF-16. JavaScript
    strings are UTF-16, so a span past a non-BMP character (an emoji, some CJK
    extensions) lands in the wrong place if you index directly. Convert
    code-point offsets to UTF-16 before slicing in the browser.

## Below-floor prefixes return an empty list

`suggest()` never raises for a bad prefix. Empty and whitespace-only inputs come
back as `[]`:

```python
r.suggest("")      # []
r.suggest("   ")   # []
```

Handle the empty list as "no suggestions yet" — there's no status to check and
no exception to catch.

## Next

- [`Resolver.suggest()` reference](../reference/resolver.md#resolversuggest) — every parameter, the clamping rules, and the full `SuggestionResult` field list.
- [Convert between code systems](convert-between-code-systems.md) — the `to=` grammar shown here in full, including name kinds and fallback chains.
