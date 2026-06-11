# `Resolver`

*As of v0.1.*

`Resolver` is the main class in resolvekit. It owns the loaded data packs and exposes every resolution method. The module-level convenience functions (`rk.resolve`, `rk.bulk`, etc.) delegate to a shared singleton; use `Resolver` directly when you need lifecycle control, isolated configuration, or multiple resolvers with different module sets.

```python
from resolvekit import Resolver
```

## Constructors

All four constructors are class methods with keyword-only arguments. They share a common set of tuning options described in [Shared options](#shared-options) below.

---

### `Resolver.auto()`

Loads every installed module across all domains (`geo` and `org` by default).

```python
r = Resolver.auto()
r.domains  # ['geo', 'org']
```

Pass `domains=` to restrict by domain:

```python
r = Resolver.auto(domains=["geo"])
r.domains  # ['geo']
```

Like bare `Resolver.auto()`, the `domains=` form loads only the modules whose data is available locally — remote tiers you haven't downloaded (the admin and cities packs) are skipped, not fetched. For a fixed country-level geo resolver with the smallest footprint, use [`Resolver.lite()`](#resolverlite) instead.

---

### `Resolver.lite()`

Loads only the four country-level geo modules: `geo.countries`, `geo.regions`, `geo.continents`, `geo.continental_unions`. Skips the larger admin-tier and cities dictionaries.

```python
r = Resolver.lite()
r.domains  # ['geo']
```

Use this when startup time or resident memory matters and country-level resolution is sufficient. The SymSpell fuzzy index still builds lazily on the first fuzzy query, so exact-name and code resolution carries no additional overhead.

To extend the lite set with admin-1 coverage:

```python
r = Resolver.lite(module_ids=["geo.countries", "geo.admin1"])
```

!!! note
    `geo.admin1` is a remote module (~12 MB). Call `rk.download("geo.admin1")` first on a fresh install.

---

### `Resolver.from_modules(module_ids=)`

Loads a specific list of installed modules.

```python
# country/DEU   0.91
r = Resolver.from_modules(module_ids=["geo.countries"])
result = r.resolve("Germany")
result.entity_id   # "country/DEU"
result.confidence  # 0.9078...
result.status      # <ResolutionStatus.resolved: 'resolved'>
```

Pass `module_ids=None` to load all installed modules (same as `auto()`).

---

### `Resolver.from_datapacks(datapack_paths=)`

Loads modules from explicit filesystem paths instead of installed packages. Intended for custom or development builds.

```python
r = Resolver.from_datapacks(datapack_paths=["/data/custom-geo-pack"])
```

Each path must point to a directory containing a `metadata.json` file.

---

## Shared options

Every constructor accepts these keyword arguments:

| Option | Type | Default | Description |
|---|---|---|---|
| `routing_mode` | `RoutingMode` | `AUTO` | How queries are dispatched across packs. |
| `cache_size` | `int` | `1024` | LRU result cache entries. `0` disables the cache. |
| `confidence_threshold` | `float | None` | `None` | Override the minimum score to resolve. `None` uses each pack's default (~0.70). |
| `default_timeout` | `float | None` | `None` | Default per-call timeout in seconds. `None` means no limit. |
| `sentinel_blocklist` | `SentinelBlocklist | None` | `DEFAULT_BLOCKLIST` | Junk-input blocklist. `None` disables it. |
| `default_to` | `str | list[str] | None` | `None` | Default output code system or name variant applied to every `resolve()`, `bulk()`, and `snap()` call. A string (`"iso3"`) or a list for a fallback chain (`["iso3", "name"]`). `None` = return raw `ResolutionResult` (default behavior). |
| `on_missing` | `Literal["raise", "null", "auto"]` | `"auto"` | Miss policy when the default output chain has no value for a resolved entity. `"auto"` = raise for scalar `resolve()`/`snap()`, null + `UserWarning` for `bulk()`; `"raise"` = always raise `OutputMissingError`; `"null"` = always return `None`. |

!!! warning "Heads up"
    The LRU cache is not thread-safe. For concurrent workloads, either build one `Resolver` per worker thread or pass `cache_size=0`.

    ```python
    # ✅ One resolver per worker
    def worker():
        r = Resolver.auto()
        ...

    # ✅ Shared resolver, cache disabled
    r = Resolver.auto(cache_size=0)
    ```

**`confidence_threshold`** — A `NO_MATCH` result caused by a score below the threshold still carries `result.confidence` equal to the top candidate's calibrated score. This lets you distinguish a near-miss (`confidence=0.66`) from a true no-candidate (`confidence=None`).

**`sentinel_blocklist`** — Inputs like `"unknown"`, `"n/a"`, and `"null"` return `NO_MATCH` without running the pipeline. Extend the defaults:

```python
from resolvekit import SentinelBlocklist

blocklist = SentinelBlocklist(extra={"tbd", "missing"})
r = Resolver.auto(sentinel_blocklist=blocklist)
```

Disable entirely with `sentinel_blocklist=None`.

---

## Lifecycle

`Resolver` supports the context manager protocol. Use it when you want guaranteed cleanup.

```python
with Resolver.from_modules(module_ids=["geo.countries"]) as r:
    entity_id = r.resolve_id("Nigeria")  # "country/NGA"
# r is closed here
```

`close()` releases the underlying SQLite stores. It's idempotent — calling it twice is safe. Calling `resolve()` after `close()` raises `RuntimeError`.

---

## Methods

### `resolve(text, *, to=UNSET, as_result=False, domain=None, context=None, from_system=None, include_entity=False, timeout=None)`

Resolves a single string.

**Parameters**

- **`text`** (`str`) — The text or code to resolve. Required.
- **`to`** (`str | type[EntityRecord] | None`, default: `UNSET`) — Controls the return type. `UNSET` (omitted) activates the resolver's configured `default_to` spec when set, or returns a raw `ResolutionResult` when no default is configured. `None` (explicit) always returns a `ResolutionResult`. A code system name (`"iso3"`, `"dcid"`) returns that code string. An attribute name (`"flag"`, `"name"`) returns that attribute. `EntityRecord` returns the full entity object. A per-call `to=` overrides any configured `default_to`.
- **`as_result`** (`bool`, default: `False`) — Return the full `ResolutionResult` even when a `default_to` is configured — equivalent to `to=None`. Raises `ValueError` when combined with an explicit non-`None` `to=`.
- **`domain`** (`str | list[str] | None`, default: `None`) — Route to a specific domain (`"geo"`) or list of domains. Requires `routing_mode=RoutingMode.EXPLICIT`; with the default `AUTO` mode, passing `domain=` raises `ValueError`. To scope resolution without EXPLICIT routing, load fewer modules instead (`from_modules` / `auto(domains=...)`).
- **`context`** (`ResolutionContext | None`, default: `None`) — Resolution context. When `as_of` is set inside it, acts as a hard point-in-time filter: entities outside their `[valid_from, valid_until)` window are dropped. With no `as_of` set, context is a no-op on temporal filtering.
- **`from_system`** (`str | None`, default: `None`) — Treat the input as a code in this system. Accepts any system known to the loaded packs (`code_systems()` lists them); common ones are `"iso2"`, `"iso3"`, `"iso_numeric"`, `"dcid"`, `"wikidata"`. An unknown system raises `UnknownCodeSystemError`. Skips name resolution.
- **`include_entity`** (`bool`, default: `False`) — Populate `result.entity` with the full `EntityRecord`. When `to=` is set or a default spec is active, this is forced `True` internally. Note: the module-level `rk.resolve()` defaults this to `True` for notebook ergonomics; `Resolver.resolve()` defaults to `False`.
- **`timeout`** (`float | None`, default: `None`) — Per-call limit in seconds. Overrides `default_timeout`. Must be positive if set.

**Returns**

- `to=UNSET` + no `default_to` configured → `ResolutionResult`.
- `to=UNSET` + `default_to` configured → `str | None` (pivoted output, or raise/null per `on_missing`).
- `to=None` or `as_result=True` → `ResolutionResult`.
- `to="iso3"` (or any scalar code/attribute) → `str | None`.
- `to=EntityRecord` → `EntityRecord | None`.

**Raises**

- **`AmbiguousResolutionError`** — When `to=` is set and the result is ambiguous.
- **`OutputMissingError`** — When a `default_to` spec is active and the entity lacks the requested output under `on_missing="raise"` (or `"auto"` for scalar calls).
- **`UnknownCodeSystemError`** — When `to=` names a code system or attribute that no loaded pack carries.
- **`ValueError`** — When `as_result=True` is combined with an explicit `to=`, or when `timeout <= 0`.
- **`RuntimeError`** — When the resolver has been closed.

!!! note
    `resolve_id()` and `require_id()` always return the entity ID string regardless of any configured `default_to`. The bound output spec has no effect on those methods.

---

### `to(output, *, on_missing="auto")` { #resolver-to }

```python
r.to(
    output: str | list[str],
    *,
    on_missing: Literal["raise", "null", "auto"] = "auto",
) -> OutputView
```

Return an `OutputView` bound to `output`. All resolution calls through the view apply the output spec automatically.

**Parameters**

- **`output`** (`str | list[str]`) — Target code system or name variant (e.g. `"iso3"`, `["iso3", "name"]`, `"name:fr"`). The name grammar accepts `name`, `name:<lang>`, `name:<kind>`, and optionally `name:<kind>:<script>`. `<kind>` ∈ {`canonical`, `alias`, `endonym`, `exonym`, `acronym`} (`abbr` is accepted as an alias for `acronym`). Kind tokens resolve only for packs that carry the corresponding name kind; the bundled packs provide canonical names, per-language names (`en`, `fr`, `es`, `de`, `ru`, `ja`, `it`, `pt`, `zh`, `ar`), and aliases. Required.
- **`on_missing`** (`"raise" | "null" | "auto"`, default: `"auto"`) — Miss policy. `"auto"` = raise for scalar, null + `UserWarning` for bulk; `"raise"` = always raise `OutputMissingError`; `"null"` = always return `None`.

**Returns** — `OutputView`.

**Raises**

- **`UnknownOutputError`** — When `output` contains a malformed token or names an unknown code system.

**Example**

```python
from resolvekit import Resolver

r = Resolver.from_modules(module_ids=["geo.countries"])
iso3 = r.to("iso3")

iso3.resolve("France")           # → "FRA"
iso3.resolve_id("France")        # → "country/FRA"  (entity ID, not pivoted)
iso3.bulk(values=["France", "Germany"])  # → ["FRA", "DEU"]
iso3.snap(query="Tanzanya", candidates=["country/TZA", "country/ZMB"])  # → "TZA"
```

See also [`OutputView`](api.md#outputview) for the full method list.

---

### `resolve_id(text, *, on_ambiguous="raise", from_system=None, domain=None, context=None, timeout=None)`

Resolves text and returns the entity ID string, or `None`.

**Parameters**

- **`text`** (`str`) — Text to resolve. Required.
- **`on_ambiguous`** (`"raise" | "null" | "best"`, default: `"raise"`) — Controls what happens when the input matches multiple entities. `"raise"` raises `AmbiguousResolutionError`. `"null"` returns `None`. `"best"` returns the top candidate's entity ID.
- **`from_system`** (`str | None`, default: `None`) — Force code-system lookup. Same semantics as `resolve()`.
- **`domain`**, **`context`**, **`timeout`** — Same as `resolve()`.

**Returns** — Entity ID string (`"country/DEU"`), or `None` on no match or ambiguity (`on_ambiguous="null"`).

**Raises**

- **`AmbiguousResolutionError`** — When `on_ambiguous="raise"` and the input is ambiguous. The exception carries `.candidates`.
- **`ResolutionError`** — When the pipeline errored.

**Example**

```python
# "country/KOR"   "country/COD"   None
r.resolve_id("South Korea")
r.resolve_id("Congo", on_ambiguous="best")
r.resolve_id("Congo", on_ambiguous="null")
```

---

### `require_id(text, *, domain=None, context=None)`

Like `resolve_id()`, but raises instead of returning `None`.

**Returns** — Entity ID string. Guaranteed non-None.

**Raises**

- **`AmbiguousResolutionError`** — When resolution is ambiguous.
- **`ResolutionError`** — For any non-resolved result (no match, error).
- **`RuntimeError`** — When the resolver has been closed.

Use this when a missing match should be treated as a pipeline error rather than handled inline.

---

### `bulk(*, values, to=UNSET, on_missing=UNSET, output="series", domain=None, context=None, from_system=None, not_found="null", on_error="raise", on_ambiguous="null")`

Resolves a collection of values.

**Parameters**

- **`values`** — Input collection: `pd.Series`, `pl.Series`, `numpy.ndarray`, `list`, or `tuple`. Required.
- **`to`** — Explicit pivot target. `UNSET` (omitted) activates the resolver's configured `default_to` spec when set. `None` forces a raw `BulkResult`. A scalar code or attribute name returns the native shape directly.
- **`on_missing`** (`"raise" | "null" | "auto" | UNSET`, default: `UNSET`) — Miss policy override for the output spec. `UNSET` inherits the spec's configured `on_missing` policy. `"raise"` aborts the batch on the first resolved-but-missing entity; `"null"` returns `None` per row silently; `"auto"` returns `None` with a `UserWarning`. Only relevant on the spec path.
- **`output`** (`"series" | "record" | "frame"`, default: `"series"`) — Output shape when `to=None`. Ignored when `to=` is a scalar.
- **`domain`** — Optional domain filter.
- **`context`** (`ResolutionContext | None`) — Broadcast to every row.
- **`from_system`** — Force code-system interpretation for all inputs.
- **`not_found`** (`"null" | "raise" | str`, default: `"null"`) — What to do when a value has no match. `"null"` → `None`. `"raise"` → `ValueError`. Any other string is used as a literal sentinel in the output.
- **`on_error`** (`"raise" | "null" | "keep"`, default: `"raise"`) — What to do on pipeline errors.
- **`on_ambiguous`** (`"null" | "raise" | "best"`, default: `"null"`) — What to do on ambiguous inputs.

**Returns** — Native shape (e.g. `pd.Series`) when `to=` is scalar or a `default_to` spec is active; `BulkResult` otherwise.

Identical inputs are deduplicated automatically — each unique value is resolved once.

**Example**

```python
import pandas as pd

# pd.Series(["DEU", "FRA", "NGA", None])
r.bulk(
    values=pd.Series(["Germany", "France", "Nigeria", "zzznotacountry"]),
    to="iso3",
)
```

---

### `snap(*, query, candidates, max_distance=0.5, to=UNSET, domain=None, context=None)`

Returns the closest match among `candidates`, or `None` when nothing clears the threshold.

**Parameters**

- **`query`** (`str`) — The string to match. Required.
- **`candidates`** (`list[str]`) — Entity IDs or free-text labels to match against. Required.
- **`max_distance`** (`float`, default: `0.5`) — Confidence floor. Results below this return `None`.
- **`to`** — Optional pivot (same semantics as `resolve()`).
- **`domain`**, **`context`** — Optional filters.

**Returns** — The matching candidate (entity ID or pivoted form), or `None`.

**Example**

```python
# "country/DEU"
r.snap(
    query="Allemagne",
    candidates=["country/DEU", "country/FRA", "country/AUT"],
)
```

!!! warning "Heads up"
    `snap` matches the query against each candidate by resolving both sides, so candidate strings must be resolvable. Entity IDs (`"country/DEU"`) work reliably. Free-text labels work when they resolve without ambiguity.

---

### `suggest(prefix, *, top_k=10, domain=None, entity_type=None, context=None, to=None, fuzzy="auto", timeout=None)` { #resolversuggest }

Returns a ranked typeahead suggestion list for `prefix`. Built for per-keystroke autocomplete: it bypasses the resolve pipeline and the query cache, never raises a thresholded verdict, and returns `[]` for empty, whitespace-only, or below-floor prefixes. This method exists only on `Resolver` — there is no module-level `rk.suggest()`.

**Parameters**

- **`prefix`** (`str`) — Partial query string. Truncated to the resolver's max query length before normalization. Required.
- **`top_k`** (`int`, default: `10`) — Maximum suggestions to return. Clamped to `[1, 100]`.
- **`domain`** (`str | list[str] | None`, default: `None`) — Pack filter by simple domain name (`"geo"`, `"org"`). A dotted value like `"geo.country"` raises `ValueError` — pass it via `entity_type=` instead.
- **`entity_type`** (`str | list[str] | None`, default: `None`) — Entity-type prefix filter (`"geo.country"`, `["geo.country", "geo.region"]`).
- **`context`** (`ResolutionContext | None`, default: `None`) — Accepted but ignored in this cut; reserved for future caller hints.
- **`to`** (`str | list[str] | None`, default: `None`) — Output code system or name variant for the `display` field, same grammar as `resolve(to=...)` and [`Resolver.to()`](#resolver-to) (`"iso3"`, `"name:fr"`). Overrides any configured `default_to` for this call. `None` renders `display` from the `canonical_name`. Output misses are coerced to `None` (`on_missing="null"`) and never raised, even on a resolver built with `on_missing="raise"`.
- **`fuzzy`** (`"auto" | "always" | "never"`, default: `"auto"`) — Fuzzy-matching policy. `"auto"` runs fuzzy on tiers with at most 25,000 eligible names, excluding the denylisted `geo.city` and `geo.admin2`–`geo.admin5` (those still get exact/prefix matching). `"always"` forces fuzzy regardless of the gate. `"never"` does prefix/infix only.
- **`timeout`** (`float | None`, default: `None`) — Per-call time budget in seconds. Exceeding it returns partial results rather than raising. `None` = no limit.

**Returns** — `list[SuggestionResult]`, sorted best-first (see [`SuggestionResult`](api.md#suggestionresult)), length at most `top_k`. Never a verdict; an empty list means no suggestions.

**Raises**

- **`ValueError`** — When `domain` contains a dotted name, or `to=` names an unknown code system (an `UnknownOutputError`, which subclasses `ValueError`).
- **`RuntimeError`** — When the resolver has been closed.

**Example**

```python
from resolvekit import Resolver

r = Resolver.lite()

# Prefix match, ranked best-first:
for s in r.suggest("unit", top_k=3):
    print(s.canonical_name, s.entity_id, s.match_class.value)
# United States   country/USA   exact_prefix
# Mexico          country/MEX   exact_prefix
# United Kingdom  country/GBR   exact_prefix

# Typo-tolerant under fuzzy="auto":
for s in r.suggest("germny", top_k=2):
    print(s.canonical_name, s.match_class.value, s.fuzzy_score)
# Germany   fuzzy   83.33333333333334
# Greece    fuzzy   80.0

# Filter to countries and render display as ISO-3:
for s in r.suggest("united", top_k=3, entity_type="geo.country", to="iso3"):
    print(s.display, s.highlight_ranges)
# USA   []
# MEX   []
# GBR   []
```

!!! note
    `suggest()` ranks by a cascade — `match_class`, then whole-name matches (the query equals the name in full, so typing an acronym like `"EU"` or `"NATO"` surfaces that entity first), then typo count, then prominence (where the tier carries it), then name length. `SuggestionResult.ranking_quality` reports `"ranked"` for tiers with prominence data — `geo.country` and the region tiers (`geo.subregion`, `geo.region`, `geo.continental_union`); continents, organizations, and the admin/city tiers are `"unranked"` (match-class + alphabetical order). See [`SuggestionResult`](api.md#suggestionresult) and [`MatchClass`](api.md#matchclass).

!!! warning "Heads up"
    `highlight_ranges` offsets are Unicode **code-point** offsets into `display`, not UTF-16. JavaScript strings are UTF-16; convert before slicing in the browser, or a span past a non-BMP character lands wrong. Fuzzy matches and alias-only matches return an empty `highlight_ranges`.

See [How to build typeahead autocomplete](../how-to/build-typeahead-autocomplete.md) for end-to-end recipes.

---

### `entity(text_or_id=None, *, iso2=None, iso3=None, dcid=None, alpha_2=None, alpha_3=None, numeric=None, domain=None, **code_kwargs)`

Looks up a fully hydrated `EntityRecord` by text, entity ID, or code.

Resolution order: (1) code kwarg if provided, (2) entity ID if `text_or_id` looks like `"domain/Value"`, (3) free-text resolution.

**Returns** — `EntityRecord | None`.

**Raises**

- **`ValueError`** — When more than one code-system kwarg is provided.
- **`AmbiguousResolutionError`** — When the lookup matches multiple entities.
- **`RuntimeError`** — When the resolver has been closed.

**Example**

```python
r.entity("France")            # by name
r.entity("country/FRA")       # by entity ID
r.entity(iso2="DE")           # by ISO 3166-1 alpha-2
r.entity(wikidata="Q30")      # by any code system
```

---

### `members_of(group, *, as_of=None, as_codes=None)`

Returns the members of a named group.

**Parameters**

- **`group`** (`str`) — Group name, abbreviation, or entity ID. Accepts the same forms as `resolve()`: `"EU"`, `"European Union"`, `"NATO"`, `"G20"`, `"EU-27"`.
- **`as_of`** (`date | None`, default: today) — Reference date for membership lookup. Has no effect on snapshot groups (e.g. `"BRIC"`, `"BRICS"`, `"European Union (28 members, 2013–2020)"`) and emits a `UserWarning` when passed for one.
- **`as_codes`** (`str | None`, default: `None`) — Return code values instead of entity IDs. Pass a code system name: `"iso3"`, `"iso2"`. The result may be shorter than the entity-ID form when entities lack that code.

**Returns** — Sorted list of member entity IDs, or code strings when `as_codes=` is set.

**Raises**

- **`GroupNotFoundError`** — Group does not resolve to any entity.
- **`AmbiguousResolutionError`** — Group resolves ambiguously.
- **`UnknownCodeSystemError`** — `as_codes` names an unrecognized code system.
- **`RuntimeError`** — When the resolver has been closed.

**Example**

```python
# 27 entity IDs: ['country/AUT', 'country/BEL', ...]
r.members_of("EU")

# 27 ISO-3 codes: ['AUT', 'BEL', ...]
r.members_of("EU", as_codes="iso3")
```

---

### `is_member(country, group, *, as_of=None)`

Checks whether `country` is a member of `group` on the reference date.

**Returns** — `bool`.

**Raises** — `GroupNotFoundError`, `AmbiguousResolutionError`, `RuntimeError`.

```python
r.is_member("Germany", "EU")   # True
r.is_member("Norway", "EU")    # False
```

---

### `known_groups()`

Returns canonical names of all queryable group entities, sorted.

**Returns** — `list[str]` of canonical names (e.g. `["African Union", "Association of Southeast Asian Nations", "BRIC", "BRICS", "European Union", ...]`). Acronyms like `"ASEAN"` or `"NATO"` are accepted as input to other methods but are not what `known_groups()` returns.

The list is built from entity types declared by each loaded pack; there's no hardcoded type set. The count depends on which modules are loaded.

---

### `related(entity_or_id, *, relation=None, as_of=None, to=None)`

Follow an entity's relation edges and return the resolved target entities, deduped, in edge order.

**Parameters**

- **`entity_or_id`** (`str | EntityRecord`) — The entity whose relations to traverse. An `EntityRecord` is used directly. A string is matched by exact entity ID (e.g. `"country/DEU"`) then by exact name or alias — deterministic, never fuzzy.
- **`relation`** (`str | None`, default: `None`) — Filter to a specific edge type (`"contained_in"`, `"member_of"`, `"subsidiary_of"`). `None` follows all edge types.
- **`as_of`** (`date | None`, default: `None`) — Hard point-in-time filter: only include edges whose validity window `[valid_from, valid_until)` contains this date. `None` returns all edges regardless of time.
- **`to`** (`str | None`, default: `None`) — Pivot each resolved entity to a code or attribute (e.g. `"iso3"`, `"name"`). Must be a scalar pivot; passing a list-valued system like `"aliases"` raises `UnknownCodeSystemError`. When set the return type changes to `list[str | None]`.

**Returns** — `list[EntityRecord]` when `to=None`; `list[str | None]` when `to=` is set. Edges whose `target_id` cannot be resolved are omitted. Duplicates are deduplicated by resolved entity ID, preserving first-seen edge order.

**Raises**

- **`EntityNotFoundError`** — String `entity_or_id` matches no entity.
- **`AmbiguousResolutionError`** — String `entity_or_id` matches more than one entity by exact name.
- **`UnknownCodeSystemError`** — `to=` names an unknown or non-scalar system.
- **`RuntimeError`** — When the resolver has been closed.

**Example**

```python
from resolvekit import Resolver, EntityNotFoundError

r = Resolver.lite()
germany = r.entity("Germany")

# EntityRecord input
parents = r.related(germany, relation="contained_in")
[p.canonical_name for p in parents]
# ['Development Assistance Committee Countries',
#  'Development Assistance Committee  Members',
#  'European Union',
#  'Organisation for Economic Co-operation and Development (OECD)',
#  'Western Europe']

# String input — same result
parents = r.related("Germany", relation="contained_in")

# Pivot to ISO-3 codes
codes = r.related("Germany", relation="contained_in", to="iso3")
# [None, None, None, None, None]  (group entities don't carry iso3)

# Unknown entity raises, not silent empty
try:
    r.related("NoSuchPlaceXYZ")
except EntityNotFoundError:
    pass
```

---

### `within(container, *, entity_type=None, recursive=True, max_depth=None, as_of=None, to=None)`

Walk the containment graph and return entities geographically contained in `container`. Returns descendants — not the container node itself.

**Parameters**

- **`container`** (`str | EntityRecord`) — The region to walk. A string is matched by exact entity ID then by exact name or alias — deterministic, never fuzzy. When a name matches both a geographic hierarchy node and a same-named statistical aggregate, `within()` prefers the geographic node.
- **`entity_type`** (`str | list[str] | None`, default: `None`) — Filter the **output** to this entity type only. Intermediate nodes are still traversed regardless of their type. Pass `"geo.country"` to collect countries, `"geo.subregion"` for UN M.49 sub-regions. `None` returns all descendant types.
- **`recursive`** (`bool`, default: `True`) — When `True`, traverses the full containment subtree. When `False`, returns only direct children.
- **`max_depth`** (`int | None`, default: `None`) — Cap traversal depth. `None` means no limit.
- **`as_of`** (`date | None`, default: `None`) — Hard point-in-time filter on containment edges. `None` returns all edges regardless of time — `within()` does **not** default to today (unlike `members_of()`).
- **`to`** (`str | None`, default: `None`) — Pivot each result to a scalar code or attribute (e.g. `"iso3"`, `"name"`). When set, the return type changes to `list[str | None]`.

**Returns** — `list[EntityRecord]` when `to=None`; `list[str | None]` when `to=` is set.

**Raises**

- **`EntityNotFoundError`** — `container` matches no entity.
- **`AmbiguousResolutionError`** — `container` matches more than one entity by exact name.
- **`UnknownCodeSystemError`** — `to=` names an unknown or non-scalar system.
- **`RuntimeError`** — When the resolver has been closed.

!!! note
    `geo.region` means **statistical aggregates** (LDCs, SIDS, development groups). `geo.subregion` means **UN M.49 geographic sub-regions** (Western Africa, Western Europe, …) with IDs like `m49/155`. These are distinct types; query them with the correct `entity_type=` string.

**Example**

```python
from resolvekit import Resolver

r = Resolver.auto()  # or Resolver.lite() for country-level geo only

# The UN M.49 sub-regions of Africa:
[e.canonical_name for e in r.within("Africa", entity_type="geo.subregion")]
# ['Western Africa', 'Eastern Africa', 'Northern Africa', 'Middle Africa',
#  'Southern Africa', 'Sub-Saharan Africa']

# Countries in a sub-region, as ISO 3166-1 alpha-3 codes:
r.within("Eastern Africa", entity_type="geo.country", to="iso3")
# ['BDI', 'COM', 'DJI', 'ERI', 'ETH', 'KEN', 'MDG', 'MOZ', 'MUS',
#  'MWI', 'MYT', 'RWA', 'SOM', 'SSD', 'SYC', 'TZA', 'UGA', 'ZMB', 'ZWE']

# Every country on a continent:
len(r.within("Africa", entity_type="geo.country", to="iso3"))   # 57

# Get the sub-region node itself — within() returns descendants, not the node:
e = r.entity("Western Europe")   # EntityRecord, entity_id 'm49/155', type 'geo.subregion'
r.within("Western Europe", entity_type="geo.subregion")   # [] — no sub-region children
r.within("Western Europe", entity_type="geo.country")     # countries in Western Europe
```

!!! note
    `within()` is available only on `Resolver` instances. There is no module-level `rk.within()`. Call it via `rk.default().within(...)` when you need a one-off call without constructing a resolver explicitly.

---

### `diagnostics.unresolved_relations(entity_or_id, *, relation=None)` { #diagnostics-unresolved-relations }

Return relation edges whose `target_id` does not resolve in the currently loaded packs.

This is a diagnostics method, not a traversal method. It surfaces dangling edges — targets that exist in the data but aren't loaded or weren't canonicalized. All edges (including temporally expired ones) are reported; filter on `valid_until` yourself if needed.

**Parameters**

- **`entity_or_id`** (`str | EntityRecord`) — The entity to inspect. Resolved the same deterministic way as `related()`.
- **`relation`** (`str | None`, default: `None`) — Restrict to a specific edge type. `None` returns all types.

**Returns** — `list[dict[str, object]]`. Each dict has keys `"relation_type"`, `"target_id"`, `"valid_from"`, `"valid_until"`.

**Raises** — `EntityNotFoundError`, `AmbiguousResolutionError`, `RuntimeError` (same conditions as `related()`).

**Example**

```python
from resolvekit import Resolver

# On a complete resolver, nothing dangles:
r = Resolver.lite()
r.diagnostics.unresolved_relations("Germany", relation="contained_in")
# []

# Load a partial pack set and edges into the missing packs surface. Here
# geo.regions is loaded without geo.continents, so Western Europe's
# containment edge points at a continent that isn't present:
p = Resolver.from_modules(module_ids=["geo.regions"])
dangling = p.diagnostics.unresolved_relations("m49/155", relation="contained_in")  # Western Europe
for edge in dangling:
    print(edge["relation_type"], edge["target_id"])
# contained_in wikidataId/Q46
```

!!! info "Why"
    Dangling edges reflect targets that are not present in or were not loaded into the current pack set. Whether an edge resolves depends on which modules are loaded and how the data build populated the target IDs. `unresolved_relations` surfaces exactly which edges are affected.

---

### `resolve_explained(text, *, domain=None, context=None, verbosity="standard", timeout=None)`

Resolves with full tracing and returns an `ExplainedResolution`. Backs `result.explain()`.

**Parameters**

- **`verbosity`** (`"minimal" | "standard" | "full"`, default: `"standard"`) — Detail level for the explanation.

**Returns** — `ExplainedResolution` with a `.result` attribute (a `ResolutionResult`) and a scorecard.

Prefer calling `result.explain()` on a `ResolutionResult` you already have over calling this directly.

---

### `resolve_detailed(text, *, domain=None, context=None, timeout=None)`

Resolves and returns a raw `PipelineResult` instead of a `ResolutionResult`.

**Returns** — `PipelineResult` with `.result`, `.candidates`, and `.pack_id`. Use when you need the unfiltered candidate list or pack-level metadata.

---

## Properties

### `domains`

`list[str]` — Sorted domain pack IDs loaded by this resolver.

```python
Resolver.auto().domains   # ['geo', 'org']
Resolver.lite().domains   # ['geo']
```

---

### `info`

`ResolverInfo` — Structured metadata about this resolver instance.

```python
r.info.data_version         # "2026.06"
r.info.resolvekit_version   # "0.1.2"
r.info.domains              # ("geo", "org")
r.info.routing_mode         # "auto"
r.info.closed               # False
r.info.cache                # CacheInfo(hits=..., misses=..., maxsize=1024, currsize=...)
```

---

### `diagnostics`

Debugging namespace. Not for production resolution.

**`diagnostics.inspect(text, *, domain=None)`** — Returns an `InspectionReport` showing exact code matches, exact name matches, and top-5 fuzzy candidates, unfiltered by the confidence threshold. Useful when a query resolves unexpectedly.

**`diagnostics.search(text, *, top_k=10, domain=None, context=None)`** — Runs the full pipeline without the decision step. Returns a `list[CandidateSummary]` ordered by confidence, bypassing the cache.

**`diagnostics.unresolved_relations(entity_or_id, *, relation=None)`** — Returns relation edges whose `target_id` does not resolve in the loaded packs. See [`diagnostics.unresolved_relations`](#diagnostics-unresolved-relations) for the full contract.

**`diagnostics.cache.info()`** — Returns `CacheInfo(hits, misses, maxsize, currsize)`, or `None` when `cache_size=0`.

**`diagnostics.cache.clear()`** — Evicts all cache entries and resets hit/miss counters. No-op when the cache is off.

```python
r.diagnostics.inspect("Germany")
r.diagnostics.search("Ger", top_k=3)
r.diagnostics.unresolved_relations("Germany", relation="contained_in")
r.diagnostics.cache.info()   # CacheInfo(hits=0, misses=0, maxsize=1024, currsize=0)
r.diagnostics.cache.clear()
```

---

### `code_systems()`

`frozenset[str]` — All code system names known to the loaded packs (e.g. `"iso3"`, `"iso2"`, `"dcid"`, `"wikidata"`).

---

### `available_entity_types()`

`frozenset[str]` — All entity type prefixes declared by the loaded packs.

---

## Next

[Module-level API](api.md) — The convenience functions (`rk.resolve`, `rk.bulk`, `rk.entity`, etc.) that delegate to a shared singleton `Resolver`. Prefer these in notebooks and one-off scripts.

[Offline-first and data packs](../explanation/offline-and-data-packs.md) — Why resolution is local-only, how bundled and remote modules differ, and how to control the install footprint.
