"""Inject formal country names (e.g. "Republic of X", "Kingdom of X") as aliases.

Most country resolution datasets contain only the short canonical name
("Albania", "Belgium") plus a few language translations. The benchmark's
"alias" capability is dominated by formal designations like "Republic of
Albania" or "Kingdom of Belgium", so packaged country sqlite files miss
almost all of those.

This module pulls formal designations from two sources:

1. ``pycountry.country.official_name`` (covers ~173 of 249 countries with
   the modern formal designation, e.g. "Hashemite Kingdom of Jordan").
2. A small overrides table in ``data/formal_names.yaml`` for the few
   countries pycountry leaves blank but that have a well-known formal
   English designation (Australia, Russia, USA, UK, China alternatives,
   etc.).

For every formal name we add, we also emit a "the X" prefixed variant
("the Republic of Albania") because hdx-style sources phrase it that way.

All injected names use ``name_kind='alias'`` and ``is_preferred=0`` so the
existing canonical short name (and its preferred flag) is untouched.

This data layer is invoked from the ``enrich`` pipeline stage
(``builder.pipeline.enrich``) so it sits in the canonical staging DB and
flows through validate / package / QA like any other ingested name. It can
also be invoked directly for ad-hoc augmentation of an already-packaged
sqlite file.
"""

from __future__ import annotations

import sqlite3
from functools import cache
from pathlib import Path

from resolvekit.builder.pipeline.contribution import GraphContribution
from resolvekit.builder.sqlite.context import connect_sqlite
from resolvekit.core.util.normalization import TextNormalizer

try:
    import pycountry as _pycountry
except ImportError:  # pragma: no cover - optional dep
    _pycountry = None  # type: ignore[assignment]

try:
    import yaml as _yaml
except ImportError:  # pragma: no cover - optional dep
    _yaml = None  # type: ignore[assignment]

DEFAULT_FORMAL_LANG = "en"
COUNTRY_ENTITY_TYPE = "geo.country"
_FORMAL_NAMES_YAML_PATH = Path(__file__).parent / "data" / "formal_names.yaml"


@cache
def _load_formal_overrides() -> dict[str, list[str]]:
    """Load formal-name overrides from YAML, cached for the process."""
    if _yaml is None:
        raise ImportError(
            "formal_names enricher requires pyyaml. "
            "Install with: pip install 'resolvekit[data]'"
        )
    with _FORMAL_NAMES_YAML_PATH.open("r", encoding="utf-8") as fh:
        data = _yaml.safe_load(fh) or {}
    overrides = data.get("overrides") or {}
    return {
        str(iso3): [str(name) for name in names] for iso3, names in overrides.items()
    }


@cache
def _load_multilingual_overrides() -> dict[str, dict[str, list[str]]]:
    """Load multilingual formal-name overrides from YAML, cached for the process.

    Returns a mapping of iso3 → lang → list[str].
    """
    if _yaml is None:
        raise ImportError(
            "formal_names enricher requires pyyaml. "
            "Install with: pip install 'resolvekit[data]'"
        )
    with _FORMAL_NAMES_YAML_PATH.open("r", encoding="utf-8") as fh:
        data = _yaml.safe_load(fh) or {}
    raw = data.get("multilingual_overrides") or {}
    return {
        str(iso3): {
            str(lang): [str(name) for name in names] for lang, names in lang_map.items()
        }
        for iso3, lang_map in raw.items()
    }


# Names we should never emit as a formal alias even if a source provides
# them, because they would collide with another country's canonical short
# name and create false positives.
_BLOCKLIST_NORMALIZED: frozenset[str] = frozenset()


def _format_with_the_prefix(name: str) -> str:
    """Return the formal name with leading ``the`` (matching OCHA style)."""
    return f"the {name}"


def _iso3_from_entity_id(entity_id: str) -> str | None:
    """Return the ISO 3166-1 alpha-3 code embedded in a ``country/XXX`` ID."""
    prefix = "country/"
    if not entity_id.startswith(prefix):
        return None
    suffix = entity_id[len(prefix) :]
    if len(suffix) == 3 and suffix.isalpha() and suffix.isupper():
        return suffix
    return None


def _formal_names_for_iso3(iso3: str) -> list[str]:
    """Return all formal English designations known for an ISO3 country."""
    if _pycountry is None:
        raise ImportError(
            "pycountry is required to ingest formal country names. "
            "Install with: pip install 'resolvekit[data]'"
        )
    out: list[str] = []
    seen: set[str] = set()

    def push(name: str | None) -> None:
        if not name:
            return
        cleaned = name.strip()
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        out.append(cleaned)

    country = _pycountry.countries.get(alpha_3=iso3)
    if country is not None:
        push(getattr(country, "official_name", None))

    overrides = _load_formal_overrides()
    for override in overrides.get(iso3, ()):
        push(override)

    return out


def build_formal_name_contribution(
    db_path: Path,
    *,
    lang: str = DEFAULT_FORMAL_LANG,
    add_the_prefix: bool = True,
) -> GraphContribution:
    """Compute formal-name alias rows for every country/XXX entity (pure read).

    Returns a ``GraphContribution`` with the alias name rows to insert. The caller
    (pipeline) writes them via ``apply_contribution``. Idempotent on re-run because
    INSERT OR IGNORE collides on the ``names`` primary key.
    """
    normalizer = TextNormalizer()
    name_dicts: list[dict] = []

    with connect_sqlite(db_path, row_factory=sqlite3.Row) as conn:
        countries = conn.execute(
            "SELECT entity_id FROM entities WHERE entity_type = ?",
            (COUNTRY_ENTITY_TYPE,),
        ).fetchall()

    for row in countries:
        entity_id = str(row["entity_id"])
        iso3 = _iso3_from_entity_id(entity_id)
        if iso3 is None:
            continue

        names = _formal_names_for_iso3(iso3)
        if not names:
            continue

        for name in names:
            for variant in _expand_variants(name, add_the_prefix=add_the_prefix):
                normalized = normalizer.normalize(variant)
                if normalized in _BLOCKLIST_NORMALIZED:
                    continue
                name_dicts.append(
                    {
                        "entity_id": entity_id,
                        "name_kind": "alias",
                        "value": variant,
                        "value_norm": normalized,
                        "lang": lang,
                        "script": "",
                        "is_preferred": 0,
                    }
                )

        # Multilingual path: emit alias rows for non-English formal names.
        # add_the_prefix=False because French/Spanish prefixes (la, le, etc.)
        # are handled explicitly in the YAML rather than via the English "the" rule.
        multilingual = _load_multilingual_overrides()
        for ml_lang, ml_names in multilingual.get(iso3, {}).items():
            for name in ml_names:
                for variant in _expand_variants(name, add_the_prefix=False):
                    normalized = normalizer.normalize(variant)
                    if normalized in _BLOCKLIST_NORMALIZED:
                        continue
                    name_dicts.append(
                        {
                            "entity_id": entity_id,
                            "name_kind": "alias",
                            "value": variant,
                            "value_norm": normalized,
                            "lang": ml_lang,
                            "script": "",
                            "is_preferred": 0,
                        }
                    )

    return GraphContribution(names=name_dicts)


def _expand_variants(name: str, *, add_the_prefix: bool) -> list[str]:
    """Yield variants of a formal name, currently the bare form and ``the X``."""
    variants = [name]
    if add_the_prefix:
        first_word = name.split(" ", 1)[0].lower()
        if first_word != "the":
            variants.append(_format_with_the_prefix(name))
    return variants
