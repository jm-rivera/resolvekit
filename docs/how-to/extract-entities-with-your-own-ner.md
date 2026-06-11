# How to extract entities using your own NER front-end

Run a NER model to detect spans in free text, then call `resolver.resolve()` per span to link each one to a canonical entity with codes and confidence scores.

## When to use this vs native `parse()`

resolvekit ships [`parse()` / `parse_bulk()`](extract-entities-from-text.md) for offline, zero-extra-dependency, calibrated entity extraction. It is deterministic, requires no additional downloads beyond the data packs, and produces offset-aligned output with `to=` pivot integration wired in.

This recipe is better when:

- you already run a NER stack (spaCy, GLiNER, Stanza) and don't want a second detection path, or
- your text is caseless, messy, or uses metonymy — "Brussels announced", "the Bank" — where a dictionary-first detector silently misses spans that a trained NER model catches.

The split is clean: NER handles **detection** (finding where entities are); resolvekit handles **linking** (mapping each span to a canonical ID, code, and confidence). Neither half does the other's job.

!!! note
    [`parse()`](extract-entities-from-text.md) is the better default for most use cases: no extra dependency, offline-safe, and its outputs are calibrated. Switch to this recipe if you already have a NER pipeline or if dictionary-first detection is leaving spans on the floor.

## Before you start

- `pip install 'resolvekit[baselines]'` (spaCy is not a core resolvekit dependency)
- `python -m spacy download en_core_web_sm`
- A `Resolver` instance (see [your first resolution](../getting-started/first-resolution.md))

## What you'll get

Given the text `"The UN and FAO coordinated aid delivery to Ethiopia and Sudan"`, the recipe produces a list like:

```
span="UN"       entity_id="groups/UN"                entity_type="geo.organization"          conf=0.91
span="FAO"      entity_id="org/oecd:agency:1022:9"   entity_type="org.government_organization" conf=0.85
span="Ethiopia" entity_id="country/ETH"              entity_type="geo.country"               conf=0.91
span="Sudan"    entity_id="country/SDN"              entity_type="geo.country"               conf=0.91
```

## The recipe

```python
import spacy
import resolvekit as rk
from resolvekit import ResolutionContext

# Load spaCy NER-only — exclude everything except the NER component.
# This keeps RSS and latency close to a pure-NER baseline.
nlp = spacy.load(
    "en_core_web_sm",
    exclude=["tok2vec", "tagger", "parser", "senter", "attribute_ruler", "lemmatizer"],
)

resolver = rk.Resolver.auto()

text = "The UN and FAO coordinated aid delivery to Ethiopia and Sudan"
doc = nlp(text)

results = []
for ent in doc.ents:
    # Filter to geographic and organizational labels only.
    # GPE = geopolitical entity, LOC = location, ORG = organization.
    # Skipping PERSON, DATE, CARDINAL, etc. avoids spurious links.
    if ent.label_ not in {"GPE", "LOC", "ORG"}:
        continue

    # as_result=True returns a ResolutionResult regardless of any default_to
    # view configured on the resolver. Without it, a resolver built with
    # default_to="iso3" would return a string (or None) instead of a result
    # object, and you'd lose entity_id and confidence.
    res = resolver.resolve(ent.text, as_result=True)
    if res is None or res.entity_id is None:
        continue  # NIL span — not in the loaded packs

    # entity_type lives on the resolved candidate, not on the result itself.
    top = res.best_candidate
    results.append({
        "span":        ent.text,
        "start":       ent.start_char,
        "end":         ent.end_char,
        "entity_id":   res.entity_id,
        "entity_type": top.entity_type if top is not None else None,
        "confidence":  res.confidence,
    })
```

`ent.start_char` and `ent.end_char` are byte-safe character offsets into the original string — use them directly to highlight spans or align with upstream tokenization.

## Narrowing with entity type hints

Short or ambiguous spans — "Georgia", "IS", "Congo" — can link to the wrong entity type when the resolver fans across all loaded packs. Pass `ResolutionContext(entity_types=...)` to hint the expected type:

```python
# ✅ Constrain to geographic entities when the NER label is GPE or LOC
geo_context = ResolutionContext(entity_types=frozenset({"geo.country", "geo.state", "geo.region"}))

for ent in doc.ents:
    if ent.label_ in {"GPE", "LOC"}:
        res = resolver.resolve(ent.text, as_result=True, context=geo_context)
    elif ent.label_ == "ORG":
        res = resolver.resolve(ent.text, as_result=True)
    else:
        continue

    if res and res.entity_id:
        ...
```

`entity_types` is a `frozenset[str]`. Passing a plain string raises `ValueError` — the validator catches it to prevent silent character-set iteration.

!!! info "Why"
    resolvekit's short-input gate suppresses disambiguation on spans shorter than a few characters unless an `entity_types` hint is supplied. The NER label already tells you the domain, so passing it through unlocks the gate without widening the candidate set.

## Reference implementation

A reference implementation, `SpacyNerAdapter`, lives at [`benchmarks/parse/baselines/spacy_ner.py`](https://github.com/jm-rivera/resolvekit/blob/main/benchmarks/parse/baselines/spacy_ner.py) in the source repository (it is not part of the installed package). It implements this same pattern with lazy spaCy import, error handling for a missing model, and `PredSpan` output — a complete, tested version of this recipe to read alongside.

## Troubleshooting

**`ImportError: The spaCy parse baseline requires spacy`**
Install with `pip install 'resolvekit[baselines]'`, not `pip install resolvekit`.

**`OSError: spaCy model 'en_core_web_sm' is not downloaded`**
Run `python -m spacy download en_core_web_sm` after installing spaCy.

**All spans return `entity_id=None`**
The loaded resolver only links entities in its packs. An `ORG` span for a company not in the org pack will always be NIL. Check `resolver.info.domains` to see what's loaded.

**`ValueError: entity_types must be a collection of strings, not a single string`**
Pass a `frozenset` or `set`, not a bare string: `entity_types=frozenset({"geo.country"})`.

## Next

- [**`resolve()` reference**](../reference/api.md) — full parameter list including `context=`, `domain=`, and `as_result=`.
- [**Handle ambiguous matches**](handle-ambiguous-matches.md) — inspect candidates and set a tiebreak policy when a span could link to more than one entity.
- [**How resolution works**](../explanation/how-resolution-works.md) — the scoring and calibration pipeline that runs behind each `resolve()` call.
