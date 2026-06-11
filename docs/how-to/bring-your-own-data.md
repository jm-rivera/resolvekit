# How to bring your own data

Resolve against your own entities and attach external data to an existing resolver —
using `Resolver.from_records` and `Resolver.augment`.

## Resolve against your own records

`Resolver.from_records` mints one entity per row and hands you a fully operational
resolver over your data. No database, no server, no schema up front.

The resolved entity ID follows the pattern `<domain>/<id>`:

```
'custom/w1'
'custom/w1'
```

```python
from resolvekit import Resolver

r = Resolver.from_records(
    [{"id": "w1", "label": "Widget", "sku": "abc"},
     {"id": "w2", "label": "Gadget", "sku": "xyz"}],
    domain="custom",     # zero-config standalone domain
    name="label",        # required: which column is the canonical name
    id="id",             # entity-ID seed column (sequential ints if omitted)
    codes=["sku"],       # code columns (list → system name == column name)
)
r.resolve("Widget").entity_id      # 'custom/w1'
r.entity(sku="abc").entity_id      # 'custom/w1'
```

### Column mapping

| Kwarg | What it does | Required? |
|---|---|---|
| `name` | Column whose value becomes the canonical name | Yes |
| `id` | Column to use as the entity-ID seed; sequential ints if omitted | No |
| `codes` | List of column names to expose as code systems, or a `{"system": "column"}` dict | No |
| `aliases` | Column or list of columns holding extra resolvable aliases | No |
| `attrs` | Columns to attach as attributes; `"rest"` keeps all unlisted columns (default drops them) | No |
| `entity_type` | Column name to read the type from each row, or a literal string to stamp on every entity | No |
| `namespace` | Override the entity-ID prefix (defaults to `domain`) | No |

**`codes` — list vs dict form.** Pass a list when the column name is also the system
name you want to query by:

```python
codes=["sku"]           # r.entity(sku="abc")
```

Pass a dict to map an external system name onto a different column:

```python
codes={"iso3": "country_code"}   # r.entity(iso3="KEN")
```

!!! note
    Code lookup via `entity()` is case-insensitive — `r.entity(sku="ABC")` and
    `r.entity(sku="abc")` both match. Store code values in whatever case your data
    uses; resolvekit casefolds on lookup.

### Accepted data forms

`data` (the first positional argument) accepts any of:

- `list[dict]` — one dict per row
- `dict` — mapping of id → record dict
- A file path (string or `Path`) to a CSV, JSON, or JSONL file
- A `pandas.DataFrame` (requires `resolvekit[pandas]`)
- A `polars.DataFrame` (requires `resolvekit[polars]`)

## Attach external data to an existing resolver

`augment` links rows from an external dataset onto a resolver's existing entities,
attaching new codes, aliases, or attributes without rebuilding the resolver.

This example joins per-country GDP figures onto the bundled country entities by ISO-3
code. The base is a single-domain geo resolver (`Resolver.lite()`); rows are matched on
`iso3`, and unmatched rows (here `"ZZZ"`) are skipped:

```
linked=2 minted=0 skipped=1 ambiguous=0
113.4
```

```python
from resolvekit import Resolver

base = Resolver.lite()   # single-domain geo resolver

report = base.augment(
    [{"iso3": "KEN", "gdp_usd_bn": 113.4},
     {"iso3": "UGA", "gdp_usd_bn": 49.3},
     {"iso3": "ZZZ", "gdp_usd_bn": 0.0}],   # ZZZ matches nothing -> skipped
    link_on=["iso3"],      # ordered code systems (or "name") to match on
    add_attrs=["gdp_usd_bn"],  # columns to attach to linked entities
    on_miss="skip",        # "skip" (default) | "mint" | "error"
    return_report=True,    # return AugmentResult; omit to get the resolver directly
)
report.linked, report.minted, report.skipped   # (2, 0, 1)
report.resolver.entity("Kenya").attributes["gdp_usd_bn"]   # 113.4
```

Matching is case-insensitive on code values, so `"KEN"`, `"ken"`, and `"Ken"` all link
to the same entity.

### Augment parameters

| Kwarg | What it does |
|---|---|
| `link_on` | Ordered list of code systems to match on, or `"name"` for canonical-name matching |
| `columns` | `{"role_or_system": "column"}` rename map — use when incoming column names differ from the system names in `link_on` |
| `add_codes` | Columns to register as new code systems on matched entities |
| `add_aliases` | Columns to add as resolvable aliases on matched entities |
| `add_attrs` | Columns to attach as attributes on matched entities |
| `on_miss` | What to do when a row doesn't match: `"skip"` (default), `"mint"` (create a new entity), or `"error"` |
| `return_report` | If `True`, returns an `AugmentResult` instead of the resolver directly |

`AugmentResult` fields: `resolver`, `linked`, `minted`, `skipped`, `ambiguous`, `errors`.

**`link_on="name"`.** Canonical-name matching needs at least one of `add_aliases` or
`add_codes` so augment can identify which column holds the name to match.

**`on_miss="mint"`.** Rows that don't link to an existing entity are minted as new
entities in the same domain. Their count appears in `report.minted`.

!!! warning "Heads up"
    `augment` requires a **single-domain** base resolver — pass `Resolver.lite()`,
    `Resolver.auto(domains=["geo"])`, or a `from_records` base, not a multi-domain
    `Resolver.auto()`. `link_on` accepts **code systems** (`iso3`, `dcid`, `wikidata`, …) and
    the `"name"` sentinel. Code-based linking normalises values case-insensitively (so `"FRA"`,
    `"fra"`, and `"Fra"` all link to the same entity). Name-based linking (`link_on=["name"]`)
    requires at least one of `add_aliases` or `add_codes` to identify the name column, and also
    links case-insensitively.

## Next

- [Resolver reference](../reference/resolver.md) — full parameter listings for
  `from_records` and `augment`.
- [API reference](../reference/api.md) — module-level functions and the `AugmentResult`
  type.
