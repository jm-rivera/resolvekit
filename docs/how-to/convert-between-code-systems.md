# How to convert between code systems

Convert country names to ISO codes, flags, Data Commons IDs, and back — using
`rk.resolve()`, `rk.bulk()`, and `rk.entity()`.

## Quick reference table

| Input | `from_system` | `to` | Output |
|-------|---------------|------|--------|
| `"Germany"` | *(auto)* | `"iso3"` | `"DEU"` |
| `"United States"` | *(auto)* | `"iso3"` | `"USA"` |
| `"Brasil"` | *(auto)* | `"iso3"` | `"BRA"` |
| `"DE"` | `"iso2"` | `"name"` | `"Germany"` |
| `"JP"` | `"iso2"` | `"name"` | `"Japan"` |
| `"Japan"` | *(auto)* | `"flag"` | `"🇯🇵"` |
| `"Tanzania"` | *(auto)* | `"dcid"` | `"country/TZA"` |
| *(default_to="iso3")* | *(auto)* | *(omitted)* | `"ESP"` |
| `"France"` | *(auto)* | `"name:fr"` | `"France"` |
| `"Spain"` | *(auto)* | `"name:es"` | `"España"` |
| `default_to=["iso3","name"]` | *(chain)* | *(omitted)* | first non-missing value |

## Single values

`rk.resolve(text, to=...)` returns the pivot value directly when `to` is set.

```python
import resolvekit as rk

rk.resolve("Germany", to="iso3")   # "DEU"
rk.resolve("Germany", to="iso2")   # "DE"
rk.resolve("Germany", to="flag")   # "🇩🇪"
rk.resolve("Tanzania", to="dcid")  # "country/TZA"
```

The `to` parameter accepts any code system the loaded packs carry — the same open-ended set as `from_system`. Common values: `"iso3"`, `"iso2"`, `"name"`, `"flag"`, `"aliases"`, `"dcid"`, `"iso_numeric"`, `"wikidata"`. Pass an unknown one and it raises `UnknownCodeSystemError`. (The same typo in `configure(default_to=...)` or `rk.to(...)` raises the sibling `UnknownOutputError` instead — those paths validate the whole output spec, not just a code system. Catch `ResolverError` to cover both.)

`"aliases"` returns a list of multilingual names:

```python
rk.resolve("Germany", to="aliases")
# ['Alemanha', 'Alemania', 'Allemagne', 'Bundesrepublik',
#  'Bundesrepublik Deutschland', 'Deutschland', ...]
```

## Forcing the input system

By default resolvekit auto-detects whether the input is a name, ISO code, or
other identifier. When your input column contains codes that could be ambiguous
(two-letter codes especially), use `from_system` to pin the interpretation.

Auto-detection is deliberately case-sensitive for codes: `"US"` resolves as an
ISO code, but `"us"` does not — lowercase two- and three-letter strings are
indistinguishable from ordinary words (`"in"`, `"it"`, `"no"`), so treating
them as codes would mis-resolve real text. Once you declare intent with
`from_system`, case no longer matters: `from_system="iso2"` accepts `"us"`,
`"Us"`, and `"US"` alike.

```python
rk.resolve("DE", from_system="iso2", to="iso3")  # "DEU"
rk.resolve("DE", from_system="iso2", to="name")  # "Germany"
rk.resolve("US", from_system="iso2", to="iso3")  # "USA"

# Start from a Data Commons ID
rk.resolve("country/DEU", from_system="dcid", to="name")  # "Germany"
```

`from_system` accepts **any code system the loaded packs carry**, not a fixed
list — pass an unknown one and it raises `UnknownCodeSystemError`. The ones
you'll reach for are `"iso2"`, `"iso3"`, `"iso_numeric"`, `"dcid"`, and
`"wikidata"`. The data also carries authority IDs like `"fips104"`,
`"ioccountrycode"`, `"gndid"`, `"viafid"`, and `"osmrelationid"`. For the full
set on your install (52 systems with the default geo + org packs), call
`rk.default().code_systems()`.

## Converting a whole column

