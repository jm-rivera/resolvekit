# How to refine resolution with context hints

*Added in v0.1.3.*

Context hints narrow the candidate set before the resolution pipeline scores anything. They work by filtering or prioritizing candidates that match the constraint — entity type, country, parent ID, or other attributes — which resolves many inputs that would otherwise come back `AMBIGUOUS` or as the wrong entity.

## Pass context as a plain dict

Every resolution surface accepts `context=` as a plain `dict`. No import needed.

```python
import resolvekit as rk

# With bundled data, France resolves unambiguously:
rk.resolve("France")
# ResolutionResult(status='resolved', entity_id='country/FRA', ...)

# After downloading more data packs, entity_types pins the domain explicitly:
rk.resolve("France", context={"entity_types": {"geo.country"}})
# ResolutionResult(status='resolved', entity_id='country/FRA', ...)
```

The valid context keys are:

| Key | Type | What it does |
|-----|------|-------------|
| `country` | `str` | ISO alpha-2 (`"FR"`) or alpha-3 (`"FRA"`) or country name (`"France"`) — restricts to entities in that country |
| `entity_types` | `set[str]` or `list[str]` | Restrict to these entity types, e.g. `{"geo.country"}`, `["org.lender"]` |
| `parent_ids` | `list[str]` | Restrict to entities whose parent is one of these entity IDs |
| `languages` | `list[str]` | Preferred BCP 47 language codes for name matching |
| `attributes` | `dict` | Pack-specific escape hatch for domain attributes |
| `as_of` | `date` or ISO date `str` | Resolve against entities valid at this date |

An unknown key raises `UnknownContextKeyError` immediately and lists the valid ones:

```python
try:
    rk.resolve("Germany", context={"region": "Europe"})
except rk.UnknownContextKeyError as e:
    print(e.valid)
    # ['as_of', 'attributes', 'country', 'entity_types', 'languages', 'parent_ids']
```

## Context works on all resolution surfaces

`context=` is accepted on every call:

```python
rk.resolve("...",     context={...})
rk.resolve_id("...", context={...})
rk.bulk(values=...,  context={...})
rk.snap(query="...", context={...})
rk.suggest("...",    context={...})
rk.parse("...",      context={...})
rk.parse_bulk(values=..., context={...})
```

The pandas and polars accessors also accept it:

```python
import resolvekit.pandas   # or resolvekit.polars

df["country"].resolvekit.bulk(context={"entity_types": {"geo.country"}})
df["country"].resolvekit.resolve(context={"entity_types": {"geo.country"}})
```

`ResolutionContext` objects continue to work everywhere — the dict form is a shortcut for the common case:

```python
from resolvekit import ResolutionContext
# these are equivalent:
rk.resolve("France", context={"entity_types": {"geo.country"}})
rk.resolve("France", context=ResolutionContext(entity_types=frozenset({"geo.country"})))
```

## Restrict by entity type

Use `entity_types` when the same name exists in multiple domains or as multiple entity types, and you know which you want:

```python
# Works on any name that could match both geo and org entities
rk.resolve("Sudan", context={"entity_types": {"geo.country"}})
# ResolutionResult(status='resolved', entity_id='country/SDN', ...)

# Bulk with entity type filter
rk.bulk(
    values=["Germany", "France", "Japan"],
    context={"entity_types": {"geo.country"}},
    to="iso3",
)
# ['DEU', 'FRA', 'JPN']
```

!!! info "Why"
    Context doesn't lower confidence thresholds or force a match. It prunes candidates that fail a hard constraint before scoring. If two candidates both pass, resolution stays `AMBIGUOUS`.

## Use country names in context

The `country` key accepts ISO alpha-2 (`"FR"`), ISO alpha-3 (`"FRA"`), and plain country names (`"France"`). Names are resolved to ISO codes automatically:

```python
# All three of these set the same constraint:
rk.resolve("Paris", context={"country": "FR"})
rk.resolve("Paris", context={"country": "FRA"})
rk.resolve("Paris", context={"country": "France"})
```

An ambiguous or unrecognized country name raises `ValueError` with a did-you-mean suggestion:

```python
try:
    rk.resolve("Paris", context={"country": "Congo"})
except ValueError as e:
    print(e)
    # cannot resolve country name 'Congo' — ambiguous (did you mean 'CD' or 'CG'?);
    # pass an ISO code
```

!!! note
    City-level disambiguation with `country=` requires the remote geo data packs (`rk.download("geo.cities")`). Country-level resolution and org resolution work with the bundled packs.

## Point-in-time filtering with `as_of`

Pass a date to restrict candidates to entities valid on that date. This is a hard filter — an entity outside its `[valid_from, valid_until)` window is dropped before scoring, regardless of confidence:

```python
from datetime import date

rk.resolve("South Sudan", context={"as_of": date(2000, 1, 1)}).status
# 'no_match' — South Sudan didn't exist until 2011

rk.resolve("South Sudan", context={"as_of": date(2020, 1, 1)}).entity_id
# 'country/SSD'
```

## Handle AMBIGUOUS results: reading the hint

When resolution stays `AMBIGUOUS`, the repr tells you which inputs to try next and, when candidates span different countries, ends with a copy-pasteable `context=` hint:

```python
r = rk.resolve("Congo")
print(repr(r))
# AMBIGUOUS — candidates:
#   Congo [DRC], CD (conf=0.92)
#   Congo [Republic], CG (conf=0.91)
#   try:
#     resolvekit.resolve(text='Congo [DRC]')
#   resolvekit.resolve(text='Congo [Republic]')
```

The `refinement_hints` tuple on the result lists the constraints that could break the tie — `country`, `parent_ids`, `entity_types`, etc.:

```python
r.refinement_hints
# (RefinementHint.PARENT_IDS, RefinementHint.COUNTRY, RefinementHint.LANGUAGES)
```

For country-level ambiguity, the most direct fix is to use the more specific canonical name shown in the hint, or to add a `country=` context when the right country is known.

## Next

- [Handle ambiguous matches](handle-ambiguous-matches.md) — `on_ambiguous` options, inspecting candidates, and when to use `"best"` versus a correction map.
- [Clean a DataFrame column](clean-a-dataframe-column.md) — per-row context for bulk resolution, so each row resolves under its own country or filter.
- [API reference — `ResolutionContext`](../reference/api.md#resolutioncontext) — full field list and the `.replace()` method for building context incrementally.
