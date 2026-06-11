# Module-level API

*As of v0.1.*

The functions below are the primary entry point for most use cases. They share a singleton [`Resolver`](resolver.md) created on first call — you don't instantiate anything. Import convention throughout this reference:

```python
import resolvekit as rk
```

!!! warning "Heads up"
    These module-level functions run on a shared `Resolver` built with the default
    `AUTO` routing mode, where the per-call `domain=` argument raises `ValueError`.
    To restrict resolution to one domain, build a resolver with only the modules you
    need — `Resolver.from_modules(module_ids=["geo.countries"])` or
    `Resolver.auto(domains=["geo"])` — or construct one with
    `routing_mode=RoutingMode.EXPLICIT` to enable per-call `domain=`. See the
    [`Resolver` reference](resolver.md).

!!! note
    **`within()`, `members_of()`, `is_member()`, `related()`, and `known_groups()`** are not module-level functions. Call them on a `Resolver` instance: `rk.default().within(...)`, or build one with `Resolver.auto()`. See the [`Resolver` reference](resolver.md).

---

## Functions { #functions }

### `resolve` { #resolve }

```python
rk.resolve(
    text: str,
    *,
    to: str | None = UNSET,
    as_result: bool = False,
    domain: str | list[str] | None = None,
    context: ResolutionContext | None = None,
    from_system: str | None = None,
    include_entity: bool = True,
    timeout: float | None = None,
) -> ResolutionResult | Any
```

Resolve a text string or code against all loaded modules.

**Parameters**

