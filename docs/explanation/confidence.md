# Confidence scores

*As of v0.1.*

The `confidence` field on a `ResolutionResult` is a calibrated probability estimate, not a raw similarity score. A value of `0.93` means the model assigns roughly a 93% probability that the matched entity is correct—given the input text, the candidate, and the features the pipeline extracted. It's fit on labeled resolution data, so the scale is meaningful rather than arbitrary.

The score runs from 0 to 1. Each data pack has a built-in decision threshold (around 0.70 with calibration). Results that clear the threshold become `resolved`; those that don't become `no_match`.

The same confidence field appears on entities returned by `parse()` and `parse_bulk()`—each extracted span carries its own score from the same calibrated model. When you use the `as_of` temporal filter, candidates outside their validity window are dropped before scoring runs, so the confidence you see is already conditioned on the entity existing at the queried point in time (see [knowledge graph and temporal data](knowledge-graph.md) for how validity windows work).

## What the score reflects

Match quality drives the score directly. An exact code or canonical-name match scores near 1.0. A fuzzy or typo-corrected match scores lower because the pipeline is less certain the input maps to that entity.

```python
import resolvekit as rk

result_exact = rk.resolve("Germany")
print(result_exact.confidence)  # ≈ 0.91
print(result_exact.match_tier)  # exact_name

result_fuzzy = rk.resolve("Germny")   # one character missing
print(result_fuzzy.confidence)  # ≈ 0.91
print(result_fuzzy.match_tier)  # exact_name
```

Both resolve to `country/DEU`. A canonical-name query like `"Germany"` hits `exact_name`; a code query like `"DEU"` or `"DE"` hits `exact_code` and scores slightly higher (≈ 0.95). The one-character typo in `"Germny"` goes through SymSpell correction first, so it also lands on `exact_name` at a similar confidence level.

!!! note
    Exact confidence values shift slightly when the calibrator is retrained on new labeled data. Treat reported floats as approximate.

!!! note
    `match_tier` tells you *how* the match was made (`exact_code`, `exact_name`, `fuzzy`, `fts`, `acronym`). Confidence tells you *how certain* the model is about that match. The two are related but distinct.

## Ambiguous results

When two or more entities score close enough that the pipeline can't pick one, the result status is `ambiguous` and `result.confidence` is `None`. Each *candidate* carries its own confidence score via `result.candidates`.

```python
import resolvekit as rk

result = rk.resolve("Congo")
print(result.is_ambiguous)        # True
print(result.confidence)          # None

for c in result.candidates[:2]:
    print(c.entity_id, round(c.confidence, 3))
# country/COD ≈ 0.908
# country/COG ≈ 0.908
```

The gap between the two scores is too small to confidently pick one. Democratic Republic of the Congo and Republic of the Congo are both plausible matches.

### Controlling ambiguous behavior

`resolve_id` raises `AmbiguousResolutionError` by default. Use `on_ambiguous` to change that:

```python
from resolvekit import AmbiguousResolutionError

# raise (default)
try:
    rk.resolve_id("Congo")
except AmbiguousResolutionError as e:
    top_two = e.candidates[:2]   # list of CandidateSummary

# return None
rk.resolve_id("Congo", on_ambiguous="null")   # None

# pick the highest-scoring candidate
rk.resolve_id("Congo", on_ambiguous="best")   # "country/COD"
```

`on_ambiguous="best"` silently picks the top candidate. Use it only when downstream logic can tolerate occasional misidentification.

## Near-miss no_match results

A `no_match` result caused by a *below-threshold* score still carries `result.confidence`. That distinguishes a near-miss from a true no-candidate.

```python
import resolvekit as rk

r = rk.Resolver.auto(confidence_threshold=0.99)
result = r.resolve("Germny")

print(result.status)       # no_match
print(result.confidence)   # ≈ 0.91
print(result.reasons)      # [<ReasonCode.BELOW_CONFIDENCE_THRESHOLD: 'below_confidence_threshold'>]
r.close()
```

Here `confidence ≈ 0.91` tells you there's a strong candidate (`country/DEU`) that just didn't clear the stricter threshold. A confidence of `None` on a `no_match` means no candidate reached the pipeline at all—nothing remotely matched.

## Adjusting the threshold

The default threshold (~0.70) is tuned for country and geo entity resolution. You can override it at resolver construction time:

```python
import resolvekit as rk

# Stricter: only accept near-certain matches
strict = rk.Resolver.auto(confidence_threshold=0.95)

# More permissive: accept uncertain fuzzy matches
lenient = rk.Resolver.auto(confidence_threshold=0.55)
```

A lower threshold increases recall but also increases false positives. A higher threshold reduces false positives but returns `no_match` on inputs the default would resolve. The right value depends on how you handle unresolved rows downstream.

!!! warning "Heads up"
    `confidence_threshold` applies at construction time to all loaded packs. There's no per-call override. If you need different thresholds for different inputs, build two resolvers.

## Inspecting a decision

`result.explain(verbosity="full").as_text()` re-runs the pipeline with full tracing and prints the scorecard:

```python
import resolvekit as rk

result = rk.resolve("Germany")
print(result.explain(verbosity="full").as_text())
```

Output (observed):

```
Resolution Scorecard
============================================================
Query: "Germany"
Normalized: "germany"
Status: RESOLVED
Entity: country/DEU
Confidence: 90.8%
Reasons: hierarchy_preference_tiebreak
Pack: geo
Match Tier: exact_name

Match Details:
----------------------------------------
  Primary Source: geo_exact_name
  Sources:
    - geo_exact_name on name.canonical (score: 1.000)
      matched "germany"
    - geo_fuzzy on fuzzy (score: 1.000)
      matched "germany"
  Key Features:
    exact_name_hit: Yes
    ...
```

Three verbosity levels exist:

| Level | What's included |
|-------|-----------------|
| `"minimal"` | Status, entity ID, confidence |
| `"standard"` (default) | + source contributions, key features, alternatives |
| `"full"` | + raw trace events, per-stage timing |

`as_text()` is for terminals and logs. `as_markdown()` and `as_json()` return the same data in other formats.

!!! note
    `explain()` re-executes the pipeline with a trace sink attached, so it's slower than a normal `resolve()` call. Call it when debugging a specific result, not in batch paths.

## Accuracy and multilingual coverage

Confidence calibration is strongest for countries and geo places queried in English. The underlying labeled data is primarily English, so the model's probability estimates are well-calibrated there.

Multilingual coverage is uneven. French, Spanish, and German country names resolve reliably; other languages have thinner name dictionaries. For non-English inputs, treat the confidence score as a relative ordering signal rather than a precise probability—a 0.80 on a French query carries more uncertainty than a 0.80 on an English one.

Org entity resolution (companies, lenders, political parties) is less calibrated than geo resolution at this stage. The score ordering is reliable, but the absolute values are less precisely anchored to empirical accuracy.

## Next

- [How resolution works](how-resolution-works.md) — the pipeline stages that produce candidates and features before scoring.
- [API reference](../reference/api.md) — `ResolutionResult`, `confidence_threshold`, `explain()`, and `on_ambiguous` parameter details.
