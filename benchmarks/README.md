# resolvekit competitive benchmark

A public, reproducible comparison of resolvekit against eight other name-resolution libraries and APIs. Everything here — datasets, adapter shims, runner, and committed results — is independent of the main resolvekit package at runtime. Nothing in this folder is imported by `resolvekit.*`; it exists to generate the numbers that back the README, the launch post, and the CI accuracy gate.

## Quick start

```bash
# one-time: install the benchmark dependency group plus calibration extras
uv sync --group benchmark --extra calibration

# run the full benchmark (all tools × all datasets)
uv run python -m benchmarks
```

For one-off runs or REPL experiments, call `run_benchmark(...)` directly:

```python
from benchmarks import run_benchmark

report = run_benchmark(
    tools=["resolvekit", "pycountry", "countryguess"],
    datasets=["geo_countries_en"],
)
print(report.to_markdown())
```

`python -m benchmarks` writes `results/latest.json` (the stable machine-readable artifact) and `results/latest.md` (a rendered summary). Both are committed. The `RunConfig` in `benchmarks/__main__.py` is the canonical CI configuration; edit it there for reproducible scheduled runs.

## Layout

```
benchmarks/
  README.md              this file
  __init__.py            public API: run_benchmark, load_dataset, ToolSpec, ...
  __main__.py            `python -m benchmarks` entry point
  core/
    engine.py            fans tools × datasets, measures, aggregates
    kernel.py            Query / Response / Observation value objects
    loader.py            BenchmarkRow schema + Parquet loader
    metrics.py           accuracy, latency, calibration, install size
    metricresults.py     AccuracyResult, LatencyResult, CalibrationResult, ToolMetrics
    profile.py           ToolProfile + measure_profile (subprocess per tool)
    report.py            BenchmarkReport → JSON / Markdown
    toolspec.py          ToolSpec dataclass + tool_registry()
  tools/
    protocol.py          ResolverAdapter Protocol
    jsoncache.py         JsonCache — shared SHA256-keyed JSON cache for online adapters
    <name>.py            one file per competitor
  build/
    __init__.py          build_all() entry point
    provenance.py        DatasetSpec registry + dataset_sha256()
    sources/             per-source build modules (cldr, geonames, wikidata, gecko)
  data/                  committed Parquet datasets + provenance.json + ATTRIBUTION.md
  cache/                 SHA256-keyed JSON caches for online adapters
  results/               latest.json, latest.md, and a history/ folder
  versions.lock          pinned competitor versions (plain text)
```

## Datasets

Committed Parquet files live under `data/`. Row counts come from `data/provenance.json`; see `data/ATTRIBUTION.md` for per-source licensing. The last full run was 2026-06-10 on macOS arm64, 18 cores, Python 3.12.13.

- **`geo_countries_en`** — 4,155 rows. English-only country queries drawn from CLDR canonical names (232 rows), GeoNames alternate names (279), Wikidata labels (648), and synthetic perturbations via Gecko (2,996). Exercises aliasing, case noise, Unicode normalization, and typos against a single entity type. ISO-only after decontamination (subnational rows mislabeled as "country" removed). resolvekit **0.793** and resolvekit_typed **0.794** lead the field by ~12 points over countryguess (0.675) and hdx_python_country (0.642); the gain over earlier runs reflects Wikidata-English alias enrichment and English-purity filtering of the synthetic source. Typed mode's wrong-match rate drops to 0.010 from 0.039 plain.

- **`geo_countries_multilingual`** — 2,240 rows. CLDR canonical names (696), GeoNames alternate names (333), and Wikidata altLabels (1,211) in `es`, `fr`, `de` (no `en` rows — purely non-English); de 620, es 670, fr 950. ISO-only after decontamination. resolvekit **0.632** and resolvekit_typed **0.614** lead all offline tools, ahead of hdx_python_country (0.565) and countryguess (0.512). The online `data_commons_resolve` adapter scores higher (0.827), reflecting Google's investment in multilingual country coverage; broader RU/ZH/AR coverage for resolvekit is scope-for-later, not a current deficiency in es/fr/de.

- **`ambiguous`** — 58 rows (28 country + 30 sub-national admin/city). Hand-authored queries whose surface form is compatible with two or more canonical entities (e.g. "Georgia"). Measures how honestly a tool signals ambiguity rather than picking one answer. resolvekit **0.872** (100% coverage, 0.000 wrong-match). Tools that appear to ace this dataset (e.g. hdx_python_country 1.000) do so at ~47.5% coverage — they are scored only on the 28 country rows and, because matching is any-of, returning one of two valid countries counts as correct; they never have to signal ambiguity or handle the sub-national rows resolvekit covers at 100%.

