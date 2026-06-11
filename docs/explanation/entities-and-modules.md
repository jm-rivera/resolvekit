# Entities, modules, and domains

*As of v0.1.0.*

resolvekit resolves text to *entities* — structured records with a stable ID, a
canonical name, and codes across many authority systems. This page explains what
an entity is, how modules organize the data, and how the resolver routes a query
to the right module.

## Entity IDs

Every entity has an `entity_id` in the form `lowercase-domain/Value`:

```
country/USA
country/DEU
country/TZA
```

For countries, this ID equals the [Data Commons](https://datacommons.org/) dcid,
which makes cross-referencing straightforward when you're working in that
ecosystem. For other entity types the same `domain/Value` convention applies,
but the value portion follows each domain's own authority.

The ID is the stable key you store. Names and codes drift — ISO codes get
reassigned, spellings vary, and romanizations differ — but the entity ID stays
fixed.

## EntityRecord

An `EntityRecord` carries everything resolvekit knows about an entity:

```python
import resolvekit as rk

e = rk.entity("Germany")
e.entity_id      # "country/DEU"
e.canonical_name # "Germany"
e.iso2           # "DE"
e.iso3           # "DEU"
e.flag           # "🇩🇪"
e.code("wikidata")   # "Q183"
e.code("dcid")       # "country/DEU"
e.code("fips104")    # "GM"
e.code("iso_numeric")# "276"
```

The `.codes_dict` property returns every code system as a `{system: value}`
dict. Germany's record contains 46 entries spanning ISO, Wikidata, GND,
VIAF, OpenStreetMap, IOC, and many national library authority IDs:

```python
e.codes_dict
# {
#   'iso3': 'DEU',
#   'iso2': 'DE',
#   'iso_numeric': '276',
#   'dcid': 'country/DEU',
#   'wikidata': 'Q183',
#   'fips104': 'GM',
#   'gndid': '4011882-4',
#   'osmrelationid': '51477',
#   ... (40+ more)
# }
```

Use `.code(system)` when you want one value; use `.codes_dict` when you want
to enumerate what's available. Both return `None` for absent systems rather
than raising.

`.aliases` returns every non-canonical name — multilingual names, endonyms,
exonyms, abbreviations, and historical names — in declaration order:

```python
e.aliases[:5]
# ['Alemanha', 'Alemania', 'Allemagne', 'Bundesrepublik', 'Bundesrepublik Deutschland']
```

You can look up an entity by any code system, not just by name:

```python
rk.entity(iso2="DE")             # same record
rk.entity(dcid="country/TZA")   # Tanzania
rk.entity(wikidata="Q30")        # United States
```

!!! warning "Heads up"
    Passing two code kwargs to `rk.entity()` raises `ValueError`. Only one
    lookup key at a time.

## Modules and domains

The data is organized into two layers:

- A **domain** (`geo`, `org`) is the top-level grouping. It maps to a broad
  subject area.
- A **module** is the loadable unit within a domain. Each module covers one
  or more entity types and ships as its own SQLite dataset.

resolvekit ships 16 modules across two domains:

### `geo` — geographic entities

| Module | Entity types | Coverage |
|---|---|---|
| `geo.countries` | `geo.country` | Sovereign states and territories (currently 241 entities) |
| `geo.regions` | `geo.region`, `geo.subregion` | World Bank/UN **statistical** aggregates (LDCs, SIDS, development groups) and UN M.49 **geographic** sub-regions (Western Africa, Eastern Europe, …), IDs like `m49/155` |
| `geo.continents` | `geo.continent` | Continental classifications |
| `geo.continental_unions` | `geo.continental_union` | Unions with membership — EU, AU, ASEAN, and others |
| `geo.admin1` | `geo.admin1` | First-level administrative divisions (states, provinces) |
| `geo.admin2` | `geo.admin2` | Second-level (counties, departments) |
| `geo.admin3` | `geo.admin3` | Third-level |
| `geo.admin4` | `geo.admin4` | Fourth-level |
| `geo.admin5` | `geo.admin5` | Fifth-level |
| `geo.cities` | `geo.city` | Populated places (~155 MB download) |

`geo.region` and `geo.subregion` are distinct entity types, both bundled in the `geo.regions`
module. Statistical aggregates (`geo.region`) group countries by economic or development criteria;
geographic sub-regions (`geo.subregion`) follow the UN M.49 geographic hierarchy. Use
`entity_type="geo.subregion"` to target the latter in
[containment queries](../how-to/list-entities-in-a-region.md) and `entity_type="geo.region"`
for statistical aggregates.

### `org` — organizational entities

| Module | Coverage |
|---|---|
| `org.companies` | Corporations and subsidiaries |
| `org.governments` | Government bodies and agencies |
| `org.lenders` | Multilateral and bilateral lending entities |
| `org.political_parties` | Political parties |
| `org.providers` | Development finance providers |
| `org.data_sources` | Statistical data sources and publishers |

The org domain is bundled and usable offline; examples in these docs lead with
geo, where entity coverage and multilingual matching are strongest. Per-language
names (en, fr, es, de, ru, ja, it, pt, zh, ar) and their aliases are indexed for
countries; deeper sub-national multilingual coverage is available via the remote
admin and cities packs where applicable.

### Bundled vs remote

The first four geo modules and all six org modules are **bundled**: they ship
inside the wheel and work immediately after `pip install resolvekit`. No
download needed.

`geo.admin1` through `geo.cities` are **remote**: the data is fetched from a
GitHub Release on first use and cached locally. On a fresh install,
`rk.modules()` shows them as `is_available=False` until you download:

```python
rk.download("geo.admin1")   # one module
rk.download("geo")          # all geo remote modules
```

!!! note
    `rk.modules()` lists every module with its `distribution`, `is_available`,
    `size_mb`, and `download_size_mb` fields, so you can inspect what's ready
    before routing queries to those packs.

## How the resolver picks a module

The default `Resolver.auto()` loads all installed modules and routes each query
based on entity type signals detected in the input. This is the AUTO routing
mode. You don't specify which module to use; the router does it.

```python
rk.resolve_id("United States")  # routes to geo.countries -> "country/USA"
rk.resolve_id("Republic of Korea")  # -> "country/KOR"
```

To load only a subset of modules, use `Resolver.from_modules()`:

```python
from resolvekit import Resolver

r = Resolver.from_modules(module_ids=["geo.countries", "geo.continents"])
r.resolve_id("France")  # "country/FRA"
```

`Resolver.lite()` is a preset that loads the four bundled geo modules only —
`geo.countries`, `geo.regions`, `geo.continents`, `geo.continental_unions` —
for environments where footprint matters:

```python
r = Resolver.lite()
r.domains  # ['geo']
```

## Group membership

Membership is modeled as `member_of` edges in the entity graph. Three methods
on `Resolver` surface them: `members_of`, `is_member`, and `known_groups`.

```python
r = rk.default()
r.members_of("EU")          # 27 entity IDs: ['country/AUT', 'country/BEL', ...]
r.is_member("Germany", "EU")  # True
```

For the full explanation — edge direction, time-aware validity, and snapshot
groups — see [The entity graph](knowledge-graph.md). For query recipes see
[Resolve group membership](../how-to/resolve-group-membership.md).

## What the entity graph powers

The same graph that backs group membership also drives three other features:

- **Containment queries** — `Resolver.within()` walks `contained_in` edges to
  return every entity inside a region, continent, or UN M.49 sub-region; see
  [List entities in a region](../how-to/list-entities-in-a-region.md).
- **Free-text extraction** — `rk.parse()` and `rk.parse_bulk()` scan text and
  link every entity mention to the graph, with calibrated confidence and character
  offsets; see [Extract entities from text](../how-to/extract-entities-from-text.md).
- **Bring-your-own data** — `Resolver.from_records()` builds a standalone
  resolver from your own records, and `Resolver.augment()` attaches codes or
  attributes to existing entities by joining on a shared code system; see
  [Bring your own data](../how-to/bring-your-own-data.md).

---

**Next**

- [Reference: `Resolver`](../reference/resolver.md) — complete constructor
  options, routing modes, and method signatures.
- [Explanation: How resolution works](how-resolution-works.md) — the pipeline
  from raw text to a scored candidate: normalization, exact match, fuzzy match,
  typo correction, and calibrated confidence.
