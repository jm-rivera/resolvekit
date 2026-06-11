# The entity graph

*As of v0.1.0.*

resolvekit's data isn't a flat code table. Entities are nodes; a small set of typed, time-aware relations connect them. That structure lets the library answer questions a code-conversion library can't — "which countries belonged to the EU on a given date?" or "what geographic region contains France?" — without a network call.

## Nodes and edges

An `EntityRecord` is a node. Relations are edges stored as `(entity_id, relation_type, target_id, valid_from, valid_until)` rows in a SQLite `relations` table, indexed in both directions.

You read edges by iterating `entity.relations`:

```python
import resolvekit as rk

for rel in rk.entity("Germany").relations:
    print(rel.relation_type, rel.target_id, rel.valid_from, rel.valid_until)
```

```
contained_in  DAC/DacCountries           None        None
contained_in  DAC/DacMembers             None        None
contained_in  EuropeanUnion              None        None
contained_in  undata-geo/G00406000       None        None
contained_in  m49/155                    None        None
member_of     EuropeanUnion              1958-01-01  None
member_of     groups/NATO                1955-05-06  None
member_of     groups/G7                  1975-01-01  None
member_of     groups/G20                 1999-09-26  None
...
```

Germany has 23 edges total. Each edge exposes `.relation_type`, `.target_id`, `.valid_from`, and `.valid_until` — no separate import needed.

## Three relation types

- **`member_of`** — a country (or territory) belongs to a group or union. Points from member to group.
- **`contained_in`** — geographic or organizational containment. France is contained in Europe; Europe is contained in the world region hierarchy.
- **`subsidiary_of`** — organizational hierarchy: a subsidiary points to its parent.

## Edges have direction

`member_of` edges point *from* the member *to* the group. The group node itself holds no outgoing member edges:

```python
import resolvekit as rk

rk.entity("European Union").relations  # []
```

That empty list isn't a data gap — it's the correct result. To find all EU members you'd need to scan every entity for a `member_of EuropeanUnion` edge, which is what the reverse index makes fast. The `members_of()` method on `Resolver` does exactly that reverse lookup:

```python
r = rk.default()   # shared singleton; equivalent to Resolver.auto() on first call
r.members_of("EU")               # ['country/AUT', 'country/BEL', ...]  (27 entries)
r.members_of("EU", as_codes="iso3")  # ['AUT', 'BEL', 'BGR', ...]
```

If you read a group's `.relations` and find nothing, you haven't misread the data — that's how group nodes work.

## Relations are time-aware

`valid_from` and `valid_until` describe a half-open interval `[valid_from, valid_until)`. Both are ISO date strings or `None`.

Dynamic groups carry dates. Germany joined the EU on 1958-01-01 (`valid_from="1958-01-01"`, `valid_until=None`). The United Kingdom's EU membership edge carries a `valid_until` near 2020-01-31, so:

```python
from resolvekit import Resolver
from datetime import date

r = Resolver.auto()
r.is_member("United Kingdom", "EU", as_of=date(2018, 1, 1))  # True
r.is_member("United Kingdom", "EU", as_of=date(2025, 1, 1))  # False
```

Snapshot groups — frozen compositions like "European Union (28 members, 2013–2020)" — carry `None/None` on their edges because the snapshot itself is the point-in-time fact; no start or end date is meaningful.

`r.known_groups()` lists all 32 named groups in the loaded packs. For the full set of query recipes — filtering by date, iterating members as codes, checking membership in bulk — see the how-to linked below.

### Entity existence: the `as_of` hard filter

Relation edges aren't the only thing that's time-bounded. Entities themselves carry `[valid_from, valid_until)` windows representing when they existed. When you pass `context=ResolutionContext(as_of=<date>)` to `resolve()`, candidates outside their existence window are dropped before scoring — not penalised, dropped.

