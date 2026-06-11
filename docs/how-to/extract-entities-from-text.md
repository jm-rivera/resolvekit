# How to extract entities from free text

`parse()` and `parse_bulk()` scan free text and link every mention of a pack-known entity to a canonical ID, with character offsets and calibrated confidence — offline, no model download required.

## Before you start

`parse()` requires the `[parsing]` extra, which installs `ahocorasick_rs` for the Aho-Corasick dictionary scan. Without it, calling `parse()` raises `ImportError`.

```bash
pip install 'resolvekit[parsing]'
# or
uv add 'resolvekit[parsing]'
```

## Output format

Given the text `"The summit in Nairobi gathered leaders from Kenya, Uganda and the United States."`, `parse()` returns one `ParsedEntity` per linked span. Linked spans have `entity_id` set; ambiguous ones have `entity_id=None` and `confidence=None`:

```
'Kenya' [44:49] -> country/KEN (geo.country) 0.91
'Uganda' [51:57] -> country/UGA (geo.country) 0.91
'the United States' [62:79] -> country/USA (geo.country) 0.91
```

!!! note
    Nairobi is not detected on a fresh bundled-only install. Detection is dictionary-first over the **loaded packs**. The bundled wheel includes countries, regions, continents, and continental unions — but not cities. Download the `geo.cities` pack to detect city spans like Nairobi. Results vary once remote packs are downloaded — additional spans may appear as ambiguous (with `entity_id=None`) when packs add new candidate matches.

## Basic usage

```python
import resolvekit as rk   # pip install 'resolvekit[parsing]'

result = rk.parse("The summit in Nairobi gathered leaders from Kenya, Uganda and the United States.")
for e in result:
    if e.entity_id:
        print(f"{e.surface!r} [{e.start}:{e.end}] -> {e.entity_id} ({e.entity_type}) {e.confidence:.2f}")
# 'Kenya' [44:49] -> country/KEN (geo.country) 0.91
# 'Uganda' [51:57] -> country/UGA (geo.country) 0.91
# 'the United States' [62:79] -> country/USA (geo.country) 0.91
```

`ParseResult` is iterable, has `len()`, and exposes `.to_dataframe()`.

## ParsedEntity fields

Each item yielded from a `ParseResult` is a `ParsedEntity`:

| Field | Description |
|---|---|
| `surface` | The matched substring as it appears in the input. |
| `start`, `end` | Character offsets into the original string (half-open: `text[start:end] == surface`). |
| `entity_id` | Canonical entity ID, e.g. `"country/KEN"`. |
| `entity_type` | Pack type, e.g. `"geo.country"`. |
| `pack_id` | The data pack that matched this span. |
| `status` | Resolution status (same enum as `resolve()`). |
| `confidence` | Calibrated confidence (0–1). |
| `resolution` | Full `ResolutionResult`; call `.resolution.explain()` to inspect scoring. |
| `output` | The `to=` pivot value — `None` unless you passed `to=`. |

`row_idx` is also present when the entity comes from `parse_bulk()`, tagging which input row it belongs to.

## Pivot to a code with `to=`

Pass `to=` to get a scalar code per entity alongside the entity record:

```python
import resolvekit as rk

[(e.surface, e.output) for e in rk.parse("Travel from France to Brazil", to="iso3")]
# [('France', 'FRA'), ('Brazil', 'BRA')]
```

The pivot fills `e.output`; all other fields are still available.

## How a detected span resolves

A span the detector finds lands in one of four states. Knowing which is which saves a confused debugging session:

| State | `status` | In the entity list? | Meaning |
|---|---|---|---|
| Linked | `resolved` | yes — `entity_id` set | matched a pack entity confidently |
| Ambiguous | `ambiguous` | yes — `entity_id=None` | competing candidates, none confident |
| NIL | `no_match` | only with `include_nil=True` | matched a candidate but scored below the abstain floor |
| Dropped | — | no | filtered before scoring (see `dropped_spans` reasons below) |

On clean country and organization text most spans are `resolved`. The ones you can't link usually come back `ambiguous`, not `no_match` — a detected mention with no confident winner:

```python
import resolvekit as rk

result = rk.parse("The Gates Foundation partnered with Gavi in Malawi.")
for e in result:
    print(f"{e.surface!r:20} {e.status} {e.entity_id}")
# 'Gates Foundation'   ambiguous None
# 'Gavi'               resolved org/oecd:agency:1311:1
# 'Malawi'             resolved country/MWI
```

## Inspect what was dropped

`ParseResult.dropped_spans` is a debug channel: a list of `DroppedSpan` named tuples — each with `surface`, `start`, `end`, `pack_id`, and `reason` — for spans the detector considered but did not emit as entities.

```python
import resolvekit as rk

result = rk.parse("The summit in Nairobi gathered leaders from Kenya, Uganda and the United States.")
result.dropped_spans
# [DroppedSpan(surface='and', start=58, end=61, pack_id='geo', reason='code_case_mismatch'),
#  DroppedSpan(surface='in', start=11, end=13, pack_id='org', reason='deny_list')]

[(d.surface, d.reason) for d in result.dropped_spans]   # the fields you usually want
# [('and', 'code_case_mismatch'), ('in', 'deny_list')]
```

The `reason` is one of `short_input`, `sentinel`, `word_boundary`, `below_threshold` (matched but confidence under the abstain floor), `deny_list` (common words suppressed by default), or `code_case_mismatch` (code-channel candidate rejected for wrong case).

## NIL spans with `include_nil`

By default, spans detected but below the confidence threshold go to `dropped_spans`, not to the entity list. Set `include_nil=True` to receive them as entities instead. NIL entities have `status == ResolutionStatus.NO_MATCH`, `entity_id` of `None`, and a near-miss `confidence` float.

To see what a NIL entity looks like, raise `confidence_threshold` above any span's calibrated score:

```python
import resolvekit as rk

result = rk.parse("Travel from France to Brazil", include_nil=True, confidence_threshold=0.999)
for e in result:
    print(e.surface, e.status, e.entity_id)
# France no_match None
# Brazil no_match None
```

In production, `include_nil=True` surfaces spans that matched a known entity but fell below the default abstain floor — useful for auditing low-confidence detections that would otherwise be silently routed to `dropped_spans` with `reason="below_threshold"`.

## Bulk over a column with `parse_bulk()`

`parse_bulk()` accepts a list (or pandas/polars Series with `[pandas]`/`[polars]` installed) and returns a single `ParseResult` with a `row_idx` column tagging each span's source row.

```python
import resolvekit as rk

df = rk.parse_bulk(values=["Visited Kenya and Peru", "Meeting in Japan"]).to_dataframe()
list(df.columns)
# ['row_idx', 'surface', 'entity_id', 'entity_type', 'pack_id', 'status', 'confidence', 'start', 'end', 'to']
```

`row_idx` is the zero-based index into `values`, so you can join the entity DataFrame back onto the original table.

## Next

- [**`parse()` / `parse_bulk()` reference**](../reference/api.md) — full parameter list for `parse`, `parse_bulk`, `ParseResult`, and `ParsedEntity`.
- [**Extract entities with your own NER front-end**](extract-entities-with-your-own-ner.md) — when a trained NER model (spaCy, GLiNER) handles detection and resolvekit handles linking.
