# resolvekit

resolvekit maps messy place and entity strings — and codes — to canonical entity IDs, offline and deterministically. Feed it "Brasil", "Cote dIvoire", or "Republic of Korea" and get back `country/BRA`, `country/CIV`, `country/KOR`.

## Quickstart

=== "uv"

    ```bash
    uv add resolvekit  # Python >= 3.12
    ```

=== "pip"

    ```bash
    pip install resolvekit  # Python >= 3.12
    ```

The three most common operations, results first:

**Resolve a name to a canonical ID:**

```
"country/USA"
```

```python
import resolvekit as rk

rk.resolve_id("United States")
# "country/USA"
```

**Convert between code systems:**

```
"DEU"
```

```python
import resolvekit as rk

rk.resolve("Germany", to="iso3")
# "DEU"
```

**Clean a DataFrame column in one call:**

```
0     USA
1     BRA
2     CIV
3     KOR
4    None
dtype: object
```

```python
import pandas as pd
import resolvekit as rk

df = pd.DataFrame({
    "country": ["United States", "Brasil", "Cote dIvoire", "Republic of Korea", "zzznotacountry"]
})
df["iso3"] = rk.bulk(values=df["country"], to="iso3")
```

!!! note
    `uv add resolvekit[pandas]` (or `pip install resolvekit[pandas]`) adds the pandas integration. The base install works without it; `bulk()` also accepts plain lists. `resolvekit[parsing]` installs `ahocorasick_rs`, required for `parse()` and `parse_bulk()`.

## What you can do

- **Resolve names and codes to canonical IDs.** Inputs can be country names, ISO codes, Wikidata IDs, or Data Commons DCIDs; output is a stable `domain/ID` string like `country/USA`.
- **Convert between representations.** Pivot any input to `iso2`, `iso3`, `name`, `flag`, `dcid`, or any other code system in one call: `rk.resolve("Japan", to="flag")` → `🇯🇵`.
- **Handle typos and aliases.** "Brasil", "Cote dIvoire", and "Republic of Korea" all resolve correctly without pre-cleaning.
- **Clean a whole Series or list with `bulk()`.** Deduplicated internally; unresolved rows get `None` by default. Returns the same type you passed in.
- **Inspect a calibrated confidence score.** Every `ResolutionResult` carries a `confidence` float and a `match_tier`. Call `.explain(verbosity="full")` for a full scorecard.
- **Resolve group membership.** The data is a graph — entities linked by typed relations — so you can list the members of a group (EU, NATO, OECD, and 29 others), check membership, and query it as of a past date: `rk.default().members_of("EU", as_codes="iso3")`.
- **Run fully offline.** Resolution hits no network, no LLM, no external service. The bundled packs ship in the wheel and work immediately after install.
- **Extract entity mentions from free text.** `rk.parse("Leaders from Kenya, Uganda and the United States met in Nairobi")` returns linked entities with character offsets and calibrated confidence — no NER model required. Requires the `[parsing]` extra.
- **Autocomplete a search box.** `Resolver.lite().suggest("germny")` returns ranked, typo-tolerant suggestions (Germany, Greece, …) with match-class and highlight offsets — safe to call per keystroke.
- **List what a region contains.** `rk.default().within("Eastern Africa", entity_type="geo.country", to="iso3")` walks the containment graph and returns every matching descendant. Works for continents, UN M.49 sub-regions (e.g. Western Africa, South-Eastern Asia), and any node in the hierarchy.
- **Bring your own data.** `Resolver.from_records(rows, domain=..., name=..., codes=[...])` stands up a resolver from your records in one call; `resolver.augment(rows, link_on=[...])` attaches extra codes or attributes to existing entities by joining on a shared code system.

Bundled packs cover countries, UN M.49 regions and sub-regions, continents, continental unions, and the bundled org packs. Deeper sub-national admin levels and cities are available as downloadable remote packs (see [Offline use and data packs](explanation/offline-and-data-packs.md)).

## Where to next

- [Install](getting-started/install.md) — extras, data packs, and Python version requirements.
- [Your first resolution](getting-started/first-resolution.md) — a short tutorial that walks through resolve, bulk, ambiguity handling, and confidence.
- [How-to recipes](how-to/convert-between-code-systems.md) — task-focused examples: code conversion, handling ambiguous inputs, using context, and more.
- [Resolve group membership](how-to/resolve-group-membership.md) — list a group's members, check membership, and query it as of a past date.
- [List entities in a region](how-to/list-entities-in-a-region.md) — use `within()` to walk a continent, UN M.49 sub-region, or any containment node and return filtered descendants.
- [Extract entities from text](how-to/extract-entities-from-text.md) — use `parse()` and `parse_bulk()` to find and link entity mentions in free text with character offsets.
- [Build typeahead autocomplete](how-to/build-typeahead-autocomplete.md) — use `suggest()` for ranked, typo-tolerant suggestions with match-class and highlight offsets for a search box.
- [Bring your own data](how-to/bring-your-own-data.md) — stand up a custom resolver from your own records or attach new codes and attributes to existing entities.
- [The entity graph](explanation/knowledge-graph.md) — why resolvekit is graph-backed and what relations it models.
- [Offline use and data packs](explanation/offline-and-data-packs.md) — how bundled vs. remote packs work and when to call `rk.download()`.

---

MIT — see [LICENSE](https://github.com/jm-rivera/resolvekit/blob/main/LICENSE).
