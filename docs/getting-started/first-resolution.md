# First resolution

After this walkthrough you'll be able to:

- Resolve a messy country name to a canonical entity ID.
- Get an ISO 3166-1 alpha-3 code directly from a name string.
- Handle inputs that don't match anything.
- Read the confidence score on a result and understand what it means.
- Clean a whole pandas column in one call.

**You'll need** resolvekit on Python 3.12+ ([install](install.md)); the last step also uses the `pandas` extra. About five minutes.

## Resolve a list of names

Start with a small list that covers the common trouble cases: a missing accent, a Portuguese-language name, a formal full-name, and one that doesn't exist.

```python
import resolvekit as rk

names = ["United States", "Cote dIvoire", "Brasil", "Republic of Korea", "XYZZY"]

for name in names:
    print(name, "->", rk.resolve_id(name))
```

Output:

```
United States -> country/USA
Cote dIvoire -> country/CIV
Brasil -> country/BRA
Republic of Korea -> country/KOR
XYZZY -> None
```

`rk.resolve_id` returns a string entity ID or `None`. The IDs use the format `domain/Value` — for countries this matches the [Data Commons](https://datacommons.org) DCID convention.

"Brasil" resolves because resolvekit indexes multilingual aliases. "Cote dIvoire" resolves even without the accent. "XYZZY" returns `None` because nothing in the bundled data matches it above the confidence threshold.

!!! note
    `rk.resolve_id` returns `None` for a non-match and raises `AmbiguousResolutionError` when two entities score equally. If you'd rather have `None` in both cases, pass `on_ambiguous="null"`.

## Get a code directly

If you need ISO codes instead of entity IDs, use the `to=` argument:

```python
import resolvekit as rk

print(rk.resolve("Brasil", to="iso3"))
```

```
BRA
```

`rk.resolve(..., to="iso3")` returns the code string (or `None` if unresolved), bypassing the result object entirely. Other useful pivots on country data: `"iso2"`, `"name"`, `"flag"`, `"dcid"`.

## Set a default output once

Passing `to="iso3"` on every call works, but if your whole script wants ISO codes you can set that once at construction time with `default_to=`:

```python
from resolvekit import Resolver

r = Resolver.auto(default_to="iso3")
print(r.resolve("Spain"))          # "ESP"
print(r.resolve("Brasil"))         # "BRA"
print(r.resolve("XYZZY"))          # None
```

After that, every `r.resolve(...)` call returns the ISO 3166-1 alpha-3 code (or `None` on no match) without repeating the `to=` argument. If you need the raw result object for a specific call, pass `to=None` or `as_result=True` to bypass the default. And `r.resolve_id(...)` always returns the canonical entity ID regardless of the configured default — `default_to` never affects it.

For a list of available code systems, fallback chains (`default_to=["iso3", "name"]`), and what happens when an entity lacks the requested code, see [Convert between code systems](../how-to/convert-between-code-systems.md).

## Inspect a result

`rk.resolve_id` and the `to=` shorthand drop the detail. When you want to understand *why* something resolved — or whether to trust it — use `rk.resolve` and look at the result object:

```python
import resolvekit as rk

r = rk.resolve("Brasil")
print(round(r.confidence, 2))
```

```
0.91
```

That's about 91%. The score reflects how the match was found: exact code matches score near 1.0; alias hits like "Brasil" score a bit lower. A score below ~0.70 is abstained by default — you won't see it come back as a resolved result.

For a full breakdown, call `.explain()`:

```python
import resolvekit as rk

r = rk.resolve("Brasil")
print(r.explain(verbosity="full").as_text())
```

```
Resolution Scorecard
============================================================
Query: "Brasil"
Normalized: "brasil"
Status: RESOLVED
Entity: country/BRA
Confidence: 90.8%
Reasons: exact_name_match
Pack: geo
Match Tier: exact_name

Match Details:
----------------------------------------
  Primary Source: geo_exact_name
  Sources:
    - geo_exact_name on name.alias (score: 0.950)
      matched "brasil"
    - geo_fuzzy on fuzzy (score: 1.000)
      matched "brasil"
  Key Features:
    exact_name_hit: Yes
    query_len: 6
    fuzzy_edit_sim: 1.000
    fuzzy_token_sim: 1.000
    retrieval_rank_inv: 1.000
    hierarchy_rank: 0.850
    exact_code_hit: No
    query_has_digits: No
  Why this match:
    - matched canonical name exactly
    - very close edit-distance match

Trace Events (14):
----------------------------------------
...

Timing:
----------------------------------------
  Generation: 0.28ms
  Decision: 0.00ms
  Total: 0.28ms
```

!!! note
    Confidence floats and feature values like `hierarchy_rank` vary with the calibrator version. The structure, tier (`exact_name`), and reason codes are stable. Timing numbers vary per run.

The scorecard tells you which source matched first (`geo_exact_name` on an alias), what the fuzzy similarity was, and what tier the match landed in. This is the fastest way to debug an unexpected result.

The result object also carries convenience shortcuts: `r.iso3`, `r.iso2`, `r.flag`, `r.name`, `r.entity_id`, `r.status`, `r.match_tier`, and `r.is_resolved`.

??? abstract "Under the hood"
    Resolution runs entirely offline: exact-code lookup → exact-name lookup → fuzzy (rapidfuzz) → typo correction (SymSpell). Candidates from each stage are scored by a calibrated model using features like edit distance, token similarity, candidate prominence, and hierarchy rank. No LLM, no network call. The pipeline is deterministic.

## Clean a whole column

The loop above is fine for exploration. For a real dataset, use `rk.bulk`:

```python
import pandas as pd
import resolvekit as rk

series = pd.Series(["United States", "Cote dIvoire", "Brasil", "Republic of Korea", "XYZZY"])
result = rk.bulk(values=series, to="iso3")
print(result)
```

```
0     USA
1     CIV
2     BRA
3     KOR
4    None
dtype: object
```

`rk.bulk` returns a pandas `Series` when given one. Unresolved rows come back as `None`. It deduplicates identical inputs automatically, so large columns with repeated country names resolve each unique value once.

!!! warning "Heads up"
    `rk.bulk` needs the `pandas` extra. If you see `ImportError`, install it with `uv add "resolvekit[pandas]"` (or `pip install "resolvekit[pandas]"`).

## Next

[How resolution works](../explanation/how-resolution-works.md) — the full pipeline from normalization through scoring and the decision model; useful if a result surprises you.

[Confidence scores](../explanation/confidence.md) — what the score measures, why it isn't a probability, and when to trust it.

[Clean a DataFrame column](../how-to/clean-a-dataframe-column.md) — practical patterns for null handling, sentinel detection, and attaching multiple output columns to a DataFrame.

[Extract entities from text](../how-to/extract-entities-from-text.md) — use `parse()` / `parse_bulk()` to detect and link every entity mention in free text, with character offsets and calibrated confidence. Requires `resolvekit[parsing]`.

[List entities in a region](../how-to/list-entities-in-a-region.md) — use `Resolver.within()` to walk the geographic containment graph and pull every country (or UN M.49 sub-region) inside a continent or sub-region.
