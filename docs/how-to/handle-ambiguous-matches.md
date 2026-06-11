# How to handle ambiguous matches

Some inputs genuinely match more than one entity. "Congo" maps to both the Democratic Republic of the Congo (`country/COD`) and the Republic of the Congo (`country/COG`) at equal confidence. resolvekit doesn't silently pick one — it tells you there's a collision and lets you decide what to do.

## The three behaviors

`resolve_id` controls ambiguity through `on_ambiguous`. The default is `"raise"`.

### Raise (default) — catch and inspect

```python
import resolvekit as rk
from resolvekit import AmbiguousResolutionError

try:
    rk.resolve_id("Congo")
except AmbiguousResolutionError as err:
    print(f"{len(err.candidates)} candidates:")
    for c in err.candidates[:2]:
        print(f"  {c.entity_id:<20}  {c.canonical_name}")
```

Output:

```
2 candidates:
  country/COD           Congo [DRC]
  country/COG           Congo [Republic]
```

`err.candidates` is a list of `CandidateSummary` objects, each with `.entity_id`, `.canonical_name`, and `.confidence`. Use it to route the input to a human-review queue or to build a correction map.

### Null — return `None` and handle downstream

```python
entity_id = rk.resolve_id("Congo", on_ambiguous="null")
# entity_id is None
```

Use `"null"` in pipelines where unresolved rows are handled by a later step — for example, logged for manual review or skipped entirely.

### Best — take the top candidate

```python
entity_id = rk.resolve_id("Congo", on_ambiguous="best")
# "country/COD"
```

`"best"` returns whichever candidate has the highest confidence score. When two candidates are tied — as `COD` and `COG` are — the tie is broken by internal ranking heuristics, not a guarantee. Use `"best"` only when a wrong answer is better than no answer (reporting, fuzzy deduplication), not when accuracy matters.

## Inspecting ambiguity without resolving

`rk.resolve()` returns a `ResolutionResult` whether or not the input is ambiguous. Check `.is_ambiguous` before acting on the result:

```python
import resolvekit as rk

r = rk.resolve("Congo")

r.is_ambiguous   # True
r.status         # 'ambiguous'

# Inspect candidates
for c in r.candidates[:2]:
    print(f"{c.entity_id}  ({c.canonical_name})  conf={c.confidence:.2f}")
```

Output:

```
country/COD  (Congo [DRC])  conf=0.91
country/COG  (Congo [Republic])  conf=0.91
```

`r.best_candidate` returns the first candidate without committing to a resolution:

```python
r.best_candidate
# CandidateSummary('country/COD', conf=0.91 [geo] (3 evidence))
```

## Exploring candidates before deciding

When you're not sure which entities could match a term, use `diagnostics.search` to run a dry lookup against the loaded packs:

```python
resolver = rk.default()
hits = resolver.diagnostics.search("Congo", top_k=5)
```

Output:

```
[
    CandidateSummary('country/COD', conf=0.91 [geo] (3 evidence)),
    CandidateSummary('country/COG', conf=0.91 [geo] (3 evidence)),
]
```

This is useful interactively when building a correction map — you can see all plausible matches and decide which entity IDs to assign by hand.

## Narrowing with context

`ResolutionContext` lets you constrain the candidate set before resolution. `entity_types` filters to a specific entity type, which prunes candidates that don't match — useful when a query like "Congo" could match both countries and sub-national regions depending on loaded packs:

```python
import resolvekit as rk
from resolvekit import ResolutionContext

ctx = ResolutionContext(entity_types=["geo.country"])
r = rk.resolve("Congo", context=ctx)

r.status   # 'ambiguous'
for c in r.candidates:
    print(f"{c.entity_id}  {c.canonical_name}")
```

Output:

```
country/COD  Congo [DRC]
country/COG  Congo [Republic]
```

The input is still ambiguous — context can't pick between two genuine countries with the same name — but the noise from sub-national regions is gone. A follow-up call with `on_ambiguous="best"` or a correction map can finish the job.

!!! info "Why"
    Context doesn't lower confidence thresholds or guess. It prunes candidates that fail a hard constraint (wrong type, wrong parent). If two candidates both pass, resolution stays ambiguous.

## Snapping to a known candidate list

When you already know the valid options from a dataset or a previous lookup, use `rk.snap` to pick the closest match from that list:

```python
import resolvekit as rk

r = rk.resolve("Congo")
candidate_ids = [c.entity_id for c in r.candidates[:2]]
# ['country/COD', 'country/COG']

rk.snap(query="DR Congo", candidates=candidate_ids)
# 'country/COD'

rk.snap(query="Republic of Congo", candidates=candidate_ids)
# 'country/COG'
```

`snap` resolves each candidate from your list and returns the one whose name or aliases most closely match the query. It returns `None` when nothing clears the `max_distance` threshold (default `0.5`).

## Handling ambiguity in bulk

`rk.bulk` defaults to `on_ambiguous="null"` — ambiguous rows become `None` rather than raising:

```python
import pandas as pd
import resolvekit as rk

countries = pd.Series(["United States", "Congo", "Germany"])
iso3s = rk.bulk(values=countries, to="iso3")
# 0     USA
# 1    None
# 2     DEU
# dtype: object

# Flag the rows that need attention
ambiguous_mask = countries.notna() & iso3s.isna()
print(countries[ambiguous_mask].to_list())
# ['Congo']
```

Switch to `on_ambiguous="raise"` if you want the job to fail fast on any ambiguous input, or `"best"` to accept the top candidate throughout.

!!! warning "Heads up"
    `"best"` in bulk commits to the top-ranked candidate for every ambiguous row, with no per-row review. Use `rk.resolve(value).candidates` to inspect a sample of ambiguous inputs before enabling `"best"` on data where entity accuracy matters.

## Next

- [Resolver reference](../reference/resolver.md) — `ResolutionContext` fields and `on_ambiguous` across all resolver methods.
- [How resolution works](../explanation/how-resolution-works.md) — why two candidates can score identically and how the pipeline decides what to surface as ambiguous versus resolved.
