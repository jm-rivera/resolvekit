# How to reconcile a column with a human-in-the-loop review

Resolve the values a column can match automatically, hand the ambiguous and unmatched ones to a human as a CSV, then fold their decisions back in and re-run. The artifact you get at the end is a [`Crosswalk`](../reference/api.md#crosswalk) — a `value → entity_id` table you can save and replay against future data.

## Before you start

- Bundled geo data ships in the wheel — no download needed for country-level resolution.
- pandas is optional. The round-trip works on a plain `list`; swap in a `pd.Series`/`pl.Series` and the output keeps that shape.
- This guide assumes you've seen [`bulk`](clean-a-dataframe-column.md). Reconciliation is `bulk` plus a review step for the rows `bulk` can't decide alone.

## The result

You start with a column where some values are clean (`France`), some are ambiguous (`Congo` matches two countries), and some match nothing (`Atlantis`). After one review pass:

| # | country  | iso3 |
|---|----------|------|
| 0 | France   | FRA  |
| 1 | Congo    | COG  |
| 2 | Congo    | COG  |
| 3 | Atlantis | None |
| 4 | France   | FRA  |

`Congo` resolved to the Republic of the Congo (`COG`) because *you* picked it; `Atlantis` is `None` because you marked it ignored. Neither decision was guessed.

## Steps

### 1. First pass — resolve what's clean, see what's left

Call `bulk` with `to=None` to get a [`BulkResult`](../reference/api.md#bulkresult) instead of a finished column. Its `summary()` tells you how much needs attention:

```python
import resolvekit as rk

country = ["France", "Congo", "Congo", "Atlantis", "France"]

result = rk.bulk(values=country, to=None)
result.summary()
# ResolutionSummary(total=5, resolved=2, ambiguous=2, no_match=1, error=0)
```

Two rows resolved (the `France`s), two are ambiguous (`Congo`), one matched nothing (`Atlantis`).

### 2. Export the hard cases for review

`to_review` writes a CSV containing only the ambiguous and no-match values — **deduplicated**, so `Congo` appears once even though the column has it twice. Each row carries the top candidates so the reviewer has something to choose from:

```python
result.to_review("review.csv")
```

```csv
value,status,cand_1_id,cand_1_name,cand_1_conf,cand_2_id,cand_2_name,cand_2_conf,cand_3_id,cand_3_name,cand_3_conf,chosen,note
Congo,ambiguous,country/COD,Congo [DRC],0.908,country/COG,Congo [Republic],0.908,,,,,
Atlantis,no_match,,,,,,,,,,,
```

The resolved values (`France`) aren't in the file — they need no decision. If every value resolves, you get a header-only file and no error.

### 3. Fill in the `chosen` column

A human edits `review.csv` in a spreadsheet or text editor, putting an **entity ID** in the `chosen` column for each value — or the literal token `IGNORE` to map it to nothing:

```csv
value,status,...,chosen,note
Congo,ambiguous,...,country/COG,picked Republic of the Congo
Atlantis,no_match,...,IGNORE,not a real place
```

The `chosen` value is an entity ID (`country/COG`), not a code like `COG`. Storing decisions as entity IDs means the same review re-pivots to any output later — `iso3` today, `dcid` tomorrow. The `note` column is for the reviewer; it's ignored on read.

### 4. Build the crosswalk and re-run

`to_crosswalk` merges the auto-resolved rows from step 1 with the human decisions from the filled file into one complete table, then you pass it back to `bulk` via `crosswalk=`:

```python
crosswalk = result.to_crosswalk(review="review.csv")
len(crosswalk)        # 3  — France (auto) + Congo + Atlantis (manual)

iso3 = rk.bulk(values=country, to="iso3", crosswalk=crosswalk)
# ['FRA', 'COG', 'COG', None, 'FRA']
```

A value in the crosswalk skips resolution entirely — `Congo` returns `COG` without re-deciding, `Atlantis` returns `None` because it's marked `IGNORE`. Values *not* in the crosswalk (none here) fall through to normal resolution.

### 5. Save the crosswalk to reuse it

The crosswalk is the durable artifact. Write it once, load it next month against a fresh extract, and skip the review entirely for values you've already decided:

```python
crosswalk.to_csv("country_crosswalk.csv")

# ... next run, possibly a fresh process ...
crosswalk = rk.Crosswalk.from_csv("country_crosswalk.csv")
rk.bulk(values=new_country_column, to="iso3", crosswalk=crosswalk)
```

The saved file is the same `value → entity_id` shape, with `IGNORE` written out as a literal token:

```csv
value,entity_id
France,country/FRA
Congo,country/COG
Atlantis,IGNORE
```

## Skip the file for known corrections

If you already know the corrections, build the crosswalk directly with `from_dict` — no review round-trip. Use `rk.IGNORE` to drop a value:

```python
crosswalk = rk.Crosswalk.from_dict({
    "Congo": "country/COG",
    "Atlantis": rk.IGNORE,
})
rk.bulk(values=country, to="iso3", crosswalk=crosswalk)
# ['FRA', 'COG', 'COG', None, 'FRA']
```

This is the same object `to_crosswalk` returns, so a hand-written correction map and a reviewed one are interchangeable.

## Reconcile a dict, keep the keys

`bulk` accepts a `dict` and returns one with the same keys — the values are reconciled (and deduplicated) and projected back:

```python
rk.bulk(values={"hq": "France", "branch": "France", "other": "Germany"}, to="iso3")
# {'hq': 'FRA', 'branch': 'FRA', 'other': 'DEU'}
```

`crosswalk=` works here too.

## Verify it worked

Re-run the finished column through `bulk` with `to=None` and check the summary — once every value is either resolved or covered by the crosswalk, nothing should remain ambiguous:

```python
check = rk.bulk(values=country, to=None, crosswalk=crosswalk)
check.summary().ambiguous   # 0
```

## Troubleshooting

**`CrosswalkError: crosswalk references N unknown entity-id(s)`** — A `chosen` (or `from_dict`) entity ID doesn't exist in the loaded data, usually after a data rebuild changed IDs. Fix the IDs, or build the crosswalk with `strict=False` to downgrade unknown IDs to per-value misses (they follow `not_found`) instead of raising:

```python
crosswalk = rk.Crosswalk.from_csv("country_crosswalk.csv", strict=False)
```

**`ValueError: crosswalk entry '...' is not a well-formed entity-id`** — A `chosen` value isn't a `pack/code` entity ID. `Congo` resolves to `country/COG`, not `COG` — put the full entity ID in `chosen`. Run the value through [`rk.resolve_id`](../reference/api.md#resolve-id) if you're unsure of the ID.

## See also

- [Clean a DataFrame column](clean-a-dataframe-column.md) — the automatic path, when no review is needed.
- [Handle ambiguous matches](handle-ambiguous-matches.md) — inspect candidates and tiebreak policies before deciding what to put in `chosen`.
- [`Crosswalk` reference](../reference/api.md#crosswalk) — the full constructor, methods, and CSV formats.