- **`no_match`** — 43 rows (all country-typed junk). Hand-authored queries that should not resolve (fictional states, empty strings, misspelled nonsense). Measures abstention — tools that always return something score 0 here by design. resolvekit untyped **0.771**, resolvekit_typed **0.914**. Four strict matchers (country_converter, pycountry, geonamescache, hdx_python_country) score 1.000 here simply by abstaining on input they can't match — the same strictness that makes country_converter score 0.566 on `geo_countries_en`; the pure-fuzzy rapidfuzz_dict scores 0.200 because it matches everything. The no_match winners are the recognition losers.

- **`geo_admin`** — 2,657 rows. Admin1/admin2/admin3 queries sampled directly from the shipped resolver store with synthetic perturbations. Because entities are sampled from the same store the scorer runs against, every sampled entity is resolvable — there are no dead golds dragging the score down, which is why accuracy rose sharply from earlier runs. resolvekit **0.935**, resolvekit_typed **0.977**. data_commons_resolve **0.598**.

- **`geo_cities`** — 2,148 rows. City queries sampled directly from the shipped resolver store with synthetic perturbations. Because entities are sampled from the same store the scorer runs against, every sampled entity is resolvable — there are no dead golds dragging the score down, which is why accuracy rose from earlier runs. resolvekit **0.858**, resolvekit_typed **0.862**. data_commons_resolve **0.502**.

- **`eval_geo`** — Hand-curated geo eval set; the primary dev-loop regression gate for resolvekit. 467 rows total, 367 measured after 100-query warmup. Covers `country`, `admin1`–`admin5`, `city`, `continent`, `continental_union`, `world_region`. Per-stratum row counts are calibrated for statistical power (≥40 rows per entity type). Rows are tagged with `capabilities` (`iso_code`, `informal_alias`, `transliteration`, `multilingual`) for per-capability accuracy breakdown; difficulty: easy/medium/hard; language: predominantly `en`. Many rows have multiple valid expected IDs — any-of matching is used.

  **Restricted to resolvekit and resolvekit_typed only.** Competitors are skipped automatically (`skipped_reason="eval: restricted to resolvekit variants"`). A CI gate step enforces a minimum floor; see `benchmarks/eval_gate.json` and `scripts/benchmark/check_eval_gate.py`.

  resolvekit **0.888** (wrong-match 0.049), resolvekit_typed **0.913** (wrong-match 0.025). ECE **0.043**. data_commons_resolve **0.763**. CI gate floor: **0.82** (set at `round(0.8747 − 0.05, 2)` from the earlier 0.8747 baseline).

  To run resolvekit against this dataset only:

  ```python
  from benchmarks import run_benchmark

  report = run_benchmark(
      tools=["resolvekit", "resolvekit_typed"],
      datasets=["eval_geo"],
      measure_cold_start=False,
  )
  print(report.to_markdown())
  ```

  **Caveats for `eval_geo` numbers:**
  - Needs the deep geo tiers loaded locally; bundled-only scores are around 0.29.
  - Expected IDs use mixed namespaces (`wikidataId/`, `geoId/`, `country/`, `nuts/`, `groups/`, `undata-geo/`). A resolver returning the correct entity under a different namespace counts as wrong until cross-namespace aliases are added. The 6 worst stale city golds (Warsaw, Vienna, La Paz, Cologne, Casablanca, Accra) were repointed to live entity-ids in the 2026-06-10 run, so the "lower bound" gap is smaller though not eliminated.
  - `continent`, `continental_union`, `world_region`, `admin5` packs are being actively expanded; scores on those entity types will improve as data lands.

- **`eval_org`** — Hand-curated org eval set, 25 rows, re-scoped in the 2026-06-10 gold-liveness cleanup to IGOs and development organizations that actually ship in the org pack (e.g. African Development Bank, Asian Development Bank, ILO, WFP, UNDP, FAO, Global Partnership for Education). resolvekit **0.750**. The earlier 54-row set was dominated by international NGOs (MSF, Oxfam, Human Rights Watch, Amnesty, Red Cross, Save the Children) that the org pack does not cover; those rows were dropped — honest re-scope, not a fix to the resolver. The org pack remains underdeveloped relative to geo. This dataset is not gated. Restricted to resolvekit variants.

## Competitors

Eight adapters are in the active comparative set. The `name` column matches the argument accepted by `run_benchmark(tools=[...])`; `offline` indicates whether the adapter hits the network at query time; `supports` lists the entity types the adapter answers for. Pinned versions live in `versions.lock` — treat that file as the source of truth, not the table below.

