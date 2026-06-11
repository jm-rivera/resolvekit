# How resolution works

*As of v0.1.0.*

Every call to `rk.resolve()` runs the same pipeline: normalize the input, generate candidates from the data, score them, and decide. Understanding each stage lets you reason about why a result came back as it did — and what to adjust when it doesn't.

## The pipeline at a glance

```
input string
    → sentinel check      (junk short-circuit)
    → normalization       (Unicode NFC + casefold + whitespace)
    → candidate generation (exact code, exact name, FTS, fuzzy, typo correction)
    → as_of filter        (hard point-in-time constraint — drops out-of-window candidates)
    → scoring             (feature extraction + calibrated confidence)
    → decision            (threshold + gap check → resolved / ambiguous / no_match)
    → optional pivot      (to="iso3", to="flag", …)
```

No network calls happen at resolution time. The pipeline runs entirely against bundled SQLite data.

## Sentinel check

Before the pipeline runs, the input is tested against a blocklist of known placeholder strings: `"unknown"`, `"n/a"`, `"null"`, `"tbd"`, `"999"`, and similar. These return `no_match` immediately.

```python
import resolvekit as rk

rk.resolve("n/a").status    # no_match
rk.resolve("unknown").status  # no_match
```

The blocklist only tests strings of 20 characters or fewer. Longer inputs always reach the pipeline. Legitimate short codes like `"NA"` (Namibia's ISO 3166-1 alpha-2) are not blocked — the blocklist targets the slash form `"n/a"` specifically.

You can extend or replace the blocklist:

```python
from resolvekit import Resolver, SentinelBlocklist

r = Resolver.auto(sentinel_blocklist=SentinelBlocklist(extra={"lorem"}))
```

Or disable it entirely with `sentinel_blocklist=None`.

## Normalization

Inputs that survive the sentinel check are normalized before any lookup:

1. Unicode NFC composition (so `é` and `e + combining acute` match the same entry)
2. Unicode casefolding (more thorough than `.lower()` — handles ß → ss and similar)
3. Whitespace collapse (runs of whitespace become a single space, leading/trailing stripped)

The normalized form is what gets compared against the data. The original text is preserved in `result.query_text`; the normalized form appears in `result.explain().normalized_text`.

## Candidate generation

The pipeline runs several sources in order and merges the results before scoring. Sources are ordered by cost and specificity: cheap exact lookups run first; fuzzy and typo-correction sources run after.

**exact_code** — looks up the input against every registered code system (ISO 3166 alpha-2, alpha-3, DCID, Wikidata ID, and many others). A match here is near-certain. `"DEU"`, `"DE"`, and `"country/DEU"` all hit this path for Germany.

**exact_name** — checks the normalized input against canonical names and all registered aliases. `"United States"`, `"Estados Unidos"`, and `"Vereinigte Staaten"` all resolve via this path.

**FTS (full-text search)** — runs a SQLite FTS5 query over the name index. Handles partial matches and alternate word orders. `"Cote dIvoire"` (missing the accent) resolves here at a lower confidence than the accented form.

**Fuzzy (rapidfuzz)** — computes edit-distance similarity between the query and candidate names. Catches close variants.

**SymSpell typo correction** — generates spelling corrections for the input before re-running exact and name lookups. `"Germny"` → corrected to `"germany"` → hits exact_name for `country/DEU`. The corrected form still shows `exact_name` as the match tier because the corrected string matched the canonical name exactly; the SymSpell step is the source, not the tier.

When an exact-code or exact-name hit is found, the pipeline stops generating candidates — there's no point running fuzzy after a certain match.

## Point-in-time filter (as_of)

When `context=ResolutionContext(as_of=<date>)` is passed, candidates outside their `[valid_from, valid_until)` existence window are dropped before scoring. This is a hard filter, not a score penalty — a dropped candidate never influences the result.

```python
from datetime import date
from resolvekit import Resolver, ResolutionContext

r = Resolver.auto()

r.resolve("South Sudan", context=ResolutionContext(as_of=date(2000, 1, 1))).status
# ResolutionStatus.no_match   (South Sudan did not exist until 2011)

r.resolve("South Sudan", context=ResolutionContext(as_of=date(2020, 1, 1))).entity_id
# 'country/SSD'
```

With no `as_of` the filter is a no-op — all candidates pass regardless of their existence window. Coverage is curated for known-clear cases: new states (South Sudan, Montenegro, Timor-Leste) and dissolved ones (Czechoslovakia, Yugoslavia, Netherlands Antilles).

!!! note
    `as_of` also exists directly on `within()`, `members_of()`, `related()`, and `is_member()`, where it filters the returned relationships by the same window logic.

## Scoring

Each candidate gets a feature vector, then a calibrated confidence score in `[0, 1]`.

Features include: whether there was an exact code or name hit, edit-distance similarity, query length, candidate prominence (a pre-computed relevance weight in the data), retrieval rank, and others. The scorer combines these into a raw score and then applies calibration to produce the final confidence.

The confidence is meaningful in absolute terms — it's calibrated against real resolution outcomes, not a raw similarity metric. You'll see approximately:

| Match tier | Typical confidence |
|---|---|
| `exact_code` | ~0.95 |
| `exact_name` | ~0.91 |
| `fts` (accent-stripped or partial) | ~0.84 |
| `fuzzy` | varies; often 0.70–0.88 |

These aren't guarantees — the scorer weights multiple features — but the ordering is stable: code matches score higher than name matches, which score higher than fuzzy matches.

!!! info "Why"
    We calibrate confidence rather than leaving it as raw similarity so that `0.90` means roughly the same thing across query types. A raw rapidfuzz score of `0.90` for a three-character query is much weaker evidence than `0.90` for a fifteen-character query; calibration accounts for this.

## Decision

After scoring, the decision policy applies two checks:

1. **Threshold** — the top candidate's confidence must be at or above the per-pack threshold (~0.70 for bundled packs). Below this, the result is `no_match`, with the near-miss confidence attached so you can distinguish a genuine miss from a bad input.

2. **Gap** — when two or more candidates score above the threshold, they must be separated by a minimum confidence gap for the top one to be declared the winner. If the gap is too small, the result is `ambiguous`.

The three outcomes map directly to `result.status`:

- `resolved` — one clear winner above threshold with sufficient gap
- `ambiguous` — multiple candidates above threshold, gap too small
- `no_match` — no candidate above threshold, or sentinel blocked

```python
import resolvekit as rk

# Resolved: single clear winner
rk.resolve("Germany").status       # resolved
rk.resolve("Germany").match_tier   # exact_name  ("Germany" is a name, not a code)
rk.resolve("Germany").confidence   # ≈ 0.91

# Ambiguous: two Congos, similar confidence
rk.resolve("Congo").status         # ambiguous
rk.resolve("Congo").is_ambiguous   # True

# No match: unknown input
rk.resolve("zzznotacountry").status  # no_match
```

## The explain() scorecard

`result.explain(verbosity="full")` returns a `Scorecard` you can render as text. It shows the normalized query, the match tier, confidence, reason codes, and which sources contributed:

```python
import resolvekit as rk

result = rk.resolve("United States")
scorecard = result.explain(verbosity="full")
print(scorecard.as_text())
```

```
Resolution Scorecard
============================================================
Query: "United States"
Normalized: "united states"
Status: RESOLVED
Entity: country/USA
Confidence: 90.8%
Reasons: exact_name_match
Pack: geo
Match Tier: exact_name

Match Details:
----------------------------------------
  Primary Source: geo_exact_name
  Sources:
    - geo_exact_name on name.canonical (score: 1.000)
      matched "united states"
    - geo_fuzzy on fuzzy (score: 1.000)
      matched "united states"
  Key Features:
    query_len: 13
    exact_name_hit: Yes
    fuzzy_edit_sim: 1.000
    ...
  Why this match:
    - matched canonical name exactly
    - very close edit-distance match
```

`"United States"` resolves at 90.8% via `exact_name` rather than ~95% via `exact_code` because the input was matched against the canonical name index, not a code. The score is high but not as high as submitting `"USA"` directly.

Verbosity levels are `"minimal"` (status + entity_id + confidence), `"standard"` (adds sources, features, and alternatives), and `"full"` (adds trace events and timing).

## Why results are deterministic

Resolution produces the same output for the same input, every time, without a network call. The pipeline is:

- **Fixed data** — resolution runs against bundled SQLite files that don't change unless you explicitly download an update.
- **No LLM** — there's no language model in the pipeline. Candidate generation is exact lookup + edit-distance arithmetic; scoring is a calibrated linear model over a fixed feature set.
- **No stochastic components** — rapidfuzz and SymSpell are deterministic; SQLite FTS5 returns results in a stable order.

This makes resolvekit suitable for reproducible pipelines: the same CSV processed today and next month produces identical entity IDs as long as the data version doesn't change. The data version is available at `rk.default().info.data_version`.

??? abstract "Under the hood"
    The pipeline is implemented in `resolvekit.core.engine`. `PipelineRunner` orchestrates candidate generation, constraint application, feature extraction, and scoring. `ThresholdDecisionPolicy` implements the threshold + gap decision. The scorer applies a per-pack logistic calibration model trained on held-out resolution outcomes; the calibration coefficients are bundled with each data pack.

    The multi-pack `Resolver` (returned by `Resolver.auto()`) runs each domain pack's pipeline independently and merges results before returning. For a query like `"Germany"`, the geo pack resolves it and the org pack finds no match; the geo result wins.

## parse() and the same pipeline

`rk.parse()` is a separate entry point that runs this same linking pipeline once per entity span detected in free text, returning calibrated confidence and character offsets for each match. See [Extract entities from text](../how-to/extract-entities-from-text.md) for usage.

## Next

[Confidence and ambiguity](confidence.md) — how to interpret the confidence score and handle the `ambiguous` case in pipelines that need a single answer.

[Entities and modules](entities-and-modules.md) — what an `EntityRecord` contains and how bundled versus remote modules differ.
