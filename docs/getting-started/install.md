# Install resolvekit

Install the package and confirm it's working. Requires Python 3.12 or later.

## Install

=== "uv"

    ```bash
    uv add resolvekit
    ```

=== "pip"

    ```bash
    pip install resolvekit
    ```

That installs the base package with all bundled data — no extras needed for country, region, and org resolution.

### Extras

Install an integration extra when you need it:

| Extra | Adds |
|---|---|
| `resolvekit[pandas]` | `pandas` — enables `rk.bulk()` with a `Series` input |
| `resolvekit[polars]` | `polars` — enables `rk.bulk()` with a Polars `Series` input |
| `resolvekit[parsing]` | `ahocorasick_rs` — required for `rk.parse()` and `rk.parse_bulk()` |

=== "uv"

    ```bash
    uv add 'resolvekit[parsing]'
    ```

=== "pip"

    ```bash
    pip install 'resolvekit[parsing]'
    ```

You can combine extras: `uv add "resolvekit[pandas,polars]"` (or `pip install "resolvekit[pandas,polars]"`).

## What's bundled vs what's remote

resolvekit ships two kinds of data modules.

**Bundled** modules are included in the wheel. They work offline immediately after install:

- `geo.countries`, `geo.regions`, `geo.continents`, `geo.continental_unions`
- `org.companies`, `org.governments`, `org.lenders`, `org.political_parties`, `org.providers`, `org.data_sources`

**Remote** modules are downloaded on first use from the GitHub Release tag `data-v2026.06`, verified by checksum:

- `geo.admin1`, `geo.admin2`, `geo.admin3`, `geo.admin4`, `geo.admin5`, `geo.cities`

On a fresh install these modules show `is_available=False` until you call `rk.download(...)`.

!!! warning "Heads up"
    Remote packs range from ~12 MB (`geo.admin1`) to ~380 MB (`geo.admin4`). `geo.cities` is ~154 MB. If you need them in a restricted environment or want to pre-fetch before going offline, see [Work offline and manage data packs](../how-to/work-offline-and-manage-data-packs.md).

Download a remote module on demand:

```python
import resolvekit as rk

rk.download("geo.admin1")   # ~12 MB; verifies checksum, then marks is_available=True
```

`rk.download_all()` fetches every remote module in one call. `rk.configure(auto_download=True)` downloads modules automatically the first time they are needed.

## Verify the install

```python
>>> import resolvekit as rk
>>> rk.__version__
'0.1.3'
>>> rk.resolve_id("United States")
'country/USA'
```

List all modules with their distribution and availability status:

```python
>>> import resolvekit as rk
>>> for m in rk.modules():
...     print(m.module_id, m.distribution, m.is_available)
...
geo.admin1 remote False
geo.admin2 remote False
geo.admin3 remote False
geo.admin4 remote False
geo.admin5 remote False
geo.cities remote False
geo.continental_unions bundled True
geo.continents bundled True
geo.countries bundled True
geo.regions bundled True
org.companies bundled True
org.data_sources bundled True
org.governments bundled True
org.lenders bundled True
org.political_parties bundled True
org.providers bundled True
```

Remote modules show `is_available=False` on a fresh install. Bundled modules are ready immediately.

!!! note
    Each `ModuleInfo` object also carries `size_mb`, `data_version`, `remote_url`, and `cache_path`. The table above shows the fields most useful for a quick status check.

## Next

[First resolution](first-resolution.md) — resolve your first names and understand the result object.

[Work offline and manage data packs](../how-to/work-offline-and-manage-data-packs.md) — pre-fetch remote modules, use a custom cache path, and verify checksums.