Each tool is scored only on rows whose `entity_type` falls within its declared `supports` set. A `coverage` column in the results reports what fraction of each dataset the tool attempted. A tool with 90% accuracy at 30% coverage is a different proposition from one with 60% accuracy at 100% coverage.

| name | offline | supports | notes |
|---|---|---|---|
| `resolvekit` | yes | country, country_region, admin1–5, city, continent, continental_union, world_region, org | `Resolver.auto()` / `from_modules(...)`; emits confidence scores. |
| `resolvekit_typed` | yes | (same as resolvekit) | Passes `entity_type` + language hints from the dataset row. A `city` hint admits places at any admin level. Improves accuracy and substantially lowers wrong-match rate. |
| `pycountry` | yes | country | Exact-only ISO lookups. |
| `country_converter` | yes | country | Alias table + regex; a staple of the data-science stack. |
| `countryguess` | yes | country | Zero-dep fuzzy country resolver; ~200 kB wheel. |
| `hdx_python_country` | yes | country | Multilingual EN/ES/FR/DE exact + EN fuzzy (OCHA-DAP). |
| `geonamescache` | yes | country, city | Offline GeoNames cities dump; bundled JSON is ~165 MB. |
| `rapidfuzz_dict` | yes | country | RapidFuzz over pycountry ISO3 + curated aliases. |
| `data_commons_resolve` | no | country, admin1, admin2, city | Google Data Commons `/resolve` V2 API; cached for reproducibility. |

**`ror_affiliation`:** the ROR adapter (`benchmarks/tools/ror.py`) is in the repo but excluded from the active set. Its output uses the `ror/` ID namespace, which isn't present in any committed dataset's `expected_ids`, so it structurally can't score correct answers regardless of match quality. It'll be re-added once a dataset with `ror/`-prefixed expected IDs ships.

## How to add a tool

1. Create `benchmarks/tools/<name>.py` implementing the `ResolverAdapter` Protocol from `benchmarks/tools/protocol.py`. Declare a `spec` ClassVar of type `ToolSpec` and a `resolve(query: Query)` method:

   ```python
   from __future__ import annotations

   from typing import ClassVar

   from benchmarks.core.kernel import Query, Response
   from benchmarks.core.toolspec import ToolSpec


   class MyToolAdapter:
       spec: ClassVar[ToolSpec] = ToolSpec(
           name="mytool",
           distribution="my-dist-name",
           offline=True,
           entity_types=frozenset({"country"}),
       )

       def warmup(self) -> None:
           pass  # load heavy state here, called once before measurement

       def resolve(self, query: Query) -> Response:
           # query.text holds the raw string to resolve
           ...
           return Response(status="match", match_ids=("Q123",))

       def version(self) -> str | None:
           return None
   ```

   Language-based filtering isn't implemented in the runner — language scope for a tool should be documented in its class docstring.

2. Register the adapter by adding the class to the import list in `benchmarks/core/toolspec.py` — the import is the registration step.

3. Add the library to the `benchmark` dependency group in `pyproject.toml` so `uv sync --group benchmark` installs it.

4. Re-run `uv run python -m benchmarks` and inspect `results/latest.md`.

## How to rebuild datasets

The committed Parquet files plus `provenance.json` are the reproducibility baseline. Rebuilding is only needed when upstream sources change.

```bash
uv run python -c "from benchmarks.build import build_all; build_all()"
```

This requires network access (CLDR release zip, GeoNames dump, Wikidata SPARQL endpoint) and the resolvekit calibration stack for the synthetic slice. The build records SHA256 digests and upstream versions into `data/provenance.json`; reviewers see those move in the diff.

## Metrics

Per (tool, dataset) the runner records:

- **Accuracy (overall)** — fraction of measured rows whose response includes at least one expected ID (or returns `no_match` when the expected set is empty).
- **Accuracy (by capability / language / difficulty / entity_type)** — same ratio stratified by the tags on each row.
- **Wrong-match rate** — fraction of rows where the tool returned `match` but the ID didn't match any expected answer.
- **Abstention precision / recall** — of rows the tool said `no_match` on, how many should have been no-match; of rows that should be no-match, how many the tool correctly refused.
- **Ambiguity recall** — of rows with ≥2 expected IDs, fraction of responses that returned at least one correct answer.
- **Latency p50 / p95 / p99 / mean / min / max** — measured with `time.perf_counter()` around a single `resolve(query)` call.
- **Throughput (qps)** — warm measurements divided by wall-clock seconds.
- **Cold-start (ms)** — fresh subprocess: import, construct, warmup, one resolve. Measured once per tool (not per dataset) via `measure_profile`.
- **Memory (RSS MB)** — subprocess peak RSS (`resource.getrusage(RUSAGE_SELF).ru_maxrss`) captured in an isolated process per tool, so each tool's footprint is independent of measurement order.
- **Install size (MB)** — sum of files reported by `importlib.metadata.distribution(...).files`.
- **Calibration** — ECE, Brier score, and reliability-bin data; resolvekit only (the only adapter emitting confidence scores).