| Name | Meaning |
|---|---|
| `text` | The string to resolve. Can be a name, spelling variant, or code. |
| `to` | Pivot the resolved entity to a specific representation. Omit (default) to use the `default_to` configured via [`configure()`](#configure), or return a raw `ResolutionResult` when no default is set. Pass `None` to always return a `ResolutionResult`. When set to a code system name (`"iso3"`, `"iso2"`, `"name"`, `"flag"`, `"aliases"`, `"dcid"`, etc.), returns the pivot value directly. A per-call `to=` overrides the configured default. |
| `as_result` | Return the full `ResolutionResult` even when a `default_to` is configured — equivalent to passing `to=None`. Cannot be combined with an explicit `to=`. |
| `domain` | Restrict resolution to one or more domains (`"geo"`, `"org"`, or a list). |
| `context` | A [`ResolutionContext`](#resolutioncontext) with hints (entity type, parent, country, language). |
| `from_system` | Treat `text` as a code in this system (e.g. `"iso2"`, `"iso3"`, `"dcid"`, `"wikidata"`). Skips name-matching. |
| `include_entity` | Populate `result.entity`. Defaults to `True` at the module level for notebook ergonomics. Set to `False` in pipelines where you don't need the full entity. |
| `timeout` | Maximum seconds before the pipeline is cut short. `None` = no limit. |

**Returns**

- A [`ResolutionResult`](#resolutionresult) when `to=None` or `as_result=True`, or when no `default_to` is configured and `to` is omitted.
- The pivot value directly (typically `str | None`) when `to` is set or a `default_to` is active.

**Example — full result**

```python
>>> rk.resolve("Germany")
ResolutionResult(status='resolved', entity_id='country/DEU', confidence=≈0.91, pack_id='geo')
```

**Example — pivot**

```python
>>> rk.resolve("DE", from_system="iso2", to="flag")
'🇩🇪'
```

---

### `resolve_id` { #resolve-id }

```python
rk.resolve_id(
    text: str,
    *,
    on_ambiguous: Literal["raise", "null", "best"] = "raise",
    from_system: str | None = None,
    domain: str | list[str] | None = None,
    context: ResolutionContext | None = None,
    timeout: float | None = None,
) -> str | None
```

Resolve text and return the entity ID string, or `None` on no match.

**Parameters**

| Name | Meaning |
|---|---|
| `text` | Text or code to resolve. |
| `on_ambiguous` | What to do when multiple entities match. `"raise"` (default) raises [`AmbiguousResolutionError`](#ambiguousresolutionerror); `"null"` returns `None`; `"best"` returns the top candidate's ID. |
| `from_system` | Force input to be interpreted as a code in this system. |
| `domain` | Restrict to one or more domains. |
| `context` | Resolution hints. |
| `timeout` | Maximum seconds. |

**Returns** `str | None` — entity ID, or `None` when no match (or ambiguous with `on_ambiguous="null"`).

**Raises** [`AmbiguousResolutionError`](#ambiguousresolutionerror) when `on_ambiguous="raise"` and the query is ambiguous.

**Example**

```python
>>> rk.resolve_id("United States")
'country/USA'
>>> rk.resolve_id("Cote dIvoire")
'country/CIV'
>>> rk.resolve_id("Congo", on_ambiguous="null")   # ambiguous → None
None
>>> rk.resolve_id("Congo", on_ambiguous="best")
'country/COD'
```

---

### `bulk` { #bulk }

```python
rk.bulk(
    *,
    values: list | tuple | dict | pd.Series | pl.Series | np.ndarray,
    to: str | None = UNSET,
    on_missing: Literal["raise", "null", "auto"] = UNSET,
    domain: str | list[str] | None = None,
    context: ResolutionContext | None = None,
    output: Literal["series", "record", "frame"] = "series",
    from_system: str | None = None,
    not_found: str = "null",
    on_error: Literal["raise", "null", "keep"] = "raise",
    on_ambiguous: Literal["null", "raise", "best"] = "null",
    crosswalk: Crosswalk | None = None,
) -> Any
```

Resolve a collection of values. Identical inputs are deduplicated automatically before the pipeline runs, so repeated values don't multiply the work.

See [how to clean a DataFrame column](../how-to/clean-a-dataframe-column.md) for the automatic path, and [how to reconcile a column with a review](../how-to/reconcile-a-column-with-review.md) for the [`Crosswalk`](#crosswalk) round-trip.

**Parameters**

| Name | Meaning |
|---|---|
| `values` | Input collection. Accepts a list, tuple, `dict`, pandas `Series`, polars `Series`, or NumPy array. A `dict` resolves its values and returns a same-keyed dict. `Added in v0.1.` |
| `to` | Pivot each resolved entity. Omit to use the `default_to` configured via [`configure()`](#configure). Pass `None` to always return a [`BulkResult`](#bulkresult). When set to a code system name, returns the native input shape (e.g. `pd.Series`) of pivot values; unresolved rows become `None`. |
| `on_missing` | Miss policy override for the configured output chain. Omit to inherit the resolver's `on_missing` policy. `"auto"` = null per row with `UserWarning` for bulk; `"raise"` = raises [`OutputMissingError`](#outputmissingerror) on the first resolved-but-missing entity; `"null"` = returns `None` per row silently. Only relevant when `to` is omitted and a `default_to` is configured. |
| `domain` | Domain filter, broadcast to every row. |
| `context` | Context hints, broadcast to every row. |
| `output` | Shape of the returned object when `to=None`: `"series"` (default) — series of values; `"record"` — series of structs; `"frame"` — DataFrame. Ignored when `to` is set. |
| `from_system` | Treat every value as a code in this system. |
| `not_found` | What fills unresolved rows in the output. `"null"` (default) → `None`; `"raise"` → raises; any other string → used as a literal sentinel value. |
| `on_error` | `"raise"` (default), `"null"`, or `"keep"` (pass the original value through). |
| `on_ambiguous` | `"null"` (default), `"raise"`, or `"best"`. |
| `crosswalk` | A [`Crosswalk`](#crosswalk) of pre-decided `value → entity_id` overrides. A value in the crosswalk short-circuits resolution — it bypasses `from_system`, `on_ambiguous`, and `not_found`; an `IGNORE` entry yields `None`. Values absent from the crosswalk resolve normally. `Added in v0.1.` |

**Returns**

- When `to` is set: the native shape (e.g. `pd.Series`, or a same-keyed `dict` for dict input) of pivot values.
- When `to=None`: a [`BulkResult`](#bulkresult).

**Raises** [`CrosswalkError`](#crosswalkerror) when a `crosswalk` (built with `strict=True`, the default) maps a value to an entity ID that no loaded pack carries.

**Example — pandas Series with pivot**

```python
>>> import pandas as pd
>>> rk.bulk(
...     values=pd.Series(["United States", "Brasil", "Cote dIvoire", "zzznotacountry"]),
...     to="iso3",
... )
0    USA
1    BRA
2    CIV
3    None
dtype: object
```

**Example — list with custom not-found sentinel**

```python
>>> rk.bulk(values=["Germany", "zzz"], to="iso3", not_found="UNKNOWN")
['DEU', 'UNKNOWN']
```

**Example — dict input (same keys back)**

```python
>>> rk.bulk(values={"hq": "France", "branch": "France", "other": "Germany"}, to="iso3")
{'hq': 'FRA', 'branch': 'FRA', 'other': 'DEU'}
```

**Example — crosswalk overrides**

```python
>>> cw = rk.Crosswalk.from_dict({"Congo": "country/COG", "Atlantis": rk.IGNORE})
>>> rk.bulk(values=["Congo", "Atlantis", "France"], to="iso3", crosswalk=cw)
['COG', None, 'FRA']
```

!!! note
    All parameters to `bulk()` are keyword-only. There is no positional `values` shortcut.

---

### `snap` { #snap }

```python
rk.snap(
    *,
    query: str,
    candidates: list[str],
    max_distance: float = 0.5,
    to: Any = None,
    domain: str | list[str] | None = None,
    context: ResolutionContext | None = None,
) -> Any
```

Return the closest matching candidate from a caller-supplied list, or `None` when nothing clears the threshold.

`snap` is for constrained matching: you already know the valid options and want to map a messy input onto one of them. It differs from `resolve`, which searches the full installed catalog.

**Parameters**

| Name | Meaning |
|---|---|
| `query` | The string to match. |
| `candidates` | Entity IDs or names to match against (e.g. `["country/TZA", "country/ZMB"]`). |
| `max_distance` | Confidence floor. Candidates below this threshold are rejected. Default `0.5`. |
| `to` | Pivot the matched entity (same semantics as `resolve`). |
| `domain` | Domain filter. |
| `context` | Resolution hints. |

**Returns** The best matching candidate (entity ID or pivot value), or `None` when below threshold.

**Example**

```python
>>> rk.snap(query="Tanzanya", candidates=["country/TZA", "country/ZMB", "country/KEN"])
'country/TZA'
>>> rk.snap(query="Zzzzzzz", candidates=["country/TZA", "country/ZMB", "country/KEN"])
None
```

!!! note "Candidate forms"
    `candidates` accepts entity IDs (e.g. `"country/TZA"`), plain labels (e.g. `"Tanzania"`), or a mix. Labels are resolved to entities first; a label that cannot be resolved unambiguously is skipped from the candidate set.

---

### `entity` { #entity }

```python
rk.entity(
    text_or_id: str | None = None,
    *,
    alpha_2: str | None = None,
    alpha_3: str | None = None,
    numeric: str | None = None,
    iso2: str | None = None,
    iso3: str | None = None,
    dcid: str | None = None,
    domain: str | list[str] | None = None,
    **code_kwargs: str,
) -> EntityRecord | None
```

Look up a fully hydrated [`EntityRecord`](#entityrecord) by name, entity ID, or code. Returns `None` when no match is found.

**Parameters**

| Name | Meaning |
|---|---|
| `text_or_id` | Name or entity ID (e.g. `"France"` or `"country/FRA"`). |
| `iso2` | ISO 3166-1 alpha-2 code. |
| `iso3` | ISO 3166-1 alpha-3 code. |
| `dcid` | Data Commons entity ID. |
| `alpha_2`, `alpha_3`, `numeric` | pycountry-compatible aliases for `iso2`, `iso3`, and the numeric code. |
| `**code_kwargs` | Any other code system by name (e.g. `wikidata="Q30"`). |
| `domain` | Domain filter. |

Pass exactly one lookup — `text_or_id` or one code kwarg. Passing two code kwargs raises `ValueError`.

**Returns** [`EntityRecord`](#entityrecord) or `None`.

**Example**

```python
>>> rk.entity("France").entity_id
'country/FRA'
>>> rk.entity(iso2="JP").canonical_name
'Japan'
>>> rk.entity(wikidata="Q30").entity_id
'country/USA'
```

---

### `modules` { #modules }

```python
rk.modules() -> list[ModuleInfo]
```

Return the full module catalog, sorted by `module_id`.

Each entry carries identity metadata and cache state. Bundled modules are always `is_available=True`. Remote modules are `is_available=True` only when their data is on disk.

!!! note
    On a fresh `pip install`, all six remote geo modules (`geo.admin1` through `geo.cities`) report `is_available=False` until you call [`download`](#download).

**Example**

```python
>>> [(m.module_id, m.distribution, m.is_available) for m in rk.modules()]
[
  ('geo.admin1', 'remote', False),
  ('geo.admin2', 'remote', False),
  ...
  ('geo.countries', 'bundled', True),
  ('org.companies', 'bundled', True),
  ...
]
```

**`ModuleInfo` fields**

| Field | Type | Meaning |
|---|---|---|
| `module_id` | `str` | Dot-separated identifier, e.g. `"geo.countries"`. |
| `domain` | `str` | Domain pack ID, e.g. `"geo"`. |
| `entity_types` | `tuple[str, ...]` | Entity types this module covers. |
| `distribution` | `"bundled" | "remote"` | How the data ships. |
| `is_available` | `bool` | Whether data is usable now without a download. |
| `size_mb` | `float | None` | Uncompressed on-disk size. `None` for uncached remote modules. |
| `download_size_mb` | `float | None` | Compressed download size. `None` for bundled modules. |
| `remote_url` | `str | None` | Download URL. |
| `data_version` | `str | None` | CalVer string for the module's data, e.g. `"2026.06"`. |
| `cache_path` | `Path | None` | On-disk path when cached; `None` otherwise. |

---

### `download` { #download }

```python
rk.download(target: str, *, force: bool = False) -> dict[str, Path]
```

Download remote module data to the local cache.

**Parameters**

| Name | Meaning |
|---|---|
| `target` | Module ID (`"geo.cities"`) or domain (`"geo"`) to download all modules in that domain. |
| `force` | Re-download even if already cached. Default `False`. |

**Returns** `dict[str, Path]` mapping `module_id` → `cache_path` for each downloaded module.

See [managing data packs](../how-to/work-offline-and-manage-data-packs.md) for download patterns and offline configuration.

---

### `download_all` { #download-all }

```python
rk.download_all(*, force: bool = False) -> dict[str, Path]
```

Download all installed remote modules.

**Parameters**

| Name | Meaning |
|---|---|
| `force` | Re-download even if already cached. Default `False`. |

**Returns** `dict[str, Path]` mapping `module_id` → `cache_path`.

---

### `configure` { #configure }

```python
rk.configure(
    *,
    auto_download: bool | None = None,
    cache_dir: str | Path | None = None,
    default_to: str | list[str] | None = None,
    on_missing: Literal["raise", "null", "auto"] = UNSET,
) -> None
```

Set runtime defaults and discard the singleton resolver so the next call rebuilds with the new configuration.

**Parameters**

| Name | Meaning |
|---|---|
| `auto_download` | When `True`, remote packs are downloaded automatically on first use. Default `False`. |
| `cache_dir` | Custom directory for cached remote data. |
| `default_to` | Default output code system or name variant applied to every subsequent `resolve()`, `bulk()`, and `snap()` call. A string (`"iso3"`) or a list of strings for a fallback chain (`["iso3", "name"]`). `None` clears the default, restoring the legacy `ResolutionResult` return. |
| `on_missing` | Miss policy when the configured output chain has no value for a resolved entity. Omitting leaves any previously configured policy unchanged. `"auto"` = raises [`OutputMissingError`](#outputmissingerror) for scalar `resolve()`/`snap()`, returns `None` with a `UserWarning` for `bulk()`; `"raise"` = always raise; `"null"` = always return `None`. |

**Raises**

- **`UnknownOutputError`** — When `default_to` contains a malformed `name:` grammar token. Also raised immediately when a singleton resolver already exists and `default_to` names an unknown code system (deferred to next resolver build otherwise).

**Example**

```python
import resolvekit as rk

rk.configure(default_to="iso3")
rk.resolve("France")         # → "FRA"
rk.bulk(values=["France", "Germany"], to="name")  # per-call to= overrides default

rk.configure(default_to=["iso3", "name"], on_missing="null")
rk.resolve("France")         # → "FRA"
rk.resolve("zzznotacountry") # → None  (no raise)

rk.configure(default_to=None)  # clear — resolves return ResolutionResult again
```

---

### `to` { #to }

```python
rk.to(
    output: str | list[str],
    *,
    on_missing: Literal["raise", "null", "auto"] = "auto",
) -> OutputView
```

Return an [`OutputView`](#outputview) bound to the given output spec, using the singleton default resolver.

All resolution methods on the returned view apply `output` automatically — no need to pass `to=` on every call. The view is a lightweight forwarding object; it holds a reference to the same underlying resolver.

**Parameters**

| Name | Meaning |
|---|---|
| `output` | Target code system or name variant (e.g. `"iso3"`, `["iso3", "name"]`, `"name:fr"`). The name grammar accepts `name`, `name:<lang>`, `name:<kind>`, and optionally `name:<kind>:<script>`. `<kind>` ∈ {`canonical`, `alias`, `endonym`, `exonym`, `acronym`} (`abbr` is accepted as an alias for `acronym`). Kind tokens resolve only for packs that carry the corresponding name kind; the bundled packs provide canonical names, per-language names (`en`, `fr`, `es`, `de`, `ru`, `ja`, `it`, `pt`, `zh`, `ar`), and aliases. |
| `on_missing` | Miss policy for the output chain. `"auto"` (default) = raise for scalar `resolve()`/`snap()`, null + `UserWarning` for `bulk()`; `"raise"` = always raise [`OutputMissingError`](#outputmissingerror); `"null"` = always return `None`. |

**Returns** — [`OutputView`](#outputview).

**Raises**

- **`UnknownOutputError`** — When `output` contains a malformed token or names an unknown code system.

**Example**

```python
import resolvekit as rk

iso3 = rk.to("iso3")
iso3.resolve("France")          # → "FRA"
iso3.resolve_id("France")       # → "country/FRA"  (entity ID, not pivoted)
iso3.bulk(values=["France", "Germany"])  # → ["FRA", "DEU"]
```

---

### `clear_cache` { #clear-cache }

```python
rk.clear_cache(target: str | None = None) -> None
```

Remove cached module data from disk.

**Parameters**

| Name | Meaning |
|---|---|
| `target` | Module ID to clear, or `None` to clear all. |

---

### `reset` { #reset }

```python
rk.reset() -> None
```

Close and discard the singleton resolver. The next call to any resolution function constructs a fresh one via `Resolver.auto()`.

---

### `warm` { #warm }

```python
rk.warm() -> None
```

Build all lazily-constructed indexes in the singleton resolver now and block until they are ready. Idempotent — calling it again when indexes are already built returns immediately. Thread-safe.

By default, `Resolver` construction starts a background daemon thread that pre-builds the SymSpell typo index so the cost does not land on the first query. `warm()` is for servers and batch jobs that need the resolver to be fully ready before processing begins, rather than relying on background preparation.

`Resolver.warm()` is the same operation on an explicit resolver instance:

```python
from resolvekit import Resolver

r = Resolver.auto()
r.warm()          # block here until all indexes are ready
r.resolve("France")   # no index-build latency
```

The module-level call warms the singleton resolver, constructing it first if it hasn't been created yet:

```python
import resolvekit as rk

rk.warm()           # build the singleton resolver and all its indexes
rk.resolve("France")  # ready immediately
```

To skip background warm-up entirely and keep construction fully lazy, pass `warm=False` to any constructor:

```python
r = Resolver.auto(warm=False)
r = Resolver.from_modules(module_ids=["geo.countries", "geo.admin1"], warm=False)
```

The compiled index cache reduces the SymSpell build cost from ~6 s to ~1.4 s on installs with remote data tiers (admin2–admin5, cities). The cache file is stored under `<cache-dir>/compiled/` (the same directory as the remote data tiers; see [`configure(cache_dir=...)`](#configure)), keyed by the dictionary files and symspellpy version. It is generated locally and never downloaded. If the cache directory is read-only, the library silently skips writing it.

---

### `default` { #default }

```python
rk.default() -> Resolver
```

Return the singleton [`Resolver`](resolver.md) instance, creating it on first call. The same object is reused until `reset()` or `configure()` is called.

---

### `parse` { #parse }

```python
rk.parse(
    text: str,
    *,
    to: str | list[str] | None = None,
    include_nil: bool = False,
    domain: str | list[str] | None = None,
    context: ResolutionContext | None = None,
    confidence_threshold: float | None = None,
    timeout: float | None = None,
) -> ParseResult
```

Extract and link every pack-known entity mention in free text, returning character offsets and calibrated confidence for each span. Detection is dictionary-first over the loaded packs.

!!! warning "Heads up"
    Requires the `[parsing]` extra: `pip install 'resolvekit[parsing]'`. Without it, calling `parse()` raises `ImportError`.

**Parameters**

| Name | Meaning |
|---|---|
| `text` | Free-text input to scan. |
| `to` | Pivot each resolved entity to a code system (e.g. `"iso3"`). The pivot value is stored in `ParsedEntity.output`. |
| `include_nil` | When `True`, below-threshold detected spans are included in the result with `status="no_match"` instead of going to `dropped_spans`. Default `False`. |
| `domain` | Restrict entity matching to one or more domains. |
| `context` | Resolution hints broadcast to every candidate span. |
| `confidence_threshold` | Minimum calibrated confidence to accept a match. `None` uses each pack's built-in threshold. |
| `timeout` | Soft per-call time budget in seconds. `None` = no limit. |

**Returns** [`ParseResult`](#parseresult).

**Raises** `ImportError` when the `[parsing]` extra is not installed.

**Example**

```python
import resolvekit as rk   # pip install 'resolvekit[parsing]'

result = rk.parse("The summit in Nairobi gathered leaders from Kenya, Uganda and the United States.")
for e in result:
    if e.entity_id:
        print(f"{e.surface!r} [{e.start}:{e.end}] -> {e.entity_id} ({e.entity_type}) {e.confidence:.2f}")
# 'Kenya' [44:49] -> country/KEN (geo.country) 0.91
# 'Uganda' [51:57] -> country/UGA (geo.country) 0.91
# 'the United States' [62:79] -> country/USA (geo.country) 0.91

# Nairobi is NOT detected on a fresh install — cities are a remote pack, not bundled.
[(d.surface, d.reason) for d in result.dropped_spans]   # e.g. [('and', 'code_case_mismatch'), ('in', 'deny_list')]

# Pivot each linked entity to a code:
[(e.surface, e.output) for e in rk.parse("Travel from France to Brazil", to="iso3")]
# [('France', 'FRA'), ('Brazil', 'BRA')]
```

---

### `parse_bulk` { #parse-bulk }

```python
rk.parse_bulk(
    *,
    values: list[str] | tuple | pd.Series | pl.Series,
    to: str | list[str] | None = None,
    include_nil: bool = False,
    domain: str | list[str] | None = None,
    context: ResolutionContext | None = None,
    confidence_threshold: float | None = None,
    timeout: float | None = None,
) -> ParseResult
```

Extract entities from a collection of text strings. Each `ParsedEntity` carries a `row_idx` field identifying its source row.

!!! warning "Heads up"
    Requires the `[parsing]` extra: `pip install 'resolvekit[parsing]'`. Without it, raises `ImportError`.

**Parameters**

| Name | Meaning |
|---|---|
| `values` | Collection of text strings to scan. Accepts a list, tuple, pandas `Series`, or polars `Series`. |
| `to` | Pivot each resolved entity. Stored in `ParsedEntity.output`. |
| `include_nil` | Include below-threshold spans in the result. Default `False`. |
| `domain` | Domain filter, broadcast to every row. |
| `context` | Resolution hints, broadcast to every row. |
| `confidence_threshold` | Minimum calibrated confidence to accept a match. `None` uses each pack's built-in threshold. |
| `timeout` | Soft per-call time budget in seconds. `None` = no limit. |

**Returns** [`ParseResult`](#parseresult).

**Raises**

- **`ImportError`** — When the `[parsing]` extra is not installed.
- **`TypeError`** — When `values` is not a `list`, `tuple`, `pd.Series`, or `pl.Series`.

**Example**

```python
import resolvekit as rk   # pip install 'resolvekit[parsing]'

df = rk.parse_bulk(values=["Visited Kenya and Peru", "Meeting in Japan"]).to_dataframe()
list(df.columns)
# ['row_idx', 'surface', 'entity_id', 'entity_type', 'pack_id', 'status', 'confidence', 'start', 'end', 'to']
```

---

## Models { #models }

### `ResolutionResult` { #resolutionresult }

Frozen Pydantic model. Returned by `resolve()` (when `to` is not set) and by the `Resolver` class methods.

**Fields**

| Field | Type | Meaning |
|---|---|---|
| `status` | [`ResolutionStatus`](#resolutionstatus) | Always set — never `None`. |
| `entity_id` | `str | None` | Resolved entity ID (e.g. `"country/USA"`). Present only when `status == RESOLVED`. |
| `confidence` | `float | None` | Calibrated confidence in `[0, 1]`. Present only when `status == RESOLVED`. |
| `entity` | [`EntityRecord`](#entityrecord) `| None` | Populated when `include_entity=True`. |
| `pack_id` | `str | None` | Domain pack that produced the result (e.g. `"geo"`). |
| `match_tier` | `str | None` | How the match was found: `"exact_code"`, `"exact_name"`, `"acronym"`, `"fts"`, `"fuzzy"`, or `"fallback"`. |
| `candidates` | `tuple[CandidateSummary, ...]` | Top candidates (up to 10), including the winner on a resolved result. |
| `reasons` | `tuple[str, ...]` | Reason codes explaining the outcome (e.g. `("exact_code_match",)`). Currently always a single-element tuple. |
| `refinement_hints` | `tuple[str, ...]` | Suggestions for a retry that would likely succeed (e.g. `("entity_types",)`). |
| `query_text` | `str | None` | The original input text as seen by the resolver. |

**Convenience properties** (delegate to `entity`; return `None` when `entity` is not populated)

| Property | Returns |
|---|---|
| `.iso2` | ISO 3166-1 alpha-2 code |
| `.iso3` | ISO 3166-1 alpha-3 code |
| `.name` | Canonical name |
| `.flag` | Flag emoji |
| `.is_resolved` | `True` when `status == RESOLVED` |
| `.is_ambiguous` | `True` when `status == AMBIGUOUS` |
| `.best_candidate` | Highest-confidence `CandidateSummary`, or `None` |

**Methods**

| Method | Returns | Meaning |
|---|---|---|
| `.top_candidates(n=3)` | `tuple[CandidateSummary, ...]` | Top *n* candidates by confidence. |
| `.explain(verbosity="standard")` | `Scorecard` | Re-run with full tracing. Verbosity: `"minimal"`, `"standard"`, `"full"`. Raises `ExplainNotAvailableError` on detached results. |
| `.to_dict()` | `dict` | JSON-serializable dict (delegates to `model_dump()`). |
| `.to_json(indent=None)` | `str` | JSON string. |

**Example**

```python
>>> r = rk.resolve("United States")
>>> r.status
<ResolutionStatus.RESOLVED: 'resolved'>
>>> r.entity_id
'country/USA'
>>> r.confidence
≈0.91
>>> r.is_resolved
True
>>> r.reasons
(<ReasonCode.EXACT_NAME_MATCH: 'exact_name_match'>,)
```

**Explain**

```python
>>> print(r.explain(verbosity="full").as_text())
Resolution Scorecard
============================================================
Query: "United States"
Normalized: "united states"
Status: RESOLVED
Entity: country/USA
Confidence: 93.3%
Reasons: exact_name_match
Pack: geo
Match Tier: exact_name
```

---

### `EntityRecord` { #entityrecord }

Frozen Pydantic model. Domain-neutral entity representation.

**Fields**

| Field | Type | Meaning |
|---|---|---|
| `entity_id` | `str` | Unique identifier, e.g. `"country/DEU"`. |
| `entity_type` | `str` | Type string, e.g. `"geo.country"`. |
| `canonical_name` | `str` | Primary display name. |
| `names` | `list[NameRecord]` | All name records, including aliases in multiple languages. |
| `codes` | `list[CodeRecord]` | Code identifiers (ISO, Wikidata, DCID, etc.). |
| `relations` | `list[RelationRecord]` | Relations to other entities (containment, membership). |
| `attributes` | `dict[str, str | int | float | bool]` | Domain-specific lightweight attributes (e.g. `prominence`). |
| `valid_from`, `valid_until` | `date | None` | Validity window. |

**Convenience properties**

| Property | Returns |
|---|---|
| `.name` | Same as `canonical_name`. |
| `.iso2` | ISO 3166-1 alpha-2 code, or `None`. |
| `.iso3` | ISO 3166-1 alpha-3 code, or `None`. |
| `.numeric` | ISO 3166-1 numeric code string, or `None`. |
| `.flag` | Flag emoji derived from `iso2`, or `None`. |
| `.continent` | Continent name from `attributes`, or `None`. |
| `.aliases` | Non-preferred name strings, in declaration order. |
| `.codes_dict` | `{system: value}` mapping from all `CodeRecord` entries. |

**Methods**

| Method | Returns | Meaning |
|---|---|---|
| `.code(system)` | `str | None` | Code value for a named system, e.g. `.code("wikidata")`. |
| `.attribute(key, default=None)` | `Any` | Attribute by key, with optional default. |
| `.to(system)` | `Any` | Pivot to a code system or computed property. Raises `UnknownCodeSystemError` if the system isn't recognized. |

**Example**

```python
>>> e = rk.entity("Germany")
>>> e.entity_id
'country/DEU'
>>> e.iso3
'DEU'
>>> e.code("wikidata")
'Q183'
>>> e.aliases[:3]
['Alemanha', 'Alemania', 'Allemagne']
>>> e.attribute("source")
'datacommons'
```

**Reading relations**

```python
>>> e = rk.entity("Germany")
>>> [(r.relation_type, r.target_id) for r in e.relations if r.relation_type == "member_of"][:3]
[('member_of', 'EuropeanUnion'), ('member_of', 'groups/NATO'), ('member_of', 'groups/G7')]
```

Each edge exposes `.relation_type`, `.target_id`, `.valid_from`, and `.valid_until` (all duck-typed; `RelationRecord` is not a public import).

**Traversing relations**

Reading `entity.relations` and calling `rk.entity(rel.target_id)` directly can return `None` — some `target_id` values (e.g. `"WesternEurope"`, `"geoId/06"`) don't resolve in the bundled packs. Use `Resolver.related()` to get resolved entities only:

```python
r = rk.default()
parents = r.related("country/DEU", relation="contained_in")
for parent in parents:
    print(parent.canonical_name)
```

Unresolvable targets are omitted. To see which targets are dangling, use `r.diagnostics.unresolved_relations()`:

```python
for edge in r.diagnostics.unresolved_relations("country/DEU", relation="contained_in"):
    print(edge["target_id"], "is dangling")
```

See [The entity graph](../explanation/knowledge-graph.md) for the full edge-type vocabulary and traversal recipes.

---

### `OutputView` { #outputview }

Frozen dataclass. Returned by [`rk.to()`](#to) and [`Resolver.to()`](resolver.md#resolver-to). Binds a fixed output spec to a resolver so every call through it returns the configured representation without repeating `to=`.

```python
from resolvekit import Resolver

view = Resolver.auto().to("iso3")
view.resolve("France")       # → "FRA"
view.resolve_id("France")    # → "country/FRA"  (entity ID, never pivoted)
view.bulk(values=["France", "Germany"])  # → ["FRA", "DEU"]
```

**Methods**

| Method | Returns | Notes |
|---|---|---|
| `.resolve(text, *, as_result=False, domain=None, context=None, from_system=None, timeout=None)` | `str \| None` or `ResolutionResult` | Applies the bound spec. `as_result=True` returns a raw `ResolutionResult`. |
| `.resolve_id(text, *, on_ambiguous="raise", from_system=None, domain=None, context=None, timeout=None)` | `str \| None` | Always returns entity ID — the bound output spec has no effect here. |
| `.bulk(*, values, on_missing=UNSET, output="series", domain=None, context=None, from_system=None, not_found="null", on_error="raise", on_ambiguous="null")` | native shape or `BulkResult` | Applies the bound spec to every row. |
| `.snap(*, query, candidates, max_distance=0.5, domain=None, context=None)` | `str \| None` | Returns the closest match pivoted to the bound output. |

`OutputView` is not exported from `resolvekit` directly; it is the return type of `rk.to()` and `Resolver.to()`.

---

### `ResolutionContext` { #resolutioncontext }

Frozen Pydantic model. Pass to any resolution function to narrow or constrain matching.

```python
from resolvekit import ResolutionContext
```

**Fields**

| Field | Type | Meaning |
|---|---|---|
| `as_of` | `date | None` | Resolve against entities valid at this date. |
| `entity_types` | `frozenset[str] | None` | Restrict to specific entity types (e.g. `{"geo.country"}`). Must be a collection — a bare string raises `ValueError`. |
| `parent_ids` | `list[str] | None` | Restrict to entities contained within these parent IDs. |
| `country` | `str | None` | ISO 3166-1 country code hint — alpha-2 (`"US"`) or alpha-3 (`"USA"`). |
| `languages` | `list[str] | None` | Preferred language codes for name matching. |
| `attributes` | `dict` | Escape hatch for domain-specific hints. |

**Methods**

| Method | Returns | Meaning |
|---|---|---|
| `.replace(**updates)` | `ResolutionContext` | Return a new instance with specified fields updated. Full validation is run on the result. |

**Example**

```python
>>> from datetime import date
>>> from resolvekit import ResolutionContext
>>> ctx = ResolutionContext(country="US", entity_types={"geo.state"})
>>> ctx.replace(as_of=date(2020, 1, 1))
ResolutionContext(as_of=datetime.date(2020, 1, 1), entity_types=frozenset({'geo.state'}), parent_ids=None, country='US', languages=None, attributes={})
```

---

### `BulkResult` { #bulkresult }

Frozen dataclass. Returned by `bulk()` when `to=None`.

**Attributes**

| Attribute | Type | Meaning |
|---|---|---|
| `values` | `Any` | Native output shape (`pd.Series`, `pl.Series`, `list`, etc.). |
| `source` | `Sequence[ResolutionResult]` | Per-row `ResolutionResult` instances. |
| `kind` | `"pandas" | "polars" | "numpy" | "list" | "tuple" | "dict"` | Which native shape is in `values`. `"dict"` when `bulk` was called with a `dict`. |

**Methods**

| Method | Returns | Meaning |
|---|---|---|
| `.summary()` | `ResolutionSummary` | Per-status counts: `total`, `resolved`, `ambiguous`, `no_match`, `error`. |
| `.failures` | `BulkResult` | Sub-result containing only non-RESOLVED rows. |
| `.unnest()` | `pd.DataFrame | pl.DataFrame | list[dict]` | Flatten `source` into columns: `status`, `entity_id`, `confidence`, `pack_id`, `query_text`. |
| `.to_list()` | `list` | Convert `values` to a plain Python list. |
| `.to_pandas()` | `pd.Series` | Convert to pandas. Raises `ImportError` if pandas isn't installed. |
| `.to_polars()` | `pl.Series` | Convert to polars. |
| `.to_review(path, *, top_n=3)` | `None` | Write the ambiguous and no-match unique values (deduplicated) to a CSV for human review, each with up to `top_n` candidates. Resolved rows are omitted; an all-resolved result writes a header-only file. `Added in v0.1.` |
| `.to_crosswalk(review=None, *, strict=True)` | [`Crosswalk`](#crosswalk) | Build a complete crosswalk from this result's resolved rows, optionally merged with a filled review file (`review=` path). The filled `chosen` column overrides the auto-resolved entries. `Added in v0.1.` |
| `.explain(verbosity="standard")` | `list[Scorecard | None]` | Scorecards for every row; `None` for detached rows. |

`BulkResult` supports `len()`, iteration, and integer/slice indexing (over `source`).

**Review round-trip**

```python
>>> result = rk.bulk(values=["France", "Congo", "Atlantis"], to=None)
>>> result.to_review("review.csv")          # writes Congo (ambiguous) + Atlantis (no_match)
>>> # ... a human fills the `chosen` column ...
>>> crosswalk = result.to_crosswalk(review="review.csv")
>>> rk.bulk(values=["France", "Congo", "Atlantis"], to="iso3", crosswalk=crosswalk)
['FRA', 'COG', None]
```

See [how to reconcile a column with a review](../how-to/reconcile-a-column-with-review.md) for the full workflow and CSV formats.

**Example**

```python
>>> import pandas as pd
>>> br = rk.bulk(values=pd.Series(["Germany", "France", "zzznotacountry"]), to=None)
>>> br
BulkResult(total=3, resolved=2, no_match=1, ambiguous=0, error=0, kind='pandas')
>>> br.summary()
ResolutionSummary(total=3, resolved=2, ambiguous=0, no_match=1, error=0)
>>> br.unnest()[["status", "entity_id", "confidence"]]
     status    entity_id  confidence
0  resolved  country/DEU       ≈0.91
1  resolved  country/FRA       ≈0.91
2  no_match         None         NaN
```

---

### `Crosswalk` { #crosswalk }

*Added in v0.1.*

Frozen value-object: a complete `value → entity_id` table that overrides resolution when passed to [`bulk(crosswalk=…)`](#bulk). Build one by hand with `from_dict`, load a saved one with `from_csv`, or have [`BulkResult.to_crosswalk()`](#bulkresult) assemble it from a review round-trip.

```python
from resolvekit import Crosswalk, IGNORE
# or: rk.Crosswalk, rk.IGNORE
```

**Constructors**

- **`Crosswalk.from_dict(mapping, *, strict=True)`** — `mapping` is `dict[str, str | None]` mapping each input value to an entity ID (e.g. `"country/COG"`) or to `IGNORE` (equivalently `None`) to map it to no output. Entity IDs are validated structurally (must be `pack/code`); existence is checked later, at `bulk` time.
- **`Crosswalk.from_csv(path, *, strict=True)`** — load a crosswalk written by `to_csv`. Columns must be exactly `value,entity_id`; an `IGNORE` token or empty `entity_id` cell is read as ignore.

**Parameters**

- **`strict`** (`bool`, default `True`) — carried on the instance and applied when the crosswalk is used. With `strict=True`, an entity ID that no loaded pack carries raises [`CrosswalkError`](#crosswalkerror) at `bulk` time. With `strict=False`, such a value becomes a per-value miss (follows `not_found`).

**Methods**

| Method | Returns | Meaning |
|---|---|---|
| `.to_csv(path)` | `None` | Write the table to a `value,entity_id` CSV. `IGNORE` entries are written as the literal token `IGNORE`. |
| `len(cw)` | `int` | Number of entries. |
| `value in cw` | `bool` | Whether a value is in the table. |

**Raises**

- **`ValueError`** — at construction, when an entry's value isn't `None`/`IGNORE` or a well-formed `pack/code` entity ID, or (from `from_csv`) when columns are missing or a value is duplicated.

**Example**

```python
>>> cw = rk.Crosswalk.from_dict({"Congo": "country/COG", "Atlantis": rk.IGNORE})
>>> len(cw), "Congo" in cw
(2, True)
>>> cw.to_csv("crosswalk.csv")
>>> rk.Crosswalk.from_csv("crosswalk.csv")  # round-trips, including IGNORE
```

CSV format written by `to_csv`:

```csv
value,entity_id
Congo,country/COG
Atlantis,IGNORE
```

**See also** — [`BulkResult.to_crosswalk`](#bulkresult), [`bulk`](#bulk), [how to reconcile a column with a review](../how-to/reconcile-a-column-with-review.md).

---

### `IGNORE` { #ignore }

*Added in v0.1.*

Sentinel marking a [`Crosswalk`](#crosswalk) entry that maps a value to no output (`None`). Use it in `from_dict`; in a CSV it's the literal token `IGNORE`. Importable as `rk.IGNORE` or `from resolvekit import IGNORE`.

```python
>>> cw = rk.Crosswalk.from_dict({"placeholder row": rk.IGNORE})
>>> rk.bulk(values=["placeholder row"], to="iso3", crosswalk=cw)
[None]
```

---

### `ParseResult` { #parseresult }

Returned by [`parse()`](#parse) and [`parse_bulk()`](#parse-bulk). Iterable over [`ParsedEntity`](#parsedentity) instances.

**Attributes**

| Attribute | Type | Meaning |
|---|---|---|
| `dropped_spans` | `list[DroppedSpan]` | Spans detected but filtered out before linking. `DroppedSpan` is a `NamedTuple` with fields `surface`, `start`, `end`, `pack_id`, `reason` — where `reason` is one of `short_input`, `sentinel`, `word_boundary`, `below_threshold`, `deny_list`, `code_case_mismatch`. |

**Methods**

| Method | Returns | Meaning |
|---|---|---|
| `__iter__` | `Iterator[ParsedEntity]` | Iterate over linked entities. |
| `__len__` | `int` | Number of linked entities. |
| `.to_dataframe()` | `pd.DataFrame` | Columns: `row_idx`, `surface`, `entity_id`, `entity_type`, `pack_id`, `status`, `confidence`, `start`, `end`, `to`. Requires `pandas`. |

---

### `ParsedEntity` { #parsedentity }

Represents a single entity mention extracted by [`parse()`](#parse) or [`parse_bulk()`](#parse-bulk).

**Fields**

| Field | Type | Meaning |
|---|---|---|
| `surface` | `str` | The literal text span as it appears in the input. |
| `start` | `int` | Start character offset (inclusive). |
| `end` | `int` | End character offset (exclusive). |
| `entity_id` | `str | None` | Resolved entity ID, e.g. `"country/KEN"`. |
| `entity_type` | `str | None` | Entity type, e.g. `"geo.country"`. |
| `pack_id` | `str | None` | Domain pack that produced the match. |
| `status` | `str` | Resolution status string (e.g. `"resolved"`, `"no_match"`). |
| `confidence` | `float | None` | Calibrated confidence in `[0, 1]`. |
| `resolution` | `ResolutionResult | None` | Full resolution result — call `.resolution.explain()` for a detailed scorecard. |
| `output` | `Any` | The `to=` pivot value, or `None` when `to` was not set. |
| `row_idx` | `int | None` | Source-row index when produced by `parse_bulk()`; `None` for single-text `parse()`. |

---

### `ResolutionStatus` { #resolutionstatus }

`StrEnum` with four values. Every `ResolutionResult.status` is one of these — it's never `None`.

| Value | String | Meaning |
|---|---|---|
| `RESOLVED` | `"resolved"` | A single entity matched with sufficient confidence. |
| `AMBIGUOUS` | `"ambiguous"` | Multiple plausible matches, none dominant. |
| `NO_MATCH` | `"no_match"` | No candidates found, or all below threshold. |
| `ERROR` | `"error"` | Internal pipeline error. |

---

### `SuggestionResult` { #suggestionresult }

Frozen Pydantic model. One ranked suggestion returned by [`Resolver.suggest()`](resolver.md#resolversuggest). `suggest()` returns a `list[SuggestionResult]`, best-first. Not root-exported; import the type from `resolvekit.core.model`:

```python
from resolvekit.core.model import SuggestionResult, MatchClass
```

**Fields**

| Field | Type | Meaning |
|---|---|---|
| `entity_id` | `str` | The matched entity ID, e.g. `"country/USA"`. |
| `canonical_name` | `str | None` | The entity's canonical name. |
| `entity_type` | `str | None` | Entity type string, e.g. `"geo.country"`. |
| `pack_id` | `str | None` | Pack that produced the candidate. |
| `match_class` | [`MatchClass`](#matchclass) | How the candidate was found. |
| `fuzzy_score` | `float | None` | Raw RapidFuzz `partial_ratio` (0–100). `None` unless `match_class == FUZZY`. A similarity score, not a calibrated confidence. |
| `ranking_quality` | `"ranked" | "unranked"` | Tier-based honesty hint about the sort. `"ranked"` for tiers with prominence data — `geo.country` and the region tiers (`geo.subregion`, `geo.region`, `geo.continental_union`); `"unranked"` otherwise (continents, organizations, admin/city — match-class + alphabetical). Tier-based, not per-candidate: a country with no prominence value still reports `"ranked"`. |
| `display` | `str | None` | The `to=`-rendered output string, or `canonical_name` when no `to=` was set. `None` on an output miss. |
| `highlight_ranges` | `list[tuple[int, int]]` | Unicode **code-point** offsets (not UTF-16), end-exclusive, into `display`. Empty for fuzzy matches and for matches that hit an alias rather than `display`. JS/browser callers must convert offsets. |

**Example**

```python
>>> from resolvekit import Resolver
>>> r = Resolver.lite()
>>> s = r.suggest("germany", top_k=1)[0]
>>> s.entity_id
'country/DEU'
>>> s.match_class
<MatchClass.EXACT_PREFIX: 'exact_prefix'>
>>> s.ranking_quality
'ranked'
>>> s.display
'Germany'
>>> s.highlight_ranges
[(0, 7)]
```

---

### `MatchClass` { #matchclass }

`StrEnum`. Reports how a [`SuggestionResult`](#suggestionresult) candidate was matched. Not root-exported:

```python
from resolvekit.core.model import MatchClass
```

The four values, in ranking order (best first):

| Value | String | Meaning |
|---|---|---|
| `EXACT_PREFIX` | `"exact_prefix"` | The display/name starts with the query. |
| `TOKEN_PREFIX` | `"token_prefix"` | A word/token inside the name starts with the query. |
| `INFIX` | `"infix"` | The query appears mid-name. |
| `FUZZY` | `"fuzzy"` | A RapidFuzz near-match (typo tolerance). |

`suggest()` sorts by a lexicographic cascade: `(match_class, whole-name match, typo_count, -prominence, name-kind, name length, entity_id)`. So an exact prefix outranks a fuzzy match; among ties, an entity whose complete name was typed (e.g. an acronym like `"EU"`) wins, then fewer typos, then more-prominent entities (where the tier is ranked).

---

### `AugmentResult` { #augmentresult }

Returned by `Resolver.augment(..., return_report=True)`. See the [`Resolver` reference](resolver.md) for the full `augment` signature.

**Fields**

| Field | Type | Meaning |
|---|---|---|
| `resolver` | `Resolver` | The updated resolver with new attributes/codes attached. |
| `linked` | `int` | Rows that matched an existing entity and had their data merged in. |
| `minted` | `int` | Rows that matched no entity and were created as new entities (`on_miss="mint"`). |
| `skipped` | `int` | Rows that matched no entity and were dropped (`on_miss="skip"`). |
| `ambiguous` | `int` | Rows where the link key matched more than one entity. |
| `errors` | `list[str]` | Diagnostic messages for rows that raised during linking. |

!!! warning "Heads up"
    `augment` requires a single-domain base. `link_on` accepts **code systems** (`iso3`, `dcid`,
    `wikidata`, …) and the `"name"` sentinel. Code-based linking is case-insensitive on the code
    value (the shared casefold normaliser applies, so `"FRA"`, `"fra"`, and `"Fra"` all link).
    Name-based linking (`link_on=["name"]`) requires at least one of `add_aliases` or `add_codes`
    to identify the name column.

**Example**

```python
from resolvekit import Resolver

base = Resolver.from_records(
    [{"id": "KE", "label": "Kenya", "iso3": "KEN"},
     {"id": "UG", "label": "Uganda", "iso3": "UGA"}],
    domain="custom", name="label", id="id", codes={"iso3": "iso3"},
)
report = base.augment(
    [{"iso3": "KEN", "pop_m": 55}],
    link_on=["iso3"],
    add_attrs=["pop_m"],
    on_miss="skip",
    return_report=True,
)
report.linked, report.minted, report.skipped, report.ambiguous   # 1, 0, 0, 0
report.resolver.entity("Kenya").attributes["pop_m"]              # 55
```

`Resolver.from_records` and `Resolver.augment` are methods on `Resolver`, not module-level functions. See the [`Resolver` reference](resolver.md) for their full signatures.

---

### `SentinelBlocklist` { #sentinelblocklist }

```python
from resolvekit import SentinelBlocklist
```

Immutable set of normalized forms that the resolver rejects before running the pipeline. Blocked inputs return `NO_MATCH` with reason `"sentinel_blocked"`.

The default set covers common placeholders (`"unknown"`, `"n/a"`, `"null"`, `"tbd"`, …), junk strings (`"qwerty"`, `"lorem"`, …), pure-punctuation sequences (`"---"`, `"..."`, …), and specific pure-digit strings (`"000"`, `"999"`). Strings longer than 20 characters are never blocked regardless of content.

```python
SentinelBlocklist(
    *,
    extra: frozenset[str] | set[str] | None = None,
    replace: frozenset[str] | set[str] | None = None,
)
```

| Parameter | Meaning |
|---|---|
| `extra` | Additional terms to block (merged with defaults). Normalized via casefold + strip. |
| `replace` | Replace the entire default set. When set, `extra` is ignored. |

**Methods**

| Method | Returns | Meaning |
|---|---|---|
| `.is_blocked(text)` | `bool` | Case-insensitive match against the blocked set. |
| `text in blocklist` | `bool` | Same as `.is_blocked(text)`. |

**Example**

```python
>>> bl = SentinelBlocklist()
>>> "unknown" in bl
True
>>> "Germany" in bl
False

>>> bl2 = SentinelBlocklist(extra={"myplaceholder"})
>>> "myplaceholder" in bl2
True
```

Pass a custom blocklist to `Resolver.auto(sentinel_blocklist=...)`, or disable blocking entirely with `Resolver.auto(sentinel_blocklist=None)`.

---

## Errors { #errors }

All public errors are importable from `resolvekit` or the dedicated `resolvekit.errors` namespace. The errors most callers need:

```python
from resolvekit import (
    ResolverError,
    ResolutionError,
    AmbiguousResolutionError,
    EntityNotFoundError,
    GroupNotFoundError,
    CrosswalkError,
    DataPackNotAvailableError,
    ExplainNotAvailableError,
    NoModulesInstalledError,
    OutputMissingError,
    UnknownCodeSystemError,
    UnknownDomainError,
    UnknownOutputError,
)
```

All of the above are also available via `resolvekit.errors`. The full catalogue of datapack and registry errors (e.g. `DataPackRuntimeVersionError`, `ModuleConflictError`) lives exclusively in `resolvekit.errors`.

### `ResolverError` { #resolvererror }

Base class for all resolvekit errors. Carries an optional `.hint` attribute (a `str | None`) surfaced as a PEP 678 `__notes__` entry — it appears in tracebacks automatically.

### `ResolutionError(ResolverError)` { #resolutionerror }

A resolution attempt did not produce a usable result.

| Attribute | Type | Meaning |
|---|---|---|
| `.status` | `ResolutionStatus` | The status that triggered the error. |
| `.candidates` | `list[CandidateSummary]` | Available candidates (may be empty). |

### `AmbiguousResolutionError(ResolutionError)` { #ambiguousresolutionerror }

Raised by `resolve_id()` (default `on_ambiguous="raise"`) when multiple entities match.

| Attribute | Type | Meaning |
|---|---|---|
| `.candidates` | `list[CandidateSummary]` | The ambiguous candidates. |

**Example**

```python
from resolvekit import AmbiguousResolutionError

try:
    rk.resolve_id("Congo")
except AmbiguousResolutionError as e:
    entity_ids = [c.entity_id for c in e.candidates]
    # ['country/COD', 'country/COG']
```

### `GroupNotFoundError(ResolutionError)` { #groupnotfounderror }

Raised by `Resolver.members_of()` and `Resolver.is_member()` when the group string resolves to no entity.

### `EntityNotFoundError(ResolutionError)` { #entitynotfounderror }

Raised by `Resolver.related()` and `Resolver.diagnostics.unresolved_relations()` when the string `entity_or_id` argument matches no entity.

```python
import resolvekit as rk
from resolvekit import EntityNotFoundError

try:
    rk.default().related("NoSuchPlaceXYZ")
except EntityNotFoundError as e:
    print(e)
```

### `UnknownOutputError(ValueError, ResolverError)` { #unknownoutputerror }

Raised at configuration or compile time when `default_to` contains a malformed token (including a malformed `name:` grammar segment in a per-call `to=`) or names a code system that no loaded pack carries. A per-call `to=` naming an unknown code system raises [`UnknownCodeSystemError`](#unknowncodesystemerror) instead.

```python
from resolvekit import UnknownOutputError  # or: from resolvekit.errors import UnknownOutputError
```

| Attribute | Type | Meaning |
|---|---|---|
| `.token` | `str` | The unrecognised token. |
| `.available` | `list[str]` | Code and pivot names available in the relevant scope. |

Carries `.hint` with difflib did-you-mean suggestions.

### `UnknownCodeSystemError(ValueError, ResolverError)` { #unknowncodesystemerror }

Raised when a per-call `to=` (or `EntityRecord.to(system)`) names a code system that no loaded pack carries, and by `Resolver.members_of` when the requested `as_codes` is not loaded.

```python
from resolvekit import UnknownCodeSystemError  # or: from resolvekit.errors import UnknownCodeSystemError
```

| Attribute | Type | Meaning |
|---|---|---|
| `.system` | `str` | The requested code system name. |
| `.available` | `list[str]` | Code system names available in the relevant scope. |

Carries `.hint` with difflib did-you-mean suggestions.

### `OutputMissingError(ResolverError)` { #outputmissingerror }

Raised at runtime when a resolved entity (and the full fallback chain) has no value for the requested output, under `on_missing="raise"` (or `on_missing="auto"` for scalar `resolve()`/`snap()`).

```python
from resolvekit import OutputMissingError  # or: from resolvekit.errors import OutputMissingError
```

| Attribute | Type | Meaning |
|---|---|---|
| `.entity_id` | `str` | The entity that was resolved but lacked the output. |
| `.requested` | `str` | The output token that was requested (last in the fallback chain). |
| `.available_codes` | `list[str]` | Code systems the entity does carry. |

Carries `.hint` listing the available codes.

### `CrosswalkError(ResolverError)` { #crosswalkerror }

*Added in v0.1.*

Raised by [`bulk`](#bulk) when a [`Crosswalk`](#crosswalk) built with `strict=True` (the default) maps one or more values to entity IDs that no loaded pack carries — typically a crosswalk saved before a data rebuild that changed IDs.

```python
from resolvekit import CrosswalkError  # or: from resolvekit.errors import CrosswalkError
```

| Attribute | Type | Meaning |
|---|---|---|
| `.offenders` | `list[str]` | The unknown entity IDs found in the crosswalk. |

Carries `.hint` pointing to `strict=False` as the way to downgrade unknown IDs to per-value misses. Rebuild the crosswalk with `Crosswalk.from_dict(..., strict=False)` / `from_csv(..., strict=False)` to apply it.

---

## Next { #next }

**[Resolver class reference](resolver.md)** — constructors (`auto`, `lite`, `from_modules`), concurrency notes, and the full method list including `members_of`, `diagnostics`, and context-manager protocol.

**[Convert between code systems](../how-to/convert-between-code-systems.md)** — end-to-end patterns for `from_system` / `to` pivots and bulk column normalization.
