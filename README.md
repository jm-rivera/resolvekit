# resolvekit

Resolve messy place and entity strings — and codes — to canonical entity IDs, offline and deterministically. Feed it `"Brasil"`, `"Cote dIvoire"`, or `"Republic of Korea"` and get back `country/BRA`, `country/CIV`, `country/KOR`.

- **Offline and deterministic.** No network call, no LLM, no external service at resolution time. The same input gives the same output, today and next year.
- **Countries to cities to organizations.** Resolve countries, UN M.49 regions, continents, sub-national admin levels 1–5, cities, and organizations through one pipeline. Most alternatives stop at countries.
- **Typo- and alias-tolerant.** Exact-code and exact-name matching, full-text search, fuzzy matching, and typo correction, with a calibrated confidence score on every result.
- **Built for tabular data.** `bulk()` cleans a whole pandas or polars column in one call, deduplicating repeated values.
- **A graph, not a lookup table.** List the members of the EU, NATO, or OECD, check membership, convert between code systems, and query it all as of a past date.

## Install

```bash
# with uv
uv add resolvekit                  # Python >= 3.12
uv add "resolvekit[pandas]"        # add the pandas integration for bulk()

# with pip
pip install resolvekit
pip install "resolvekit[pandas]"
```

Country, region, continent, and organization data ships in the wheel and works offline immediately. Sub-national admin levels and cities are fetched on first use — see [the docs](https://jm-rivera.github.io/resolvekit/).

## Quickstart

```python
import resolvekit as rk

rk.resolve_id("United States")        # "country/USA"
rk.resolve("Germany", to="iso3")      # "DEU"
rk.resolve("Japan", to="flag")        # "🇯🇵"
rk.resolve("Tanzania", to="dcid")     # "country/TZA"
```

`to=` pivots a resolved entity to `iso2`, `iso3`, `name`, `flag`, `dcid`, `wikidata`, and other code systems.

Clean a DataFrame column in one call. `bulk()` deduplicates internally, so a 10,000-row column with 50 distinct values runs 50 resolutions, not 10,000:

```python
import pandas as pd
import resolvekit as rk

df = pd.DataFrame({"country": ["United States", "Brasil", "Cote dIvoire", "n/a"]})
df["iso3"] = rk.bulk(values=df["country"], to="iso3")
#       country  iso3
# United States   USA
#        Brasil   BRA
#  Cote dIvoire   CIV
#           n/a  None
```

## What you can do with it

### Every result carries a calibrated confidence score

`confidence` is a calibrated probability, not a raw similarity score — `0.93` means the pipeline estimates roughly a 93% chance the match is correct. A code match and a fuzzy name match are on the same scale:

```python
r = rk.resolve("US")
r.entity_id     # "country/USA"
r.confidence    # 0.951
r.match_tier    # "exact_code"
```

Call `r.explain(verbosity="full").as_text()` for a scorecard of which matchers fired, what they matched, and why this candidate won. It renders to text, Markdown, or JSON.

### It abstains instead of guessing

When two candidates score too close to separate, the result is ambiguous — `confidence` is `None`, and each candidate carries its own score:

```python
r = rk.resolve("Congo")
r.is_ambiguous                          # True
[(c.entity_id, round(c.confidence, 3)) for c in r.candidates[:2]]
# [("country/COD", 0.908), ("country/COG", 0.908)]
```

`resolve_id()` raises `AmbiguousResolutionError` by default; pass `on_ambiguous="null"` for `None` or `"best"` to take the top candidate. Placeholder inputs like `"n/a"` or `"unknown"` short-circuit to no-match before scoring.

### Query the graph — including as of a past date

Entities carry typed, time-aware relations. Ask who belongs to a group, what a region contains, and what either looked like on a given date:

```python
from datetime import date

r = rk.default()

r.members_of("EU", as_codes="iso3")                          # 27 codes
r.is_member("United Kingdom", "EU")                          # False — left in 2020
r.is_member("United Kingdom", "EU", as_of=date(2018, 1, 1))  # True
r.within("Eastern Africa", entity_type="geo.country", to="iso3")
# ['BDI', 'COM', 'DJI', 'ERI', 'ETH', 'KEN', 'MDG', 'MOZ', 'MUS',
#  'MWI', 'MYT', 'RWA', 'SOM', 'SSD', 'SYC', 'TZA', 'UGA', 'ZMB', 'ZWE']
```

`as_of` drops candidates outside their existence window before scoring — it's a hard filter, not a score penalty.

### Extract entities from free text

`parse()` scans text with an Aho-Corasick dictionary pass, then runs the same resolution pipeline on each span. No NER model, no network call (needs `pip install "resolvekit[parsing]"`):

```python
import resolvekit as rk

for e in rk.parse("Leaders from Kenya, Uganda and the United States met to discuss trade."):
    if e.entity_id:
        print(f"{e.surface!r} [{e.start}:{e.end}] -> {e.entity_id} ({e.confidence:.2f})")
# 'Kenya' [13:18] -> country/KEN (0.91)
# 'Uganda' [20:26] -> country/UGA (0.91)
# 'the United States' [31:48] -> country/USA (0.91)
```

`parse_bulk()` runs over a list or Series and tags each span with its source row index.

### Bring your own data

`Resolver.from_records()` builds a resolver from a list of dicts, a DataFrame, or a CSV — no schema, no server:

```python
from resolvekit import Resolver

r = Resolver.from_records(
    [{"id": "w1", "label": "Widget", "sku": "abc"},
     {"id": "w2", "label": "Gadget", "sku": "xyz"}],
    domain="custom", name="label", id="id", codes=["sku"],
)
r.resolve("Widget").entity_id   # "custom/w1"
r.entity(sku="abc").entity_id   # "custom/w1"
```

`Resolver.augment()` joins your own columns onto an existing resolver's entities by code, attaching attributes without a rebuild and reporting what linked, what was minted, and what was skipped.

## How it compares

resolvekit is benchmarked against eight other resolvers on a public, reproducible suite — run it yourself with `uv run python -m benchmarks`. Methodology and per-dataset numbers are in [benchmarks/README.md](https://github.com/jm-rivera/resolvekit/blob/main/benchmarks/README.md); the figures below are from the committed 2026-06-10 run. A dash means the tool was skipped because the dataset is outside its scope, not that it scored zero.

| tool | offline | entity types | `countries_en` | `countries_multilingual` | `admin` | `cities` |
|---|---|---|---|---|---|---|
| **resolvekit** | yes | country, admin1–5, city, continent, org | **0.793** | 0.632 | **0.935** | **0.858** |
| **resolvekit** (typed) | yes | same, with type hints | **0.794** | 0.614 | **0.977** | **0.862** |
| hdx_python_country | yes | country | 0.642 | 0.565 | — | — |
| countryguess | yes | country | 0.675 | 0.512 | — | — |
| country_converter | yes | country | 0.566 | 0.419 | — | — |
| geonamescache | yes | country, city | 0.057 | 0.148 | — | 0.000 |
| rapidfuzz_dict | yes | country | 0.469 | 0.370 | — | — |
| pycountry | yes | country | 0.099 | 0.143 | — | — |
| data_commons_resolve | no | country, admin1–2, city | 0.625 | **0.827** | 0.598 | 0.502 |

The lead is widest on sub-national data. Six of the eight competitors are country-only and can't answer admin or city queries at all. On `cities`, resolvekit scores 0.858 against data_commons_resolve's 0.502 and geonamescache's 0.000; on `admin`, 0.935 against data_commons_resolve's 0.598. resolvekit is also the only tool that emits a calibrated confidence score (ECE 0.043 on the geo eval set).

## How it works

**The data.** resolvekit is built from public authority datasets — [Data Commons](https://datacommons.org/), ISO 3166, the UN M.49 standard, Wikidata, and World Bank/UN statistical groupings. Each entity gets one stable ID (countries reuse the Data Commons dcid, so `country/DEU` is the same key Data Commons uses) plus codes across dozens of systems: ISO 2/3/numeric, Wikidata, GND, VIAF, OpenStreetMap, IOC, and more. Names and codes drift over time; the ID stays fixed. The dataset is compiled into SQLite files that ship on disk, so resolution never makes a network call.

**The graph.** Those entities are nodes in a graph, not rows in a flat code table. A small set of typed, time-aware edges — `member_of`, `contained_in`, `subsidiary_of` — connect them, each carrying a `[valid_from, valid_until)` validity window. That structure answers questions a code-conversion library can't: which countries were in the EU on a given date, what a region contains, which group an organization belongs to. It's a small, fixed graph for entity relations — there's no query language, just the membership and containment methods on `Resolver`.

**Resolution.** A query is normalized, then run through a cascade of matchers, cheapest first — exact code, exact name, full-text search, fuzzy edit distance, then SymSpell typo correction — stopping once a confident match is found. Each candidate is scored by a calibrated model that folds match tier, edit distance, query length, and entity prominence into one confidence value, so a code match and a fuzzy name match sit on the same scale. The result is `resolved` when the top candidate clears the threshold and leads the runner-up by a margin, `ambiguous` when two are too close to separate, and `no_match` when nothing clears it.

Country, region, continent, and organization modules ship in the wheel; sub-national admin levels and cities are separate packs fetched on demand. See [How resolution works](https://jm-rivera.github.io/resolvekit/explanation/how-resolution-works/), [The entity graph](https://jm-rivera.github.io/resolvekit/explanation/knowledge-graph/), and [Offline-first and the data-pack split](https://jm-rivera.github.io/resolvekit/explanation/offline-and-data-packs/).

## Documentation

Full documentation — tutorial, how-to guides, API reference, and design notes — lives at **[jm-rivera.github.io/resolvekit](https://jm-rivera.github.io/resolvekit/)**.

- [Install](https://jm-rivera.github.io/resolvekit/getting-started/install/)
- [Your first resolution](https://jm-rivera.github.io/resolvekit/getting-started/first-resolution/) (tutorial)
- [How-to guides](https://jm-rivera.github.io/resolvekit/how-to/clean-a-dataframe-column/)
- [API reference](https://jm-rivera.github.io/resolvekit/reference/api/)
- [How resolution works](https://jm-rivera.github.io/resolvekit/explanation/how-resolution-works/)
- [Roadmap](https://jm-rivera.github.io/resolvekit/roadmap/)

## License

MIT — see [LICENSE](https://github.com/jm-rivera/resolvekit/blob/main/LICENSE). Bundled data is covered under multiple licenses; see [NOTICE.md](https://github.com/jm-rivera/resolvekit/blob/main/src/resolvekit/NOTICE.md) for third-party data attributions.
