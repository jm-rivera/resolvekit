# Offline-first and the data-pack split

*As of v0.1.*

resolvekit never makes a network call when it resolves a query. Every lookup runs against SQLite databases on your local disk. No API key, no rate limit, no request that leaves your machine.

The trade-off: data has to be on disk before it can be queried. Below is how that data gets there, why it's split the way it is, and how to control the trade-off between install footprint and coverage.

## Why offline-first

Three constraints pushed us toward offline resolution rather than a query-time API:

**Determinism.** The same input should produce the same output whether you run the code today, on a CI server tomorrow, or in a colleague's environment six months from now. An API-backed resolver ties your output to whatever data the service happens to have at query time. A pinned local dataset doesn't change unless you explicitly upgrade it.

**No runtime dependencies.** A pipeline that calls an external service at query time inherits that service's availability, latency, and rate limits. resolvekit's resolve path depends on nothing beyond Python and the SQLite files on disk — no tokens, no quotas, no 429s at 2 a.m.

**Data privacy.** When you're resolving entities from donor records, patient files, or proprietary data, every query you send to an external service is also a disclosure. Running resolution locally means the data never leaves the machine.

The alternative we considered and rejected was a tiered model where bundled data handled common inputs and a remote API handled the long tail. It would have covered more edge cases, but at the cost of the three guarantees above. For the users resolvekit is built for — analysts running reproducible pipelines — those guarantees matter more than the last few percentage points of coverage.

## How the data-pack split works

resolvekit ships 16 modules across two domains. Ten are **bundled** in the wheel and work offline immediately after `pip install`. Six are **remote** and must be downloaded before use.

```python
import resolvekit as rk

for m in rk.modules():
    size = f"  ({m.size_mb:.0f} MB on disk)" if m.distribution == "remote" else ""
    print(f"{m.module_id:<35} {m.distribution}{size}")
```

Output on a fresh install (remote modules show `is_available=False` until downloaded):

```
geo.admin1                          remote  (12 MB on disk)
geo.admin2                          remote  (100 MB on disk)
geo.admin3                          remote  (160 MB on disk)
geo.admin4                          remote  (379 MB on disk)
geo.admin5                          remote  (2 MB on disk)
geo.cities                          remote  (154 MB on disk)
geo.continental_unions              bundled
geo.continents                      bundled
geo.countries                       bundled
geo.regions                         bundled
org.companies                       bundled
org.data_sources                    bundled
org.governments                     bundled
org.lenders                         bundled
org.political_parties               bundled
org.providers                       bundled
```

!!! info "Why"
    The bundled/remote split is driven by wheel size. Shipping the full admin
    hierarchy and cities database in the wheel would add ~800 MB to every
    install — including CI containers and environments that only need
    country-level resolution. The ten bundled modules (countries, regions,
    continents, continental unions, and all org modules) cover the most common
    cases at a fraction of that footprint. The large geo packs are fetched
    once, on demand.

Bundled modules live inside the installed package directory. Remote modules are
downloaded to a cache directory (`~/.cache/resolvekit` by default) and
checksum-verified before use.

## Downloading remote packs

To download a specific module:

```python
rk.download("geo.admin1")
```

To download an entire domain:

```python
rk.download("geo")   # fetches all six remote geo modules
```

After downloading, the modules load automatically — no further configuration needed.

By default, `download()` is the explicit path. resolvekit does not auto-download on first use unless you opt in:

```python
rk.configure(auto_download=True)
```

With `auto_download=True`, any call that touches a remote module triggers a download transparently. Without it, accessing an unavailable module raises `DataPackNotAvailableError` from `resolvekit.errors`.

`rk.configure()` also accepts `default_to` and `on_missing` to control output format and missing-entity behaviour process-wide — see the [API reference](../reference/api.md) for the full parameter list.

!!! warning "Heads up"
    `RESOLVEKIT_AUTO_DOWNLOAD=1` enables auto-download for the current
    process. Useful in CI pipelines that should self-provision, but not
    appropriate if you want strict offline guarantees.

## Versioned releases and pinning

All data is tied to a release tag. The current tag is `data-v2026.06`.

You can check which data version a running resolver is using:

```python
import resolvekit as rk

r = rk.default()
print(r.info.data_version)  # '2026.06'
```

When a new data release ships, `rk.download()` downloads it. Your existing
cache stays on the old version until you re-download. For reproducible
pipelines, pin your `resolvekit` version in `requirements.txt` — the package
version determines which data tag it fetches.

resolvekit verifies every downloaded file against a SHA-256 hash embedded in the package before loading it. A corrupted or truncated download is rejected. If verification fails, `rk.download()` re-fetches on the next call.

!!! note
    To override the download location (for air-gapped environments or
    corporate mirrors), set `RESOLVEKIT_CACHE_DIR` to a directory path, or
    `RESOLVEKIT_RELEASE_BASE_URL` to point at an internal mirror that serves
    the same asset filenames.

## Resolver.lite() for smaller footprint

`Resolver.lite()` loads only the four bundled country-level geo modules —
`geo.countries`, `geo.regions`, `geo.continents`, and `geo.continental_unions`.
It does not load org modules or any remote admin/cities tiers, so `.domains`
is `['geo']` and it works from a fresh install with no download step.

```python
from resolvekit import Resolver

r = Resolver.lite()
print(r.domains)              # ['geo']
print(r.resolve_id("Japan"))  # 'country/JPN'
```

Use `Resolver.lite()` when:

- You only need country-level resolution.
- Cold-start time or resident memory is a concern (e.g., short-lived Lambda functions or CI jobs that resolve countries in a loop).
- You want the smallest possible footprint with zero download required.

`Resolver.auto()` (the default) loads all installed and available modules — bundled and any remote modules that are already cached, across both `geo` and `org` domains. Use `auto()` when you need full resolution coverage across countries, regions, admin levels, cities, and org entities.

## What runs without any download

After `pip install resolvekit` with no further setup:

- Country resolution — names, codes (ISO 2, ISO 3, numeric), aliases in multiple languages
- Geographic regions, continents, and continental unions
- All org modules — companies, governments, lenders, political parties, providers, and data sources

Admin-level resolution (provinces, districts, cities) requires the corresponding remote modules.

Entity extraction via `rk.parse()` and `rk.parse_bulk()` requires the `[parsing]` extra (`pip install 'resolvekit[parsing]'`), which installs the `ahocorasick_rs` dependency. Detection spans only the packs that are loaded — sub-national mentions (cities, admin districts) are not detected unless the relevant remote packs have been downloaded.

## Next

[How to work offline and manage data packs](../how-to/work-offline-and-manage-data-packs.md) — step-by-step instructions for seeding remote packs in air-gapped environments, clearing the cache, and using a mirror URL.

[Installation](../getting-started/install.md) — covers the optional integration extras (`resolvekit[pandas]`, `resolvekit[polars]`).
