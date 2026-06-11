# How to resolve group membership

Query which countries belong to a group, check a single country's membership, and
filter datasets to a group's members — using `Resolver.members_of()`,
`Resolver.is_member()`, and `Resolver.known_groups()`.

## List the members of a group

`members_of` returns a sorted list of entity IDs.

```
['country/AUT', 'country/BEL', 'country/BGR', 'country/CYP', 'country/CZE',
 'country/DEU', 'country/DNK', 'country/ESP', 'country/EST', 'country/FIN', ...]
```

```python
import resolvekit as rk

r = rk.default()
r.members_of("EU")
```

The list contains 27 entries, one per current EU member. Short aliases like
`"EU"`, `"NATO"`, and `"UN"` resolve the same way full names do — they're
registered aliases, not special cases.

## Get members as ISO codes

Pass `as_codes` to convert directly to a code system instead of entity IDs.

```
['AUT', 'BEL', 'BGR', 'CYP', 'CZE', 'DEU', 'DNK', 'ESP', 'EST', 'FIN',
 'FRA', 'GRC', 'HRV', 'HUN', 'IRL', 'ITA', 'LTU', 'LUX', 'LVA', 'MLT',
 'NLD', 'POL', 'PRT', 'ROU', 'SVK', 'SVN', 'SWE']
```

```python
r.members_of("EU", as_codes="iso3")   # 27 ISO 3166-1 alpha-3 codes
r.members_of("EU", as_codes="iso2")   # 27 ISO 3166-1 alpha-2 codes
```

!!! note
    The returned list can be shorter than the entity-ID list if some members
    don't carry the requested code. This is rare for `iso3` and `iso2` on
    sovereign countries but can happen for newer or disputed members in other
    groups.

## Check whether a country is a member

`is_member` takes a country name (or any resolvable alias) and a group name.

```
True
False
True
```

```python
r.is_member("Germany", "EU")          # True
r.is_member("Norway", "EU")           # False
r.is_member("Nigeria", "African Union")  # True
```

## Query membership as of a past date

`members_of` and `is_member` both accept `as_of`. Without it, they use today's
date.

The UK left the EU on 2020-01-31. Pass `as_of` to query either side of that.

```
True
False
```

```python
from datetime import date

r.is_member("United Kingdom", "EU", as_of=date(2018, 1, 1))  # True
r.is_member("United Kingdom", "EU", as_of=date(2025, 1, 1))  # False
```

To see the full 2018 membership roster (28 members including the UK):

```
28
```

```python
len(r.members_of("EU", as_of=date(2018, 1, 1)))  # 28
```

Future dates are accepted for dynamic groups — the result is the current
membership, not a projection.

## Filter a pandas DataFrame to a group's members

Build the filter set once from `members_of`, then use pandas' `isin`.

```
   country  gdp_usd_bn iso3
0  Germany        4082  DEU
2   France        2794  FRA
4    Spain        1428  ESP
```

```python
import pandas as pd
import resolvekit as rk

r = rk.default()
eu_iso3 = set(r.members_of("EU", as_codes="iso3"))

df = pd.DataFrame({
    "country": ["Germany", "Norway", "France", "United States", "Spain"],
    "gdp_usd_bn": [4082, 593, 2794, 25460, 1428],
})
df["iso3"] = rk.bulk(values=df["country"], to="iso3")
eu_df = df[df["iso3"].isin(eu_iso3)]
```

If your source column has multilingual or messy names with no existing code
column, `rk.bulk` normalises them first. "Deutschland", "Francia", "Espagne"
all resolve to `"DEU"`, `"FRA"`, `"ESP"` before the filter runs.

!!! note
    `pandas` is an optional dependency. Install with `pip install resolvekit[pandas]`
    if you don't already have it.

## Discover which groups exist

`known_groups()` returns the 32 canonical group names currently loaded.

```
['African Union', 'Association of Southeast Asian Nations', 'BRIC', 'BRICS',
 'Commonwealth of Nations', 'European Economic Area', 'European Union', ...]
```

```python
r.known_groups()
```

These are canonical names. Many groups also accept short aliases (`"EU"`,
`"NATO"`, `"UN"`, `"G20"`) — those aliases work in `members_of` and
`is_member` even though they don't appear in `known_groups()`.

!!! info "Why"
    `known_groups()` lists canonical names, not aliases. It reflects the loaded
    modules — all 32 groups ship with the `geo.continental_unions` module,
    so `rk.default()`, `Resolver.auto()`, and `Resolver.lite()` all return the
    same list.

## Work with snapshot (frozen) groups

Some groups in `known_groups()` are snapshots — frozen membership at a
specific historical point. They're named with an explicit member count and date
range, e.g. `"European Union (28 members, 2013–2020)"`.

```
28
True
```

```python
r.members_of("European Union (28 members, 2013–2020)")   # 28 members
r.is_member("United Kingdom", "European Union (28 members, 2013–2020)")  # True
```

Short aliases like `"EU28"`, `"EU27"`, `"G8"`, and `"BRIC"` also resolve to
their snapshots directly:

```
28
8
4
```

```python
len(r.members_of("EU28"))   # 28
len(r.members_of("G8"))     # 8
len(r.members_of("BRIC"))   # 4
```

Passing `as_of` to a snapshot has no effect — the membership is frozen by
construction. resolvekit emits a `UserWarning` to make this visible:

```python
import warnings
from datetime import date

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    r.members_of("European Union (28 members, 2013–2020)", as_of=date(2020, 1, 1))
    print(caught[0].message)
# as_of is ignored for snapshot entity 'groups/EU28'; the snapshot is frozen by construction.
```

!!! warning "Heads up"
    `as_of` has no effect on snapshot groups — the membership is frozen by
    construction. The `UserWarning` is the only signal: if you pass a date and
    get back the full frozen membership, you likely queried a snapshot. Check
    `known_groups()` to see which groups are snapshots (their names include a
    member count and date range).

## Handle a missing group

An unrecognised group name raises `GroupNotFoundError`.

```python
from resolvekit import GroupNotFoundError

try:
    r.members_of("EU1999")   # not a recognised group or alias
except GroupNotFoundError:
    print("group not found")
```

To guard without an exception, check `known_groups()` first — but note that
canonical-name membership doesn't tell you whether an alias will resolve.
`try/except` is the reliable pattern.

```python
from resolvekit import GroupNotFoundError

def safe_members(resolver, group_name):
    try:
        return resolver.members_of(group_name)
    except GroupNotFoundError:
        return []
```

## Next

- [Resolver reference](../reference/resolver.md) — full parameter listings for
  `members_of`, `is_member`, and `known_groups`.
- [Explanation: knowledge graph](../explanation/knowledge-graph.md) — how group
  membership is modelled and why dynamic and snapshot groups behave differently.
- [List entities in a region](list-entities-in-a-region.md) — the reverse direction:
  what countries or sub-regions does a continent or UN M.49 region contain (`within()`).