```python
from datetime import date
from resolvekit import Resolver, ResolutionContext

r = Resolver.auto()

r.resolve("South Sudan", context=ResolutionContext(as_of=date(2000, 1, 1))).status
# ResolutionStatus.NO_MATCH   (South Sudan did not exist in 2000)

r.resolve("South Sudan", context=ResolutionContext(as_of=date(2020, 1, 1))).entity_id
# 'country/SSD'
```

Without `as_of`, the filter is a no-op — all entities are candidates regardless of temporal validity.

!!! note
    Coverage is curated for known-clear cases: states that came into existence (South Sudan 2011, Montenegro 2006, Timor-Leste 2002) and states that dissolved (Czechoslovakia, Yugoslavia, Netherlands Antilles). Most entities have no validity window and are always candidates.

## What you can query today

The high-level API covers membership and containment traversal:

| Method | What it does |
|---|---|
| `Resolver.members_of(group, *, as_of, as_codes)` | All current (or as-of) members of a named group |
| `Resolver.is_member(entity, group, *, as_of)` | Boolean membership check |
| `Resolver.known_groups()` | All named groups in the loaded packs |
| `Resolver.within(container, *, entity_type, recursive, max_depth, as_of, to)` | Entities geographically contained in a region |
| `Resolver.related(entity_or_id, *, relation, as_of, to)` | Follow edges to their resolved targets |
| `Resolver.diagnostics.unresolved_relations(entity_or_id, *, relation)` | Edges whose target doesn't resolve in loaded packs |

All methods live on `Resolver` — call them on `rk.default()` or any `Resolver` instance.

### Containment traversal: `within`

`within()` reverse-walks `contained_in` edges from a container node and returns every descendant, optionally filtered by type.

```python
from resolvekit import Resolver

r = Resolver.auto()  # or Resolver.lite() for country-level geo only

# The six UN M.49 sub-regions of Africa:
[e.canonical_name for e in r.within("Africa", entity_type="geo.subregion")]
# ['Western Africa', 'Eastern Africa', 'Northern Africa', 'Middle Africa',
#  'Southern Africa', 'Sub-Saharan Africa']

# Countries in a specific sub-region, as ISO 3166-1 alpha-3 codes:
r.within("Eastern Africa", entity_type="geo.country", to="iso3")
# ['BDI', 'COM', 'DJI', 'ERI', 'ETH', 'KEN', 'MDG', 'MOZ', 'MUS', 'MWI',
#  'MYT', 'RWA', 'SOM', 'SSD', 'SYC', 'TZA', 'UGA', 'ZMB', 'ZWE']

# All countries on a continent (currently about 57 for Africa):
len(r.within("Africa", entity_type="geo.country", to="iso3"))   # 57
```

`entity_type` filters the output only — intermediate hierarchy nodes are still traversed to reach their descendants. `to=` pivots each result to a scalar code (same mechanism as `related()`).

The container is resolved deterministically (exact ID, then exact name/alias — never fuzzy). When a name matches both a geographic hierarchy node and a same-named statistical aggregate, `within()` prefers the geographic node.

!!! warning "Heads up"
    `within()` returns descendants, not the container node itself. `r.within("Western Europe", entity_type="geo.subregion")` returns `[]` because Western Europe has no sub-region children. To inspect the node, use `r.entity("Western Europe")` — which returns an `EntityRecord` with `entity_id='m49/155'` and `entity_type='geo.subregion'`. To list its countries, use `r.within("Western Europe", entity_type="geo.country")`.

For a complete worked example — iterating M.49 sub-regions, mixing `entity_type` filters, and chaining `within()` with other API calls — see [How-to: List entities in a region](../how-to/list-entities-in-a-region.md).

### UN M.49 sub-regions and `geo.region` — the distinction

The graph carries two distinct entity types that represent supra-country groupings, and they mean different things:

- **`geo.subregion`** — UN M.49 geographic sub-regions (Western Africa, Western Europe, Sub-Saharan Africa, …). IDs use the `m49/` namespace (e.g., `m49/155` for Western Europe). These reflect geographic position.
- **`geo.region`** — statistical aggregates (LDCs, Small Island Developing States, development groups). These reflect political or economic classifications, not geography.

