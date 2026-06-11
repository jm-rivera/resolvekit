# How to list the entities in a region

Use `Resolver.within()` to enumerate what a geographic region contains — countries
in a continent, UN M.49 sub-regions in Africa, or any other containment relationship
in the knowledge graph.

## List countries in a continent

```
['BDI', 'COM', 'DJI', 'ERI', 'ETH', 'KEN', 'MDG', 'MOZ', 'MUS', 'MWI',
 'MYT', 'RWA', 'SOM', 'SSD', 'SYC', 'TZA', 'UGA', 'ZMB', 'ZWE']
```

```python
from resolvekit import Resolver

r = Resolver.auto()   # or Resolver.lite() for country-level geo only

r.within("Eastern Africa", entity_type="geo.country", to="iso3")
```

Pass `to="iso3"` to get a flat list of ISO 3166-1 alpha-3 codes instead of
`EntityRecord` objects. `entity_type="geo.country"` filters the output to
`geo.country` entities (including territories and dependencies, not just UN member states);
intermediate sub-regions are still traversed to reach them.

For a full continent, Africa yields 57 countries:

```python
len(r.within("Africa", entity_type="geo.country", to="iso3"))   # 57
```

## Distinguish geo.region from geo.subregion

This is the most common source of confusion.

| Type | What it means | Example entities |
|---|---|---|
| `geo.subregion` | UN M.49 geographic sub-region | Western Africa, Eastern Africa, Sub-Saharan Africa |
| `geo.region` | OECD DAC development/statistical aggregate | "South of Sahara, regional", "Africa, regional" |

To list the UN M.49 geographic sub-regions of Africa:

```
['Western Africa', 'Eastern Africa', 'Northern Africa', 'Middle Africa',
 'Southern Africa', 'Sub-Saharan Africa']
```

```python
[e.canonical_name for e in r.within("Africa", entity_type="geo.subregion")]
# IDs: m49/011, m49/014, m49/015, m49/017, m49/018, m49/202
```

`entity_type="geo.region"` would return OECD DAC development aggregates instead — statistical
groupings like "Africa, regional" or "South of Sahara, regional". If you want geographic
subdivisions of Africa, always use `"geo.subregion"`.

## Get the sub-region node itself

!!! warning "Heads up"
    `within(node, ...)` returns what's **inside** the node, not the node itself.
    `within("Western Europe", entity_type="geo.subregion")` returns `[]` because
    Western Europe (`m49/155`) has no sub-region children — it IS a sub-region leaf.
    To get the node, call `entity()` directly:

    ```python
    e = r.entity("Western Europe")
    # EntityRecord, entity_id='m49/155', entity_type='geo.subregion'
    ```

    Then call `within("Western Europe", entity_type="geo.country")` to get its countries.

## Control traversal depth

By default `within()` walks the full containment graph (transitive). Two parameters
let you limit the descent:

```python
# Direct children only — equivalent to max_depth=1
r.within("Africa", entity_type="geo.subregion", recursive=False)

# Explicit hop limit
r.within("Africa", entity_type="geo.country", max_depth=2)
```

`recursive=False` and `max_depth=1` are equivalent. Use `max_depth` when you want
more than one hop but not unbounded traversal.

## Return EntityRecords instead of codes

Omit `to=` to get `EntityRecord` objects. You can then inspect any attribute:

```python
records = r.within("Eastern Africa", entity_type="geo.country")
for e in records:
    print(e.entity_id, e.canonical_name)
# country/BDI Burundi
# country/COM Comoros
# ...
```

`to=` pivots each record to a scalar code via `EntityRecord.to(to)`. Entities that
don't carry the requested code yield `None`, so pair `to=` with `entity_type=` to
keep the list aligned.

## Query as of a point in time

`within()` accepts `as_of` as a `datetime.date`. Unlike `members_of`, passing
`as_of=None` (the default) returns **all** containment edges regardless of their
validity window — it does not default to today's date.

```python
from datetime import date

# All edges (default)
r.within("Africa", entity_type="geo.country", to="iso3")

# Only edges valid on a specific date
r.within("Africa", entity_type="geo.country", to="iso3", as_of=date(2010, 1, 1))
```

This matters for containment edges tied to political changes. For most geographic
hierarchies the edges have no validity bounds, so the result is the same either way.

## Use within() at module level

`within()` is a `Resolver` method — there is no module-level `rk.within()`.

```python
import resolvekit as rk

# Use rk.default() to access the shared singleton:
rk.default().within("Africa", entity_type="geo.country", to="iso3")
```

`rk.default()` is equivalent to `Resolver.auto()` but reuses the already-loaded
singleton. You can also construct a geo-only resolver with `Resolver.lite()`, which
loads only country-level bundles and is faster to initialise:

```python
from resolvekit import Resolver

r = Resolver.lite()
r.within("Africa", entity_type="geo.subregion")
```

## Next

- [Resolver reference](../reference/resolver.md) — full parameter listing for `within()`.
- [Explanation: knowledge graph](../explanation/knowledge-graph.md) — how geographic
  containment and M.49 hierarchies are modelled.
- [How to resolve group membership](../how-to/resolve-group-membership.md) — `members_of()`,
  `is_member()`, and snapshot groups like EU28 and G8.
