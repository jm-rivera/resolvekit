# How to work offline and manage data packs

resolvekit ships with two classes of modules:

**Bundled** — packaged inside the wheel, available immediately with no network access. Ten modules across geo and org:

| Module | Domain |
|---|---|
| `geo.countries` | Countries |
| `geo.regions` | World regions (sub-continental groupings) |
| `geo.continents` | Continents |
| `geo.continental_unions` | Continental unions (AU, EU, ASEAN, …) |
| `org.companies` | Companies |
| `org.data_sources` | Data sources |
| `org.governments` | National governments |
| `org.lenders` | Lending institutions |
| `org.political_parties` | Political parties |
| `org.providers` | Data providers |

**Remote** — not bundled. Fetched on demand from GitHub Release `data-v2026.06` and verified by checksum. All six are in the `geo` domain:

| Module | Download size |
|---|---|
| `geo.admin1` | 12 MB |
| `geo.admin2` | 100 MB |
| `geo.admin3` | 160 MB |
| `geo.admin4` | 380 MB |
| `geo.admin5` | 2 MB |
| `geo.cities` | 154 MB |

!!! warning "Heads up"
    `geo.admin2` through `geo.admin4` together exceed 600 MB. Download only the levels you actually query. If you only need country-level geo, use [`Resolver.lite()`](#resolverlite-for-small-footprint) and skip all six remote packs entirely.

## Check what's installed

`rk.modules()` reads the on-disk manifest and cache state. It never makes a network request.

```python
import resolvekit as rk

for m in rk.modules():
    status = "ready" if m.is_available else "not downloaded"
    print(f"{m.module_id}: {m.distribution}, {status}")
```

Output on a fresh install (no remote packs downloaded yet):

```
geo.admin1: remote, not downloaded
geo.admin2: remote, not downloaded
geo.admin3: remote, not downloaded
geo.admin4: remote, not downloaded
geo.admin5: remote, not downloaded
geo.cities: remote, not downloaded
geo.continental_unions: bundled, ready
geo.continents: bundled, ready
geo.countries: bundled, ready
geo.regions: bundled, ready
org.companies: bundled, ready
org.data_sources: bundled, ready
org.governments: bundled, ready
org.lenders: bundled, ready
org.political_parties: bundled, ready
org.providers: bundled, ready
```

Each `ModuleInfo` object also carries `download_size_mb` for remote modules, so you can tally the download cost before committing:

```python
total_mb = sum(
    m.download_size_mb
    for m in rk.modules()
    if m.distribution == "remote" and not m.is_available and m.download_size_mb
)
print(f"Remote packs not yet downloaded: {total_mb:.0f} MB")
```

## Download packs on demand

`rk.download()` accepts either a single module ID or a domain name:

```python
# Download one module
rk.download("geo.cities")

# Download all remote modules in a domain
rk.download("geo")

# Re-download even if already cached
rk.download("geo.cities", force=True)
```

`rk.download_all()` downloads every remote module in the installed package:

```python
rk.download_all()

# Force re-download of everything
rk.download_all(force=True)
```

Both functions return a `dict[str, Path]` mapping module ID to the on-disk cache path. They skip any module that's already cached (unless `force=True`).

After a download, call `rk.reset()` to discard the cached resolver; the next call rebuilds it against the newly downloaded pack:

```python
rk.download("geo.cities")
rk.reset()  # discard cached resolver — next call rebuilds it

rk.resolve_id("São Paulo")  # now routes through geo.cities
```

## Configure cache directory

By default, packs land in `~/.cache/resolvekit` (XDG-compliant on Linux, equivalent on macOS/Windows).

To redirect to a project-local directory:

```python
import resolvekit as rk

rk.configure(cache_dir="./packs", auto_download=False)
```

`rk.configure()` immediately invalidates the default resolver singleton, so the next call to any module-level function rebuilds against the new config.

You can also set the directory with an environment variable — useful in CI or containers where you don't want to modify code:

```
RESOLVEKIT_CACHE_DIR=/data/resolvekit/packs
```

### Auto-download

With `auto_download=True`, resolvekit downloads any uncached remote pack at resolver build time rather than raising `DataPackNotAvailableError`:

```python
rk.configure(cache_dir="./packs", auto_download=True)
```

This is convenient in development. For production pipelines, pre-download explicitly so resolver construction doesn't block on network.

The equivalent environment variable:

```
RESOLVEKIT_AUTO_DOWNLOAD=1
```

## Clear the cache

`rk.clear_cache()` deletes downloaded data from disk.

```python
# Remove one pack
rk.clear_cache("geo.cities")

# Remove all downloaded packs
rk.clear_cache()
```

After clearing, call `rk.reset()` if you've already initialized a resolver, so it doesn't hold references to the deleted data.

## The offline-reproducible pattern

Pre-download once while you have network access, then run with no network. The download is pinned to release tag `data-v2026.06` and the checksum is verified on every fetch — re-downloading the same tag with `force=True` produces byte-identical files.

```python
# --- setup.py (run once, with network) ---
import resolvekit as rk

rk.configure(cache_dir="./packs")
rk.download("geo.countries")   # already bundled, skipped
rk.download("geo.cities")      # fetched and verified

# --- pipeline.py (runs offline) ---
import resolvekit as rk

rk.configure(cache_dir="./packs")
# All queries now resolve against the cached packs; no network calls.
result = rk.resolve_id("Nairobi")
```

To enforce that no network calls happen at all, set `RESOLVEKIT_OFFLINE=1`. resolvekit raises an error if anything attempts a download:

```
RESOLVEKIT_OFFLINE=1 python pipeline.py
```

## `Resolver.lite()` for small footprint

`Resolver.lite()` loads only the four bundled country-level modules (`geo.countries`, `geo.regions`, `geo.continents`, `geo.continental_unions`). It skips the six remote packs entirely — no download needed, lower memory use, faster cold start.

```python
from resolvekit import Resolver

r = Resolver.lite()
print(r.domains)          # ['geo']
r.resolve_id("Germany")   # 'country/DEU'
r.resolve_id("Japan")     # 'country/JPN'
```

Choose `Resolver.lite()` when:

- You only need country, region, or continental-union lookups.
- You're running in a memory-constrained environment.
- You want to avoid downloading any remote packs at all.

Choose `Resolver.auto()` (the default) when you need org module coverage or when you've downloaded admin/city packs and want them available automatically.

`Resolver.lite()` accepts the same options as `Resolver.auto()`, including `cache_size` and `confidence_threshold`. To add one admin level on top of the lite base:

```python
r = Resolver.lite(module_ids=["geo.countries", "geo.admin1"])
```

??? abstract "Under the hood"
    `Resolver.lite()` calls `Resolver.from_modules()` with the module IDs
    `["geo.countries", "geo.regions", "geo.continents", "geo.continental_unions"]`.
    The SymSpell fuzzy-match index for each pack is built lazily on the first
    fuzzy query, so exact-name and code lookups have no extra startup cost.

---

As of v0.1.0.

## Next

- [Explanation: offline data and pack management](../explanation/offline-and-data-packs.md) — why the two-tier bundled/remote split exists, how checksums work, and how to mirror releases for air-gapped environments.
- [Getting started: installation](../getting-started/install.md) — install resolvekit, choose extras, and run your first resolution.