When you call `r.within("Africa", entity_type="geo.subregion")` you get the M.49 geographic sub-regions. Passing `entity_type="geo.region"` returns any statistical aggregates contained in Africa instead — a different set. To inspect a sub-region node directly:

```python
e = r.entity("Western Europe")
e.entity_id    # 'm49/155'
e.entity_type  # 'geo.subregion'
```

### Traversal: `related`

`related` follows an entity's edges and returns the resolved target entities.
Edges whose `target_id` cannot be looked up in the loaded packs are **silently omitted** — you never get a `None` entry in the list.

```python
import resolvekit as rk

# Pass a name, entity ID, or EntityRecord — all three work
parents = rk.default().related("country/DEU", relation="contained_in")
for parent in parents:
    print(parent.canonical_name)
```

```
Development Assistance Committee Countries
Development Assistance Committee  Members
European Union
Organisation for Economic Co-operation and Development (OECD)
Western Europe
```

Filter by relation type and date:

```python
from datetime import date

r = rk.default()
# Only member_of edges active on a given date
groups = r.related("country/DEU", relation="member_of", as_of=date(2018, 1, 1))
for group in groups:
    print(group.canonical_name)
```

Pivot each resolved entity to a code value with `to=`:

```python
# ISO-3 codes of Germany's containing regions
r.related("country/DEU", relation="contained_in", to="iso3")
# [None, None, ...]  (regional group entities don't carry iso3)
```

Unknown strings raise `EntityNotFoundError` immediately — no silent empty list:

```python
from resolvekit import EntityNotFoundError

try:
    r.related("NoSuchPlaceXYZ")
except EntityNotFoundError:
    pass
```

### Diagnostics: `unresolved_relations`

`diagnostics.unresolved_relations` returns every edge whose `target_id` doesn't resolve in the current pack set:

```python
r = rk.default()
dangling = r.diagnostics.unresolved_relations("country/DEU", relation="contained_in")
# [] — all of Germany's contained_in targets resolve in the bundled packs
```

Each dict has keys `"relation_type"`, `"target_id"`, `"valid_from"`, `"valid_until"`. All edges are reported regardless of temporal validity — filter on `valid_until` yourself if needed.

### Why some targets are dangling

The `contained_in` edge target is the raw Data Commons parent ID written at build time: `"geoId/06"` (US admin1), `"geoId/06037"` (US admin2), `"zip/90210"` (postal areas). These IDs exist in DC's graph but only appear in the remote admin and cities packs, not the bundled ones. In `rk.default()` (bundled packs only), country `contained_in` edges resolve fully — the regions pack ships all M.49 sub-region and continent targets. `member_of` edges written by the groups enricher are always canonical — 0% dangling regardless of which packs are loaded. Dangling edges appear when you load an admin pack on its own without loading all the packs its parent edges point to.

resolvekit is not a general graph database and has no query language. The graph is small, purposeful, and covers the relations that come up most in data work.

??? abstract "Under the hood"
    The `relations` table in each SQLite pack stores `(entity_id, relation_type, target_id, valid_from, valid_until)`. It's indexed in both directions: a forward index (by `entity_id`) for reading an entity's own edges, and a reverse index (by `target_id`) for the `members_of()` lookup. Edges are built at pack-build time from curated YAML source files; there's no runtime graph construction.

## Next

[Reference: `Resolver`](../reference/resolver.md) — complete signatures for `members_of`, `is_member`, `known_groups`, and `within`, with parameter details.

[How-to: Resolve group membership](../how-to/resolve-group-membership.md) — filtering by date, handling snapshot groups, and iterating members as codes.

[How-to: List entities in a region](../how-to/list-entities-in-a-region.md) — `within()` recipes, UN M.49 sub-region traversal, and mixing `entity_type` filters.