See `benchmarks/core/metrics.py` for the exact definitions.

## Online tools and caching

The `data_commons_resolve` and `ror_affiliation` adapters cache every upstream response as a SHA256-keyed JSON file under `cache/data_commons/` and `cache/ror/`. The committed caches are the reproducibility baseline: a clean checkout plus `uv run python -m benchmarks` produces deterministic online numbers without hitting live endpoints.

To refresh against live endpoints:

```python
from benchmarks import run_benchmark

report = run_benchmark(refresh_online_cache=True)
```

By default `python -m benchmarks` only runs online adapters on `ambiguous` and `no_match` — the two small hand-authored slices — so a fresh checkout doesn't hammer DC or ROR. Passing `datasets=[...]` explicitly opts into online coverage of the larger slices.

## Footprint

resolvekit's footprint scales with use case. Numbers below come from the committed `results/latest.json` run (macOS arm64, Python 3.12.13).

**Wheel size** — ~9 MB (code + bundled country pack). The deep geo data pack is ~807 MB, downloaded on demand. Both figures are reported in `results/latest.json` as `wheel_size_mb` and `data_size_mb`.

**RSS by use case:**

- **Country/region resolution or `Resolver.lite()`** — ~50–100 MB. The country pack ships in the wheel; no download needed for this tier.
- **Full geo (admin + city) with typed hints** — ~125–175 MB (the benchmark's profiled peak at full-suite load).
- **No-hint fuzzy/typo queries over fully-loaded deep admin and city tiers** — builds a large in-memory SymSpell index (~1.1–1.3 GB). This is the inherent cost of typo-tolerant resolution across ~720 k admin/city names. Most callers don't hit this path: deep geo tiers are opt-in, typed callers stay light, and `Resolver.lite()` never touches it.

**Cold-start** is noisy run-to-run; treat any specific number as approximate. The first-ever cold start builds a composed-SQLite cache (~15 s); every subsequent run reads from that cache.

!!! note
    Deep geo tiers download anonymously from the public GitHub data release on first use. The bundled country pack ships in the wheel and needs no download.

## Known limitations

- **Online tools are cached, not live.** DC `/resolve` and ROR `/affiliation` results reflect the moment the cache was primed. Live refresh is supported (`refresh_online_cache=True`) but rate limits make it a manual operation, not a CI step. Cached latency numbers encode the runner's network distance to the endpoints and aren't portable between hosts.
- **Multilingual coverage is es/fr/de only.** `geo_countries_multilingual` covers those three languages; RU/ZH/AR is future scope. The `eval_geo` set is predominantly English — per-language breakdowns for de/fr/es there reflect very small sample counts and aren't yet statistically meaningful.
- **Install footprint is approximate.** The runner sums `importlib.metadata.distribution().files`. Tools that download data outside the wheel (resolvekit's ~807 MB geo pack, some GeoNames variants) understate disk usage in that figure. resolvekit reports `wheel_size_mb` (~9 MB) and `data_size_mb` (~807 MB) separately.
- **Calibrated confidence is a resolvekit-only signal.** No other adapter emits confidence scores today, so the calibration table only lists resolvekit.
- **Ranking quality isn't measured.** Top-1 accuracy only; nDCG and MRR aren't comparable across tools with different corpora.
- **Parse precision is data-tier dependent.** The committed `parse_latest.json` and the `min_precision` gate (0.95) are measured against bundled-only data — what CI installs — where precision is **0.9841** (1 FP in 50 rows). With the deep geo tiers loaded locally, `Resolver.auto()` matches common English words (`"deal"`, `"energy"`, `"long"`) against obscure admin/city names, dropping parse precision to ~0.86. Closing that gap is the deferred Phase-3 coherence work; until then, callers using deep tiers with `parse()` should expect lower precision than the bundled-only gate reports.
- **`rapidfuzz_dict` accuracy on `ambiguous` is expected to be poor.** It has no ambiguity mechanism; the low score is a property of the tool, not the slice.

## Where to read more

- `data/provenance.json` — per-dataset row counts, source breakdown, SHA256 digests, and upstream versions.
- `data/ATTRIBUTION.md` — upstream licences and attribution statements.
- `results/latest.md` — rendered summary of the most recent committed run.
- `results/latest.json` — the same numbers in stable machine-readable form.
- `versions.lock` — pinned competitor versions for the current committed run.
