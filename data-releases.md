# How to cut a data release

Build the data packs, gzip the assets for remote tiers, stamp every
`metadata.json` with the new CalVer, publish the release on GitHub, and
push the matching code. End state: `pip install resolvekit` loads the new
bundled data, and remote tiers download from the new release on first use.

## Before you start

- `gh` authenticated against `jm-rivera/resolvekit` (`gh auth status`).
- Working tree clean except for whatever you mean to ship.
- A CalVer in your head: `YYYY.MM` (e.g. `2026.06`). Bump it if you need to
  redo a published version — GitHub release tags are immutable.

!!! info "Why the order matters"
    The release flow has three coupled artefacts: the wheel-shipped data,
    the GitHub release assets, and the per-module `metadata.json` that ties
    them together. Cutting one without the others leaves users with
    metadata pointing at assets that don't exist (or stale assets pointing
    at code that doesn't read them). The step order below is the one that
    doesn't break either consumer.

## Steps

1. **Build the data.**

    ```bash
    uv run python -m scripts.build.build_data
    ```

    Defaults build the geo preset. To change scope (e.g. `ALL`, or a single
    module), edit the `BuildDataSettings(...)` block in
    `scripts/build/build_data.py`. There is no CLI.

    Output lands in `src/resolvekit/_data/{domain}/{module}/`. Each pack
    gets `entities.sqlite`, `metadata.json`, and — when the recipe sets
    `include_symspell=True` — `symspell.dict`. The builder stamps
    `distribution="bundled"`; the release script promotes remote tiers
    later.

    !!! warning "Schema-version changes require rebuilding geo.continents too"
        `build_data.py` does **not** rebuild `geo.continents` — that pack
        is produced by a separate seed-driven script.  If you bumped
        `ENTITY_SCHEMA_VERSION` in `src/resolvekit/core/datapack.py`, use
        `build_all_bundles()` instead to rebuild all packs in one pass:

        ```python
        from scripts.build.build_data import build_all_bundles
        build_all_bundles()
        ```

        Or run the continents build explicitly after step 1:

        ```bash
        uv run python -m scripts.build.build_continents
        ```

        Skipping this leaves `geo.continents` at the old schema version
        while every other pack carries the new one — a silent mismatch
        that only surfaces as a logged warning (minor bump) or a hard
        `IncompatibleVersionError` (major bump) at load time.

    !!! warning "Heads up: targeted rebuilds clobber calibrators"
        `_publish_pack` does an atomic swap of the whole module directory.
        Any file the builder didn't produce in this run (calibrators,
        hand-curated overrides) gets wiped. If you rebuild
        `geo.countries`, restore the calibrator afterwards — see
        [Troubleshooting](#troubleshooting).

2. **Cut the release.**

    ```bash
    RESOLVEKIT_RELEASE_CALVER=2026.06 RESOLVEKIT_RELEASE_EXECUTE=1 \
        uv run python -m scripts.release.release_data
    ```

    For each remote module (`geo.admin1..5`, `geo.cities`) this gzips
    `entities.sqlite` and every entry in `metadata.artifacts`
    (e.g. `symspell.dict`), then writes the per-artifact spec into
    `metadata.remote_artifacts`. For bundled modules it just stamps
    `data_version` and `datapack_id`.

    Side effects:

    - `src/resolvekit/_data/{...}/{entities.sqlite,symspell.dict}.gz` —
      the assets you'll upload in step 5. Gitignored.
    - `release-manifest.json` at repo root — local asset map.
      Gitignored.
    - One row per module appended to `data/build/registry/releases.json`
      — local ledger consumed by benchmarks and `list_releases()`.
      Gitignored.

    Drop `RESOLVEKIT_RELEASE_EXECUTE=1` for a dry run that prints the
    planned actions without writing anything.

3. **Sync the aggregate manifest.**

    ```bash
    uv run python -m scripts.release.sync_manifest
    ```

    Regenerates `src/resolvekit/_data/manifest.json` from each pack's
    `metadata.json`. This file IS tracked and ships in the wheel — the
    runtime reads it to know what modules exist and where to download
    remote ones from.

    !!! info "Why two manifests"
        `release-manifest.json` (repo root, gitignored) is the local
        asset-staging map for the release script's bookkeeping.
        `src/resolvekit/_data/manifest.json` (tracked, in the wheel) is
        what the runtime loads. They are different shapes; don't confuse
        them.

4. **Verify.**

    ```bash
    uv run python -m scripts.release.verify_bundled_data
    ```

    Expected output:

    ```
    OK: verified 15 module(s) from .../manifest.json
    ```

    Bundled modules are checked for sqlite presence + SHA-256 match.
    Remote modules are checked for `metadata.json` presence plus a
    populated `remote_artifacts['sqlite']` — their real bytes live on the
    release, not locally.

5. **Stage and upload the GitHub release.**

    Flatten the per-tier `.gz` files from step 2 into a staging directory
    with the asset names `gh release create` will see:

    ```bash
    STAGE=/tmp/rk-release-data-v2026.06
    mkdir -p "$STAGE"
    for tier in admin1 admin2 admin3 admin4 admin5 cities; do
        for kind in entities.sqlite symspell.dict; do
            cp "src/resolvekit/_data/geo/$tier/$kind.gz" \
               "$STAGE/geo-$tier-$kind.gz"
        done
    done
    ```

    Twelve assets total (6 remote tiers × 2 artifacts). The asset names
    must match `metadata.remote_artifacts[*].url`'s last path segment —
    the runtime fetches by exact filename. The `release_data` stdout
    summary at the end of step 2 lists them.

    Then:

    ```bash
    gh release create data-v2026.06 /tmp/rk-release-data-v2026.06/*.gz \
        --title "Data v2026.06" \
        --notes "Geo (admin1-5, cities) + org datapack assets."
    ```

    !!! warning "Heads up: upload before pushing code"
        The committed `metadata.json` files point at the release URLs.
        If you push code before the assets are uploaded, anyone who does
        `pip install` and uses a remote module gets a 404 until you catch
        up. Always: upload, then push.

6. **Clean the source tree.**

    Remove the now-published bytes for remote tiers (gitignored but disk
    is finite — admin4 alone is ~365 MB uncompressed):

    ```bash
    for tier in admin1 admin2 admin3 admin4 admin5 cities; do
        d="src/resolvekit/_data/geo/$tier"
        rm -f "$d/entities.sqlite" "$d/symspell.dict" \
              "$d/entities.sqlite.gz" "$d/symspell.dict.gz"
    done
    ```

    Leave bundled-tier sqlites and symspell files in place — those ship
    in the wheel.

7. **Commit and push.**

    Stage the metadata + manifest changes (not the gitignored locals):

    ```bash
    git add src/resolvekit/_data/
    git commit -m "data: refresh to data-v2026.06"
    git push origin main
    ```

## Verify it worked

```bash
uv run python -c "
import resolvekit
r = resolvekit.default()
print('data_version:', r.info.data_version)
print(r.resolve('Italy').entity_id)
"
```

Expected: `data_version: 2026.06`, `country/ITA`. Then trigger a remote
module download to confirm the GitHub release assets resolve and the
per-artifact checksums match the stamped `metadata.json`:

```bash
uv run python -c "
import resolvekit
resolvekit.configure(auto_download=True)
resolvekit.download('geo.admin5')
"
```

Expected: progress bars for `geo-admin5-entities.sqlite.gz` and
`geo-admin5-symspell.dict.gz`, then a clean exit. `admin5` is the
cheapest tier to test against (~1.9 MB sqlite, ~38 KB dict). Cache
state can be inspected via `resolvekit.modules()`; cache files land at
`$XDG_CACHE_HOME/resolvekit/`, defaulting to `~/.cache/resolvekit/`.

## Replacing a published release

Last resort. GitHub release tags are meant to be immutable — anyone
who's installed the wheel and used a remote module has cached bytes
whose SHA matches the released ones. Deleting a release and re-uploading
different bytes at the same tag breaks those consumers (they hit a
checksum mismatch at load time, not a silent wrong-data failure, but
they're stuck until they `resolvekit.clear_cache()`).

The default answer is **bump the CalVer**, not delete.

### Bump the CalVer (the safe path)

1. Fix the source data, builder code, or whatever caused the bad
   release.
2. Re-run steps 1–7 with a fresh CalVer (e.g. `2026.06` →
   `2026.06.1`, or just the next month).
3. Edit the bad release's notes on GitHub to flag the supersession so
   anyone landing on it via search knows:

    ```bash
    gh release edit data-v2026.06 \
        --notes "Superseded by data-v2026.06.1 — do not use."
    ```

The bad release stays tagged but visibly deprecated. Existing consumers
keep working off their cached bytes; new consumers see the warning.

### Delete and re-cut at the same CalVer (narrow window only)

Only safe within the same publish session, before any downstream
consumer has pulled the assets — practically, between `gh release
create` and the `git push` that ships the matching metadata. After
that, assume consumption.

1. **Delete the release and tag.**

    ```bash
    gh release delete data-v2026.06 --cleanup-tag --yes
    ```

    The `.gz` assets are gone from GitHub and cannot be restored from
    there. Keep the local staging copy in `/tmp/rk-release-data-vYYYY.MM/`
    until you're sure you're done.

2. **Roll back the local release ledger** so the conflict guard
   doesn't see a stale row for the same CalVer. There's no API; edit
   the JSON:

    ```bash
    # Drop every "version": "2026.06" object from the releases array
    $EDITOR data/build/registry/releases.json
    ```

3. **Re-cut from step 2 of the main flow.** The new run's
   `gz_sha256` values will differ from the previous attempt's (gzip
   embeds a timestamp), so the per-module `metadata.json` files get
   re-stamped with the new hashes. Commit those before pushing.

!!! warning "Heads up: don't force-push deleted-release metadata over an already-pushed commit"
    If the bad-release commit has been pushed, anyone who pulled
    main has the old metadata pointing at hashes for assets that no
    longer exist. A force-push to "fix" it requires every consumer
    to re-pull. Prefer the bump path once code has been pushed.

## Troubleshooting

**`Refusing to re-release data-vX.YY: a GitHub release tag with that
name already exists.`** — Tag is immutable. Bump the CalVer and re-run
from step 2.

**Calibrator missing after a targeted rebuild.** The builder doesn't
produce calibrators and `_publish_pack` swaps the module directory
atomically. Restore from the previous release commit:

```bash
git checkout <prev-release-commit> -- \
    src/resolvekit/_data/geo/countries/geo_calibrator.json
```

Then re-add it to the module's `metadata.json` under `artifacts` and
`checksums`:

```json
"artifacts": {
    "symspell": "symspell.dict",
    "calibrator": "geo_calibrator.json"
},
"checksums": {
    "sqlite": "...",
    "symspell": "...",
    "calibrator": "<sha256 of the restored file>"
}
```

Re-run step 3 (`sync_manifest`) and step 4 (`verify_bundled_data`).

**Gzip hashes differ between two runs of the same CalVer.** Expected.
`gzip.open` embeds the current timestamp in the header by default, so
`gz_sha256` shifts on every re-run even with identical decompressed
content. Always re-stage assets from the most recent `release_data` run
before uploading — the metadata's hashes are what runtime verifies
against.

**Pre-commit hook auto-fix conflicts with unstaged WIP.** Pre-commit
stashes unstaged changes before running hooks; if a hook then modifies
a staged file in a way that conflicts with the stash, the commit is
rolled back. Workaround: `git stash push --keep-index` first, commit,
then `git stash pop`.

## See also

- `scripts/release/release_data.py` — the script that does the heavy
  lifting in step 2. Read `_prepare_remote_module` for the per-artifact
  gzip + spec generation.
- `scripts/release/sync_manifest.py` — manifest regeneration.
- `src/resolvekit/core/datapack.py` — `RemoteArtifactSpec` and the
  `DataPackMetadata` validator that enforces the artifacts /
  remote_artifacts key parity.
- `src/resolvekit/core/remote.py` — runtime download flow. The atomic
  guarantee (clear cache on partial failure) lives in
  `download_module_data`.