`rk.bulk()` takes a list, pandas Series, or polars Series and returns the same
shape. Unresolved values come back as `None`.

```python
import pandas as pd
import resolvekit as rk

country_names = pd.Series(["Germany", "United States", "Cote dIvoire", "Brasil", "South Korea"])
rk.bulk(values=country_names, to="iso3")
# 0    DEU
# 1    USA
# 2    CIV
# 3    BRA
# 4    KOR
# dtype: object
```

Converting a column of ISO 2-letter codes:

```python
iso2_codes = pd.Series(["US", "DE", "FR", "JP", "GB"])
rk.bulk(values=iso2_codes, from_system="iso2", to="iso3")
# 0    USA
# 1    DEU
# 2    FRA
# 3    JPN
# 4    GBR
# dtype: object
```

### Handling unresolved rows

By default, unresolved rows produce `None`. Use `not_found` to replace them
with a sentinel string instead:

```python
rk.bulk(values=pd.Series(["Germany", "zzznotacountry", "France"]), to="iso3")
# 0     DEU
# 1    None
# 2     FRA
# dtype: object

rk.bulk(values=pd.Series(["Germany", "zzznotacountry", "France"]), to="iso3", not_found="UNKNOWN")
# 0        DEU
# 1    UNKNOWN
# 2        FRA
# dtype: object
```

## Joining against Data Commons

The `"dcid"` pivot produces the Data Commons entity ID, which is the canonical
key for joining against Data Commons datasets.

```python
rk.resolve("Tanzania", to="dcid")  # "country/TZA"
rk.resolve("France", to="dcid")    # "country/FRA"
```

For countries, the `dcid` has the form `country/<ISO3>`. Use `rk.bulk()` to
create a join key column:

```python
df["dcid"] = rk.bulk(values=df["country_name"], to="dcid")
```

## Getting a numeric code

The ISO numeric code is the `iso_numeric` system. Pivot to it like any other code
— `to="numeric"` returns `None` only because `"numeric"` isn't a code system name:

```python
# ✅ Use the system's real name
rk.resolve("Germany", to="iso_numeric")  # "276"

# ❌ "numeric" is not a code system — returns None
rk.resolve("Germany", to="numeric")  # None
```

!!! note
    `codes_dict` contains every known code for an entity — ISO, FIPS, Wikidata,
    Data Commons, and many library-specific IDs. For Germany it currently
    carries over 40 entries. Use `rk.entity(name).codes_dict` to inspect what's
    available.

## Set a default output system

Pass `default_to=` once at construction so every subsequent call returns that
system without a per-call `to=`:

```python
import resolvekit as rk

resolver = rk.Resolver.auto(default_to="iso3")
resolver.resolve("Spain")    # "ESP"
resolver.resolve("France")   # "FRA"
resolver.resolve("Japan")    # "JPN"
```

For module-level code (notebooks, scripts), use `rk.configure()` instead:

```python
import resolvekit as rk

rk.configure(default_to="iso3")
rk.resolve("Spain")    # "ESP"
rk.resolve("France")   # "FRA"
```

`configure()` discards the cached singleton and rebuilds it with the new setting
on the next call.

!!! note
    `resolve_id` always returns the DCID-style entity ID regardless of any
    configured `default_to`. `rk.resolve_id("Spain")` → `"country/ESP"`, not
    `"ESP"`.

## Bind a view without global state

`rk.to()` returns an `OutputView` — a lightweight wrapper around the default
resolver that always applies one fixed output spec. Calls through the view don't
affect any global setting:

```python
import resolvekit as rk

iso3 = rk.to("iso3")
iso3.resolve("Spain")   # "ESP"
iso3.resolve("France")  # "FRA"

import pandas as pd
names = pd.Series(["Spain", "France", "Germany"])
iso3.bulk(values=names)
# 0    ESP
# 1    FRA
# 2    DEU
# dtype: object
```

On a custom `Resolver`, use `resolver.to(...)` directly:

```python
resolver = rk.Resolver.auto()
iso3 = resolver.to("iso3")
iso3.resolve("Japan")  # "JPN"
```

