# How to clean a country column in a DataFrame

Turn a messy country column into canonical ISO codes or entity IDs in one call. Polars works identically — swap `pd.Series` for `pl.Series` and the rest is the same.

## Before you start

- `uv add 'resolvekit[pandas]'` / `pip install 'resolvekit[pandas]'` (or `resolvekit[polars]` for Polars)
- Bundled geo data ships in the wheel — no download needed for country-level resolution

## The result

Given this input:

| # | country        |
|---|----------------|
| 0 | United States  |
| 1 | Cote dIvoire   |
| 2 | Brasil         |
| 3 | Germany        |
| 4 | n/a            |

`rk.bulk` produces:

| # | country        | iso3 |
|---|----------------|------|
| 0 | United States  | USA  |
| 1 | Cote dIvoire   | CIV  |
| 2 | Brasil         | BRA  |
| 3 | Germany        | DEU  |
| 4 | n/a            | None |

`n/a` hits the sentinel blocklist and returns `None` without touching the resolution pipeline. Typo variants like `Brasil` and diacritic-stripped forms like `Cote dIvoire` resolve through fuzzy matching.

## The recipe

```python
import pandas as pd
import resolvekit as rk

df = pd.DataFrame({
    "country": ["United States", "Cote dIvoire", "Brasil", "Germany", "n/a"]
})

df["iso3"] = rk.bulk(values=df["country"], to="iso3")
```

`to="iso3"` returns a `pd.Series` in the same order as the input, with `None` for any row that didn't resolve. Other valid pivots: `"iso2"`, `"name"`, `"flag"`, `"dcid"`, `"aliases"`.

## Use `bulk`, not `apply`

Avoid `.apply` for country columns:

```python
# ✅ Deduplicates automatically — resolves each unique value once
df["iso3"] = rk.bulk(values=df["country"], to="iso3")

# ❌ Resolves every row, including duplicates
df["iso3"] = df["country"].apply(lambda x: rk.resolve_id(x, on_ambiguous="null"))
```

Survey and donor datasets repeat the same country names thousands of times. `bulk` deduplicates before resolving: 100 000 rows with 20 unique countries costs about the same as resolving those 20 countries once. The speedup scales with repetition in your column — the higher the row-to-unique ratio, the more work `bulk` eliminates versus row-by-row `apply`.

The `apply` path also returns entity IDs (`country/USA`), not code values, which means you'd need a separate pivot step anyway.

## Handle unresolved rows

By default, unresolved rows get `None`. Use `not_found` to replace them with a literal sentinel instead:

```python
df["iso3"] = rk.bulk(values=df["country"], to="iso3", not_found="???")
# n/a -> "???" instead of None
```

Any string works. `not_found="raise"` raises `ResolutionError` on the first miss — useful when your input is supposed to be clean.

## Handle ambiguous names

Some names match multiple entities. `Congo` resolves to both the Democratic Republic and the Republic of Congo. The default `on_ambiguous="null"` returns `None` for these rows. Use `"best"` to take the top-ranked candidate:

```python
df["iso3"] = rk.bulk(values=df["country"], to="iso3", on_ambiguous="best")
# Congo -> "COD" (Democratic Republic of the Congo)
```

Use `"raise"` to surface them as `AmbiguousResolutionError` during a data-quality pass.

## Inspect failures

`to="iso3"` gives you codes directly but hides per-row detail. Pass `to=None` to get a `BulkResult` with full diagnostics:

```python
result = rk.bulk(values=df["country"], to=None)
# BulkResult(total=5, resolved=4, no_match=1, ambiguous=0, error=0, kind='pandas')

summary = result.summary()
# ResolutionSummary(total=5, resolved=4, ambiguous=0, no_match=1, error=0)

detail = result.unnest()
# pd.DataFrame with columns: status, entity_id, confidence, pack_id, query_text
```

`result.failures` gives a sub-result containing only the non-resolved rows, so you can inspect or re-attempt just the misses.

## Use the Series accessor

Install the extras (`resolvekit[pandas]` or `resolvekit[polars]`) to get a `.resolvekit` accessor directly on Series and Expr objects:

```python
import pandas as pd
import resolvekit.pandas          # registers the accessor

df["iso3"] = df["country"].resolvekit.resolve(to="iso3")
```

```python
import polars as pl
import resolvekit.polars          # registers the namespace

df = df.with_columns(
    pl.col("country").resolvekit.resolve(to="iso3").alias("iso3")
)
```

The accessor accepts the same parameters as `rk.bulk()`. By default, parameter mistakes (unknown `to=`, bad `domain=`, unknown `from_system=`) raise immediately rather than silently producing all-`None` output.

### Control per-row errors with `on_error`

`on_error` governs what happens when an individual row's resolution raises an unexpected error at runtime:

| value | behaviour |
|-------|-----------|
| `"raise"` (default) | propagate the exception |
| `"null"` | return `None` for that row |
| `"keep"` | return the original input string |

```python
# Silently drop failed rows instead of raising
df["iso3"] = df["country"].resolvekit.resolve(to="iso3", on_error="null")
```

Note: `not_found` (for rows that simply don't match any entity) is independent of `on_error` (for rows that hit an unexpected runtime error). The defaults — `not_found="null"`, `on_error="raise"` — match `rk.bulk()`.

## Input code systems

If your column already contains ISO 2-letter codes, skip fuzzy matching entirely:

```python
df["iso3"] = rk.bulk(values=df["iso2_col"], to="iso3", from_system="iso2")
# "US" -> "USA", "DE" -> "DEU", "FR" -> "FRA"
```

Common `from_system` values: `"iso2"`, `"iso3"`, `"iso_numeric"`, `"dcid"`, `"wikidata"`. Any code system the loaded packs carry works — run `rk.default().code_systems()` for the full list.

## Next

- [**`bulk` reference**](../reference/api.md) — full parameter list, output shapes, and `BulkResult` API.
- [**Handle ambiguous matches**](handle-ambiguous-matches.md) — inspect candidates, override with context, and decide a tiebreak policy.
- [**Convert between code systems**](convert-between-code-systems.md) — pivot between ISO 2, ISO 3, numeric, DCID, Wikidata, and other code systems.
- [**Extract entities from free text**](extract-entities-from-text.md) — when your column contains running text rather than clean country names, use `parse()`/`parse_bulk()` to detect and link every entity mention with character offsets.
