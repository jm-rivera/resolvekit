"""Curated ambiguous queries — each row has 2+ plausible expected IDs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from benchmarks.build.sources._geo_common import BENCHMARK_TYPE_BY_STORE
from benchmarks.core.kernel import Query

if TYPE_CHECKING:
    from resolvekit.core.store import EntityStore

logger = logging.getLogger(__name__)


_COUNTRY_CANDIDATES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("Congo", ("country/COG", "country/COD"), "Republic of Congo vs DR Congo"),
    ("the Congo", ("country/COG", "country/COD"), "Republic of Congo vs DR Congo"),
    ("Korea", ("country/PRK", "country/KOR"), "North vs South"),
    ("korea", ("country/PRK", "country/KOR"), "case variant"),
    ("Sudan", ("country/SDN", "country/SSD"), "Sudan vs South Sudan after 2011 split"),
    ("China", ("country/CHN", "country/TWN"), "PRC vs ROC both claim 'China'"),
    (
        "Guinea",
        ("country/GIN", "country/GNB", "country/GNQ"),
        "Guinea, Guinea-Bissau, Equatorial Guinea",
    ),
    ("Dominica", ("country/DMA", "country/DOM"), "Dominica vs Dominican Republic"),
    ("Samoa", ("country/WSM", "country/ASM"), "Samoa vs American Samoa"),
    ("Virgin Islands", ("country/VGB", "country/VIR"), "British vs US Virgin Islands"),
    ("Saint Martin", ("country/MAF", "country/SXM"), "French half vs Dutch half"),
    ("St Martin", ("country/MAF", "country/SXM"), "French half vs Dutch half"),
    ("St. Martin", ("country/MAF", "country/SXM"), "French half vs Dutch half"),
    ("Republic of China", ("country/TWN", "country/CHN"), "ROC (Taiwan) vs PRC"),
)


_MIXED_CANDIDATES: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    (
        "Georgia",
        ("country/GEO", "geoId/13"),
        "admin1",
        "Country Georgia vs US state Georgia",
    ),
    (
        "Jersey",
        ("country/JEY", "geoId/1342184"),
        "country",
        "Jersey crown dependency vs US namesake city",
    ),
    (
        "Niger",
        ("country/NER", "wikidataId/Q503932"),
        "country",
        "Country Niger vs Niger State (Nigeria)",
    ),
    (
        "Andorra",
        ("country/AND", "wikidataId/Q24003627"),
        "country",
        "Andorra country vs Andorra parish-town namesakes",
    ),
    (
        "Monaco",
        ("country/MCO", "wikidataId/Q55115"),
        "country",
        "Country Monaco vs Monaco-Ville (admin)",
    ),
    (
        "San Marino",
        ("country/SMR", "wikidataId/Q1848"),
        "country",
        "Country San Marino vs City of San Marino",
    ),
    (
        "Singapore",
        ("country/SGP", "wikidataId/Q7522845"),
        "country",
        "City-state country vs US town namesake",
    ),
    (
        "Luxembourg",
        ("country/LUX", "wikidataId/Q1842", "nuts/BE34"),
        "country",
        "Country, capital admin1 and Belgian Luxembourg province",
    ),
    (
        "Granada",
        ("country/GRD", "wikidataId/Q258405", "nuts/ES614"),
        "country",
        "Grenada island vs Granada dept (Nicaragua) vs Granada province (Spain)",
    ),
    (
        "Mexico",
        ("country/MEX", "wikidataId/Q1489", "wikidataId/Q82112"),
        "country",
        "Country Mexico vs Mexico City vs State of Mexico",
    ),
    (
        "Panama",
        ("country/PAN", "wikidataId/Q3306", "wikidataId/Q557506"),
        "country",
        "Country Panama vs Panama City vs Panamá Province",
    ),
    (
        "Lebanon",
        ("country/LBN", "geoId/0942390", "geoId/1742496"),
        "country",
        "Country Lebanon vs multiple US Lebanon townships",
    ),
    (
        "New York",
        ("geoId/36", "geoId/3651000"),
        "admin1",
        "New York state vs New York City",
    ),
    (
        "New Mexico",
        ("geoId/35",),
        "admin1",
        "Stretch: only the US state resolves (no MEX admin namesake)",
    ),
    (
        "Washington",
        ("geoId/53", "geoId/11001", "geoId/5372965"),
        "admin1",
        "Washington state vs DC vs other Washingtons",
    ),
    (
        "Paris",
        ("nuts/FR101", "geoId/4717100", "geoId/4835260", "geoId/2159196"),
        "admin2",
        "Paris FR vs Paris KY vs Paris TX vs Paris TN",
    ),
    (
        "London",
        ("wikidataId/Q92561", "wikidataId/Q23311", "geoId/6466212"),
        "admin3",
        "Greater London vs City of London vs London ON",
    ),
    (
        "Moscow",
        ("wikidataId/Q649", "geoId/1654550", "geoId/2453700"),
        "admin1",
        "Moscow RU admin1 vs Moscow ID vs Moscow PA",
    ),
    (
        "Cambridge",
        ("wikidataId/Q21713103", "geoId/2511000", "geoId/3911332"),
        "admin2",
        "Cambridge UK admin vs Cambridge MA vs Cambridge OH",
    ),
    (
        "Birmingham",
        ("wikidataId/Q20986424", "geoId/0107000", "nuts/UKG31"),
        "admin2",
        "Birmingham UK vs Birmingham AL vs UK NUTS",
    ),
    (
        "Manchester",
        ("wikidataId/Q21525592", "geoId/3345140", "wikidataId/Q920496"),
        "admin2",
        "Manchester UK vs Manchester NH vs Manchester Parish (Jamaica)",
    ),
    (
        "Dublin",
        ("wikidataId/Q1761", "geoId/1324376", "geoId/0620018"),
        "admin1",
        "Dublin IE vs Dublin GA vs Dublin CA",
    ),
    (
        "Athens",
        ("wikidataId/Q570807", "geoId/1303440", "geoId/3903436"),
        "admin2",
        "Athens GR admin vs Athens GA vs Athens OH",
    ),
    (
        "Rome",
        ("wikidataId/Q220", "wikidataId/Q3940419", "geoId/3663418"),
        "admin3",
        "Rome IT vs Roma Capitale vs Rome NY",
    ),
    (
        "Cairo",
        ("wikidataId/Q18498217", "geoId/1710383", "geoId/1312400"),
        "admin4",
        "Cairo EG admin vs Cairo IL vs Cairo GA",
    ),
    (
        "Lima",
        ("wikidataId/Q579240", "geoId/3943640", "wikidataId/Q211795"),
        "admin1",
        "Lima Province (Peru) vs Lima OH vs Lima Department",
    ),
    (
        "San Jose",
        ("wikidataId/Q3070", "geoId/0668000"),
        "city",
        "San José (Costa Rica capital) vs San Jose CA",
    ),
    (
        "Springfield",
        ("wikidataId/Q1661391", "geoId/2970000", "geoId/1772000"),
        "admin3",
        "Springfield MO admin vs Springfield MA vs Springfield IL",
    ),
    (
        "Portland",
        ("geoId/4159000", "geoId/2360545", "wikidataId/Q125148"),
        "city",
        "Portland OR vs Portland ME vs Portland Parish (Jamaica)",
    ),
    (
        "Columbus",
        ("geoId/3918000", "geoId/1319000", "geoId/1814734"),
        "city",
        "Columbus OH vs Columbus GA vs Columbus IN",
    ),
    (
        "Richmond",
        ("geoId/5167000", "wikidataId/Q1683013", "geoId/0660620"),
        "admin2",
        "Richmond VA vs Richmondshire UK vs Richmond CA",
    ),
    (
        "Charleston",
        ("geoId/4513330", "geoId/5414600", "geoId/1712567"),
        "city",
        "Charleston SC vs Charleston WV vs Charleston IL",
    ),
    (
        "Kansas City",
        ("geoId/2938000", "geoId/2036000"),
        "city",
        "Kansas City MO vs Kansas City KS",
    ),
    (
        "Valencia",
        ("nuts/ES52", "wikidataId/Q1983488", "wikidataId/Q8818"),
        "admin1",
        "Comunidad Valenciana (ES) vs Valencia (Venezuela) vs Valencia (Spain)",
    ),
    (
        "Toledo",
        ("wikidataId/Q1776774", "geoId/3977000", "wikidataId/Q506049"),
        "admin2",
        "Toledo ES admin vs Toledo OH vs Toledo District (Belize)",
    ),
    (
        "Vienna",
        ("nuts/AT13", "geoId/5182000", "geoId/1379444"),
        "admin1",
        "Vienna AT vs Vienna VA vs Vienna GA",
    ),
    (
        "Cuba",
        ("country/CUB", "wikidataId/Q552580"),
        "country",
        "Country Cuba vs Cuba municipality (Portugal)",
    ),
    (
        "Malta",
        ("country/MLT", "wikidataId/Q2329682"),
        "country",
        "Country Malta vs Malta NY town",
    ),
    (
        "Turkey",
        ("country/TUR", "geoId/3768740"),
        "country",
        "Country Turkey vs Turkey NC town",
    ),
    (
        "Boston",
        ("wikidataId/Q894076", "geoId/2507000"),
        "admin2",
        "Boston UK borough vs Boston MA",
    ),
    (
        "Hamilton",
        ("wikidataId/Q30985", "wikidataId/Q289876", "geoId/3429310"),
        "admin2",
        "Hamilton ON vs Hamilton Parish (Bermuda) vs Hamilton Township NJ",
    ),
    (
        "Wellington",
        ("wikidataId/Q856010", "wikidataId/Q47037646", "wikidataId/Q646195"),
        "admin1",
        "Wellington Region NZ vs Wellington City vs Shire of Wellington AU",
    ),
    (
        "Barcelona",
        ("wikidataId/Q1492", "wikidataId/Q391221"),
        "admin3",
        "Barcelona (Spain) vs Barcelona (Venezuela)",
    ),
    (
        "Alexandria",
        ("wikidataId/Q2099372", "geoId/5101000"),
        "admin2",
        "Alexandria (Egypt) governorate vs Alexandria VA",
    ),
    (
        "Tripoli",
        ("wikidataId/Q32837", "wikidataId/Q3539555"),
        "admin1",
        "Tripoli District (Libya) vs Tripoli Municipality (Lebanon)",
    ),
    (
        "Albany",
        ("geoId/3601000", "geoId/0600674", "geoId/1301052"),
        "city",
        "Albany NY vs Albany CA vs Albany GA",
    ),
    (
        "Buffalo",
        ("geoId/3611000", "geoId/4011000", "geoId/5611260"),
        "city",
        "Buffalo NY vs Buffalo OK vs Buffalo WY",
    ),
    (
        "Plymouth",
        ("wikidataId/Q21674890", "geoId/2554275", "geoId/1860914"),
        "admin2",
        "City of Plymouth UK vs Plymouth MA vs Plymouth IN",
    ),
)


def build(
    *,
    store: EntityStore,
    limit: int | None = None,
    seed: int = 42,
) -> list[Query]:
    del seed
    rows: list[Query] = []
    skipped: list[str] = []

    for query, candidate_ids, note in _COUNTRY_CANDIDATES:
        validated = _validate(store=store, ids=candidate_ids)
        if len(validated) < 2:
            skipped.append(f"{query} -> {candidate_ids}")
            continue
        rows.append(
            Query(
                query_id="",
                text=query,
                expected_ids=validated,
                language="en",
                entity_type="country",
                category="ambiguous",
                difficulty="hard",
                capabilities=("ambiguity_signaling",),
                source="curated",
                notes=note,
            )
        )
        if limit is not None and len(rows) >= limit:
            break

    for query, candidate_ids, entity_type, note in _MIXED_CANDIDATES:
        if limit is not None and len(rows) >= limit:
            break
        validated = _validate(store=store, ids=candidate_ids)
        if len(validated) < 2:
            skipped.append(f"{query} -> {candidate_ids}")
            continue
        capabilities: tuple[str, ...] = ("ambiguity_signaling",)
        if _has_admin(store=store, entity_ids=validated):
            capabilities = ("ambiguity_signaling", "admin_hierarchy")
        effective_type = _primary_benchmark_type(
            store=store, entity_id=validated[0], fallback=entity_type
        )
        rows.append(
            Query(
                query_id="",
                text=query,
                expected_ids=validated,
                language="en",
                entity_type=effective_type,
                category="ambiguous",
                difficulty="hard",
                capabilities=capabilities,
                source="curated",
                notes=note,
            )
        )

    if skipped:
        logger.info(
            "ambiguous: skipped %d rows whose candidates weren't all resolvable: %s",
            len(skipped),
            skipped,
        )
    return rows


_ADMIN_TYPES: frozenset[str] = frozenset(
    {"geo.admin1", "geo.admin2", "geo.admin3", "geo.admin4", "geo.admin5"}
)


def _validate(*, store: EntityStore, ids: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(eid for eid in ids if store.get_entity(eid) is not None)


def _has_admin(*, store: EntityStore, entity_ids: tuple[str, ...]) -> bool:
    for eid in entity_ids:
        entity = store.get_entity(eid)
        if entity is not None and entity.entity_type in _ADMIN_TYPES:
            return True
    return False


def _primary_benchmark_type(
    *, store: EntityStore, entity_id: str, fallback: str
) -> str:
    entity = store.get_entity(entity_id)
    if entity is None:
        return fallback
    return BENCHMARK_TYPE_BY_STORE.get(entity.entity_type, fallback)