`resolve_id` on an `OutputView` returns the entity ID, not the pivoted value:

```python
iso3.resolve_id("Spain")   # "country/ESP"
iso3.resolve("Spain")      # "ESP"
```

## Fall back when a code is missing

Not every entity has every code. Org entities lack ISO codes entirely. Pass a
list to `default_to` to walk a fallback chain — resolvekit returns the first
value that exists:

```python
resolver = rk.Resolver.auto(default_to=["iso3", "name"])

resolver.resolve("France")   # "FRA"  (iso3 present — first link wins)
resolver.resolve("UNICEF")   # "United Nations Children's Fund (UNICEF)"  (no iso3 — falls back to name)
```

Or with `configure()` for module-level use:

```python
rk.configure(default_to=["iso3", "name"])
rk.resolve("UNICEF")   # "United Nations Children's Fund (UNICEF)"
```

Control what happens when the whole chain misses with `on_missing`:

| `on_missing` | scalar `resolve` / `snap` | `bulk` |
|---|---|---|
| `"auto"` (default) | raises `OutputMissingError` | `None` per row + `UserWarning` |
| `"raise"` | raises `OutputMissingError` | raises on first miss |
| `"null"` | returns `None` | `None` per row, no warning |

```python
# Suppress the warning for bulk — get None silently on misses
resolver = rk.Resolver.auto(default_to="iso3", on_missing="null")
```

!!! warning "Heads up"
    `"auto"` raises for scalar `resolve()` and `snap()`, but returns `None` with
    a `UserWarning` for `bulk()`. If your bulk output has an unexpected empty
    column, check for a `UserWarning` from the output chain.

## Output names in a language

`"name"` returns the canonical English display name. Append a language code to
select a localized variant:

```python
import resolvekit as rk

rk.resolve("Germany", to="name")     # "Germany"  (canonical)
rk.resolve("Germany", to="name:fr")  # "Allemagne"
rk.resolve("Spain", to="name:es")    # "España"
rk.resolve("Japan", to="name:ja")    # "日本"
rk.resolve("China", to="name:zh")    # "中国"
rk.resolve("Brazil", to="name:pt")   # "Brasil"
```

Ten languages are present in the bundled data: `en`, `fr`, `es`, `de`, `ru`,
`ja`, `it`, `pt`, `zh`, `ar`.

The grammar also accepts `name:<kind>` (`canonical`, `alias`, `endonym`,
`exonym`, `acronym`) for packs that carry those name kinds; the bundled packs
currently provide canonical names, per-language names, and aliases.

The name grammar works on per-call `to=` and `EntityRecord.to()` as well as
`default_to=` and `rk.to()`:

```python
rk.resolve("Germany", to="name:fr")   # "Allemagne"  (per-call)

entity = rk.entity("Germany")
entity.to("name:fr")                  # "Allemagne"  (entity-level)
```

When an entity lacks the requested language variant, these surfaces return
`None` (a quiet miss). To provide a fallback, use `default_to=` or `rk.to()`
with a chain — per-call `to=` accepts only a single target:

```python
# French name if available, canonical English otherwise
resolver = rk.Resolver.auto(default_to=["name:fr", "name"])
resolver.resolve("Germany")  # "Allemagne"  (French name present)
resolver.resolve("ASEAN")    # "Association of Southeast Asian Nations"  (no French name — falls back)
```

## As of v0.1

The `to` pivots shown here are available on all bundled modules (`geo.countries`
and the rest of the bundled pack). Remote packs (admin-level geo, cities) expose
the same API once downloaded.

---

## Next

- If your input is free text rather than clean names or codes, start with [Extract entities from text](extract-entities-from-text.md) — `rk.parse()` links mentions to the same code systems shown here.
- [API reference](../reference/api.md) — full parameter listing for
  `resolve()`, `bulk()`, and `entity()`.
- [Explanation: entities and modules](../explanation/entities-and-modules.md) —
  what an entity ID is, how modules are structured, and why the code systems
  work the way they do.
