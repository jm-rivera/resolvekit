"""Hardcoded seed data for the seven continents and Americas (Q828).

Continents are a closed, well-known set whose Wikidata Q-IDs are stable
constants. A network fetch is unnecessary and would add build complexity
for zero gain. This module provides the canonical seed rows used by
``scripts/build/build_continents.py`` to produce the bundled
``geo.continents`` datapack.

This module also re-exports ``CONTINENT_REUSE_EDGES`` from
``builder.sources.seed.m49`` so that ``build_continents.py`` can write
the two continent-sourced ``contained_in`` reuse edges into the continents
pack.  Those edges are owned by ``geo.continents`` because their source
entities live there.

Entity IDs use the ``wikidataId/Q<n>`` form consistent with how Data
Commons surfaces Wikidata-sourced entities (e.g. ``wikidataId/Q756617``
for the Kingdom of Denmark in the countries pack).  The eval compares
against these IDs directly.

Each seed entry carries:
- ``entity_id``:     ``"wikidataId/Q<n>"`` form
- ``canonical_name``: English name
- ``entity_type``:   ``"geo.continent"``
- ``wikidata_qid``:  bare Q-ID string for the ``codes.wikidata`` row
- ``names``:         tuple of (value, lang, name_kind) for retrieval
"""

from __future__ import annotations

from dataclasses import dataclass, field

from resolvekit.builder.sources.seed.m49 import CONTINENT_REUSE_EDGES

__all__ = ["CONTINENTS", "CONTINENT_REUSE_EDGES", "ENTITY_TYPE"]

ENTITY_TYPE = "geo.continent"


@dataclass(frozen=True, slots=True)
class ContinentSeedEntry:
    """One continent's seed data."""

    entity_id: str
    canonical_name: str
    wikidata_qid: str
    names: tuple[tuple[str, str, str], ...] = field(default_factory=tuple)


# Nine entities: the seven geographic continents + Americas (pan-American
# supercontinent, Q828) + World (m49/001).
# The World entry uses an m49 entity_id rather than wikidataId/ because it serves as
# the canonical aggregate target. An m49 code-system row is intentionally not added;
# to="m49" pivot on World is a known scope gap.
#
# name tuples: (value, lang, name_kind)
# name_kind values: "canonical" (primary per language), "alias" (alternate)
CONTINENTS: tuple[ContinentSeedEntry, ...] = (
    ContinentSeedEntry(
        entity_id="wikidataId/Q15",
        canonical_name="Africa",
        wikidata_qid="Q15",
        names=(
            ("Africa", "en", "canonical"),
            ("the Dark Continent", "en", "alias"),
            ("Dark Continent", "en", "alias"),
            ("Afrika", "de", "canonical"),
            ("África", "es", "canonical"),
            ("Afrique", "fr", "canonical"),
            ("Africa", "pt", "canonical"),
            ("Африка", "ru", "canonical"),
            ("非洲", "zh", "canonical"),
            ("أفريقيا", "ar", "canonical"),
        ),
    ),
    ContinentSeedEntry(
        entity_id="wikidataId/Q46",
        canonical_name="Europe",
        wikidata_qid="Q46",
        names=(
            ("Europe", "en", "canonical"),
            ("Europa", "de", "canonical"),
            ("Europa", "es", "canonical"),
            ("Europe", "fr", "canonical"),
            ("Europa", "pt", "canonical"),
            ("Европа", "ru", "canonical"),
            ("欧洲", "zh", "canonical"),
            ("أوروبا", "ar", "canonical"),
        ),
    ),
    ContinentSeedEntry(
        entity_id="wikidataId/Q48",
        canonical_name="Asia",
        wikidata_qid="Q48",
        names=(
            ("Asia", "en", "canonical"),
            ("Asien", "de", "canonical"),
            ("Asia", "es", "canonical"),
            ("Asie", "fr", "canonical"),
            ("Ásia", "pt", "canonical"),
            ("Азия", "ru", "canonical"),
            ("亚洲", "zh", "canonical"),
            ("آسيا", "ar", "canonical"),
        ),
    ),
    ContinentSeedEntry(
        entity_id="wikidataId/Q49",
        canonical_name="North America",
        wikidata_qid="Q49",
        names=(
            ("North America", "en", "canonical"),
            ("Northern America", "en", "alias"),
            ("Nordamerika", "de", "canonical"),
            ("América del Norte", "es", "canonical"),
            ("Amérique du Nord", "fr", "canonical"),
            ("América do Norte", "pt", "canonical"),
            ("Северная Америка", "ru", "canonical"),
            ("北美洲", "zh", "canonical"),
            ("أمريكا الشمالية", "ar", "canonical"),
        ),
    ),
    ContinentSeedEntry(
        entity_id="wikidataId/Q18",
        canonical_name="South America",
        wikidata_qid="Q18",
        names=(
            ("South America", "en", "canonical"),
            ("Südamerika", "de", "canonical"),
            ("América del Sur", "es", "canonical"),
            ("Sudamérica", "es", "alias"),
            ("Amérique du Sud", "fr", "canonical"),
            ("América do Sul", "pt", "canonical"),
            ("Южная Америка", "ru", "canonical"),
            ("南美洲", "zh", "canonical"),
            ("أمريكا الجنوبية", "ar", "canonical"),
        ),
    ),
    ContinentSeedEntry(
        entity_id="wikidataId/Q55643",
        canonical_name="Oceania",
        wikidata_qid="Q55643",
        names=(
            ("Oceania", "en", "canonical"),
            ("Australia and Oceania", "en", "alias"),
            ("Ozeanien", "de", "canonical"),
            ("Oceanía", "es", "canonical"),
            ("Océanie", "fr", "canonical"),
            ("Oceania", "pt", "canonical"),
            ("Океания", "ru", "canonical"),
            ("大洋洲", "zh", "canonical"),
            ("أوقيانوسيا", "ar", "canonical"),
        ),
    ),
    ContinentSeedEntry(
        entity_id="wikidataId/Q51",
        canonical_name="Antarctica",
        wikidata_qid="Q51",
        names=(
            ("Antarctica", "en", "canonical"),
            ("Antarktika", "de", "canonical"),
            ("Antártida", "es", "canonical"),
            ("Antarctique", "fr", "canonical"),
            ("Antártica", "pt", "canonical"),
            ("Антарктида", "ru", "canonical"),
            ("南极洲", "zh", "canonical"),
            ("أنتاركتيكا", "ar", "canonical"),
        ),
    ),
    ContinentSeedEntry(
        entity_id="wikidataId/Q828",
        canonical_name="Americas",
        wikidata_qid="Q828",
        names=(
            ("Americas", "en", "canonical"),
            ("New World", "en", "alias"),
            ("Amerika", "de", "canonical"),
            ("América", "es", "canonical"),
            ("Amérique", "fr", "canonical"),
            ("Américas", "pt", "canonical"),
            ("Америка", "ru", "canonical"),
            ("美洲", "zh", "canonical"),
            ("أمريكا", "ar", "canonical"),
        ),
    ),
    ContinentSeedEntry(
        entity_id="m49/001",
        canonical_name="World",
        wikidata_qid="Q16502",
        names=(("World", "en", "canonical"),),
    ),
)
