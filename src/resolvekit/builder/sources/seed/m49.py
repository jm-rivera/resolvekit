"""Hardcoded seed data for UN M.49 geographic sub-regions.

The M.49 table is a fixed international standard; this module provides the
curated seed rows used by ``builder/containment.py`` to mint ~22 absent
sub-region / intermediate region entities as ``geo.subregion`` and to emit the
``contained_in`` tree linking countries up through sub-regions to continents.

Design decisions:
- Entity IDs use the ``m49/<zero-padded-3-digit>`` form so they never collide
  with alpha ``iso2``/``iso3``, ``undata-geo/*``, or ``wikidataId/*``.
- Each minted region exposes an ``m49`` code row and an explicit canonical
  ``names`` row (``lookup_name_exact`` reads the names table).
- Two continent-sourced reuse edges (``Q18→m49/419``, ``Q49→Q828``) are held in
  ``CONTINENT_REUSE_EDGES`` for use by ``build_continents.py``.
  The enricher does NOT emit them.
- South America (Q18) and Northern America / North America (Q49) are reused
  from the shipped continents pack — they are NOT minted here.

Country assignments (``M49_COUNTRY_ASSIGNMENTS``) map every bundled iso3 to
its **leaf** M.49 node:
- South-American countries → ``wikidataId/Q18`` (reused continent).
- USA, Canada, Greenland, Bermuda, St. Pierre & Miquelon → ``wikidataId/Q49``.
- All other countries → the appropriate minted ``m49/<code>`` sub-region.

Source: https://unstats.un.org/unsd/methodology/m49
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

ENTITY_TYPE = "geo.subregion"


@dataclass(frozen=True, slots=True)
class M49Region:
    """One minted M.49 sub-region or intermediate region entity.

    ``parent_id`` is either another ``m49/<code>`` (for sub-regions under an
    intermediate region) or a continent ``wikidataId/Q<n>`` (for top-level
    sub-regions directly under a continent).

    ``aliases`` are additional English-language name variants to emit as alias
    ``names`` rows.  Keep them short; the canonical name is what resolves.
    """

    entity_id: str
    code: str  # zero-padded 3-digit M.49 numeric code
    canonical_name: str
    parent_id: str
    aliases: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# The two continent-sourced reuse edges
#
# Source entity is a continent (geo.continents pack).  They must be written by
# build_continents.py, NOT by the enricher.
# (source_entity_id, target_entity_id)
# ---------------------------------------------------------------------------

CONTINENT_REUSE_EDGES: tuple[tuple[str, str], ...] = (
    ("wikidataId/Q18", "m49/419"),  # South America → Latin America & Caribbean
    ("wikidataId/Q49", "wikidataId/Q828"),  # Northern America → Americas
)

# ---------------------------------------------------------------------------
# The ~22 minted M.49 nodes (Q18 and Q49 are NOT minted here)
#
# Tree structure (→ = contained_in, parent to the right):
#
# Africa (Q15)
#   m49/015 Northern Africa              → Q15
#   m49/202 Sub-Saharan Africa           → Q15
#     m49/014 Eastern Africa             → m49/202
#     m49/017 Middle Africa              → m49/202
#     m49/018 Southern Africa            → m49/202
#     m49/011 Western Africa             → m49/202
#
# Americas (Q828)
#   m49/419 Latin America & the Caribbean → Q828
#     m49/029 Caribbean                  → m49/419
#     m49/013 Central America            → m49/419
#     [South America (Q18)]              → m49/419   [CS edge, not minted]
#   [Northern America (Q49)]             → Q828       [CS edge, not minted]
#
# Asia (Q48)
#   m49/143 Central Asia                 → Q48
#   m49/030 Eastern Asia                 → Q48
#   m49/035 South-eastern Asia           → Q48
#   m49/034 Southern Asia               → Q48
#   m49/145 Western Asia                 → Q48
#
# Europe (Q46)
#   m49/151 Eastern Europe               → Q46
#   m49/154 Northern Europe              → Q46
#   m49/039 Southern Europe              → Q46
#   m49/155 Western Europe               → Q46
#
# Oceania (Q55643)
#   m49/053 Australia and New Zealand    → Q55643
#   m49/054 Melanesia                    → Q55643
#   m49/057 Micronesia                   → Q55643
#   m49/061 Polynesia                    → Q55643
# ---------------------------------------------------------------------------

M49_REGIONS: tuple[M49Region, ...] = (
    # ── Africa ──────────────────────────────────────────────────────────────
    M49Region(
        entity_id="m49/015",
        code="015",
        canonical_name="Northern Africa",
        parent_id="wikidataId/Q15",
        aliases=("North Africa",),
    ),
    M49Region(
        entity_id="m49/202",
        code="202",
        canonical_name="Sub-Saharan Africa",
        parent_id="wikidataId/Q15",
        aliases=("sub-Saharan Africa",),
    ),
    M49Region(
        entity_id="m49/014",
        code="014",
        canonical_name="Eastern Africa",
        parent_id="m49/202",
        aliases=("East Africa",),
    ),
    M49Region(
        entity_id="m49/017",
        code="017",
        canonical_name="Middle Africa",
        parent_id="m49/202",
        aliases=("Central Africa",),
    ),
    M49Region(
        entity_id="m49/018",
        code="018",
        canonical_name="Southern Africa",
        parent_id="m49/202",
        aliases=("South Africa region",),
    ),
    M49Region(
        entity_id="m49/011",
        code="011",
        canonical_name="Western Africa",
        parent_id="m49/202",
        aliases=("West Africa",),
    ),
    # ── Americas ─────────────────────────────────────────────────────────────
    M49Region(
        entity_id="m49/419",
        code="419",
        canonical_name="Latin America and the Caribbean",
        parent_id="wikidataId/Q828",
        aliases=("Latin America & the Caribbean", "LAC", "Latin America"),
    ),
    M49Region(
        entity_id="m49/029",
        code="029",
        canonical_name="Caribbean",
        parent_id="m49/419",
        aliases=("the Caribbean",),
    ),
    M49Region(
        entity_id="m49/013",
        code="013",
        canonical_name="Central America",
        parent_id="m49/419",
        aliases=(),
    ),
    # ── Asia ─────────────────────────────────────────────────────────────────
    M49Region(
        entity_id="m49/143",
        code="143",
        canonical_name="Central Asia",
        parent_id="wikidataId/Q48",
        aliases=(),
    ),
    M49Region(
        entity_id="m49/030",
        code="030",
        canonical_name="Eastern Asia",
        parent_id="wikidataId/Q48",
        aliases=("East Asia",),
    ),
    M49Region(
        entity_id="m49/035",
        code="035",
        canonical_name="South-eastern Asia",
        parent_id="wikidataId/Q48",
        aliases=("Southeast Asia", "South-East Asia"),
    ),
    M49Region(
        entity_id="m49/034",
        code="034",
        canonical_name="Southern Asia",
        parent_id="wikidataId/Q48",
        aliases=("South Asia",),
    ),
    M49Region(
        entity_id="m49/145",
        code="145",
        canonical_name="Western Asia",
        parent_id="wikidataId/Q48",
        aliases=("West Asia", "Middle East"),
    ),
    # ── Europe ───────────────────────────────────────────────────────────────
    M49Region(
        entity_id="m49/151",
        code="151",
        canonical_name="Eastern Europe",
        parent_id="wikidataId/Q46",
        aliases=("East Europe",),
    ),
    M49Region(
        entity_id="m49/154",
        code="154",
        canonical_name="Northern Europe",
        parent_id="wikidataId/Q46",
        aliases=("North Europe",),
    ),
    M49Region(
        entity_id="m49/039",
        code="039",
        canonical_name="Southern Europe",
        parent_id="wikidataId/Q46",
        aliases=("South Europe",),
    ),
    M49Region(
        entity_id="m49/155",
        code="155",
        canonical_name="Western Europe",
        parent_id="wikidataId/Q46",
        aliases=("West Europe",),
    ),
    # ── Oceania ──────────────────────────────────────────────────────────────
    M49Region(
        entity_id="m49/053",
        code="053",
        canonical_name="Australia and New Zealand",
        parent_id="wikidataId/Q55643",
        aliases=("Australasia",),
    ),
    M49Region(
        entity_id="m49/054",
        code="054",
        canonical_name="Melanesia",
        parent_id="wikidataId/Q55643",
        aliases=(),
    ),
    M49Region(
        entity_id="m49/057",
        code="057",
        canonical_name="Micronesia",
        parent_id="wikidataId/Q55643",
        aliases=(),
    ),
    M49Region(
        entity_id="m49/061",
        code="061",
        canonical_name="Polynesia",
        parent_id="wikidataId/Q55643",
        aliases=(),
    ),
)

# Set of all minted entity_ids + the two reused continent ids that appear as
# leaf targets in M49_COUNTRY_ASSIGNMENTS.  Used by the completeness guard.
_VALID_LEAF_IDS: frozenset[str] = frozenset(
    {r.entity_id for r in M49_REGIONS} | {"wikidataId/Q18", "wikidataId/Q49"}
)

# Set of all valid parent_ids (minted regions + direct continent parents).
_VALID_PARENT_IDS: frozenset[str] = frozenset(
    {r.entity_id for r in M49_REGIONS}
    | {
        "wikidataId/Q15",  # Africa
        "wikidataId/Q46",  # Europe
        "wikidataId/Q48",  # Asia
        "wikidataId/Q49",  # Northern America (reused)
        "wikidataId/Q55643",  # Oceania
        "wikidataId/Q828",  # Americas
    }
)

# ---------------------------------------------------------------------------
# Country → leaf M.49 node assignments
#
# Every bundled iso3 maps to its immediate M.49 sub-region leaf.
# South-American countries map to ``wikidataId/Q18`` (the reused continent).
# USA, Canada, Greenland, Bermuda, St. Pierre & Miquelon → ``wikidataId/Q49``.
# ---------------------------------------------------------------------------

M49_COUNTRY_ASSIGNMENTS: dict[str, str] = {
    # ── Northern Africa (m49/015) ────────────────────────────────────────────
    "DZA": "m49/015",  # Algeria
    "EGY": "m49/015",  # Egypt
    "LBY": "m49/015",  # Libya
    "MAR": "m49/015",  # Morocco
    "SDN": "m49/015",  # Sudan
    "TUN": "m49/015",  # Tunisia
    "ESH": "m49/015",  # Western Sahara
    # ── Eastern Africa (m49/014) ─────────────────────────────────────────────
    "BDI": "m49/014",  # Burundi
    "COM": "m49/014",  # Comoros
    "DJI": "m49/014",  # Djibouti
    "ERI": "m49/014",  # Eritrea
    "ETH": "m49/014",  # Ethiopia
    "KEN": "m49/014",  # Kenya
    "MDG": "m49/014",  # Madagascar
    "MWI": "m49/014",  # Malawi
    "MUS": "m49/014",  # Mauritius
    "MOZ": "m49/014",  # Mozambique
    "REU": "m49/014",  # Réunion
    "RWA": "m49/014",  # Rwanda
    "SYC": "m49/014",  # Seychelles
    "SOM": "m49/014",  # Somalia
    "SSD": "m49/014",  # South Sudan
    "TZA": "m49/014",  # Tanzania
    "UGA": "m49/014",  # Uganda
    "ZMB": "m49/014",  # Zambia
    "ZWE": "m49/014",  # Zimbabwe
    "MYT": "m49/014",  # Mayotte
    # ── Middle Africa (m49/017) ──────────────────────────────────────────────
    "AGO": "m49/017",  # Angola
    "CMR": "m49/017",  # Cameroon
    "CAF": "m49/017",  # Central African Republic
    "TCD": "m49/017",  # Chad
    "COG": "m49/017",  # Congo
    "COD": "m49/017",  # DR Congo
    "GNQ": "m49/017",  # Equatorial Guinea
    "GAB": "m49/017",  # Gabon
    "STP": "m49/017",  # São Tomé and Príncipe
    # ── Southern Africa (m49/018) ────────────────────────────────────────────
    "BWA": "m49/018",  # Botswana
    "SWZ": "m49/018",  # Eswatini
    "LSO": "m49/018",  # Lesotho
    "NAM": "m49/018",  # Namibia
    "ZAF": "m49/018",  # South Africa
    # ── Western Africa (m49/011) ─────────────────────────────────────────────
    "BEN": "m49/011",  # Benin
    "BFA": "m49/011",  # Burkina Faso
    "CPV": "m49/011",  # Cabo Verde
    "CIV": "m49/011",  # Côte d'Ivoire
    "GMB": "m49/011",  # Gambia
    "GHA": "m49/011",  # Ghana
    "GIN": "m49/011",  # Guinea
    "GNB": "m49/011",  # Guinea-Bissau
    "LBR": "m49/011",  # Liberia
    "MLI": "m49/011",  # Mali
    "MRT": "m49/011",  # Mauritania
    "NER": "m49/011",  # Niger
    "NGA": "m49/011",  # Nigeria
    "SHN": "m49/011",  # Saint Helena, Ascension and Tristan da Cunha
    "SEN": "m49/011",  # Senegal
    "SLE": "m49/011",  # Sierra Leone
    "TGO": "m49/011",  # Togo
    # ── Caribbean (m49/029) ──────────────────────────────────────────────────
    "AIA": "m49/029",  # Anguilla
    "ATG": "m49/029",  # Antigua and Barbuda
    "ABW": "m49/029",  # Aruba
    "BHS": "m49/029",  # Bahamas
    "BRB": "m49/029",  # Barbados
    "BLM": "m49/029",  # Saint Barthélemy
    "VGB": "m49/029",  # British Virgin Islands
    "CYM": "m49/029",  # Cayman Islands
    "CUB": "m49/029",  # Cuba
    "CUW": "m49/029",  # Curaçao
    "DMA": "m49/029",  # Dominica
    "DOM": "m49/029",  # Dominican Republic
    "GRD": "m49/029",  # Grenada
    "GLP": "m49/029",  # Guadeloupe
    "HTI": "m49/029",  # Haiti
    "JAM": "m49/029",  # Jamaica
    "MTQ": "m49/029",  # Martinique
    "MSR": "m49/029",  # Montserrat
    "ANT": "m49/029",  # Netherlands Antilles (legacy)
    "PRI": "m49/029",  # Puerto Rico
    "KNA": "m49/029",  # Saint Kitts and Nevis
    "LCA": "m49/029",  # Saint Lucia
    "MAF": "m49/029",  # Saint Martin (French)
    "VCT": "m49/029",  # Saint Vincent and the Grenadines
    "SXM": "m49/029",  # Sint Maarten
    "TTO": "m49/029",  # Trinidad and Tobago
    "TCA": "m49/029",  # Turks and Caicos Islands
    "VIR": "m49/029",  # United States Virgin Islands
    "BES": "m49/029",  # Bonaire, Sint Eustatius and Saba
    # ── Central America (m49/013) ────────────────────────────────────────────
    "BLZ": "m49/013",  # Belize
    "CRI": "m49/013",  # Costa Rica
    "SLV": "m49/013",  # El Salvador
    "GTM": "m49/013",  # Guatemala
    "HND": "m49/013",  # Honduras
    "MEX": "m49/013",  # Mexico
    "NIC": "m49/013",  # Nicaragua
    "PAN": "m49/013",  # Panama
    # ── South America (reused continent Q18) ─────────────────────────────────
    "ARG": "wikidataId/Q18",  # Argentina
    "BOL": "wikidataId/Q18",  # Bolivia
    "BVT": "wikidataId/Q18",  # Bouvet Island
    "BRA": "wikidataId/Q18",  # Brazil
    "CHL": "wikidataId/Q18",  # Chile
    "COL": "wikidataId/Q18",  # Colombia
    "ECU": "wikidataId/Q18",  # Ecuador
    "FLK": "wikidataId/Q18",  # Falkland Islands (Malvinas)
    "GUF": "wikidataId/Q18",  # French Guiana
    "GUY": "wikidataId/Q18",  # Guyana
    "PRY": "wikidataId/Q18",  # Paraguay
    "PER": "wikidataId/Q18",  # Peru
    "SGS": "wikidataId/Q18",  # South Georgia and South Sandwich Islands
    "SUR": "wikidataId/Q18",  # Suriname
    "URY": "wikidataId/Q18",  # Uruguay
    "VEN": "wikidataId/Q18",  # Venezuela
    # ── Northern America (reused continent Q49) ───────────────────────────────
    "BMU": "wikidataId/Q49",  # Bermuda
    "CAN": "wikidataId/Q49",  # Canada
    "GRL": "wikidataId/Q49",  # Greenland
    "SPM": "wikidataId/Q49",  # Saint Pierre and Miquelon
    "USA": "wikidataId/Q49",  # United States
    # ── Central Asia (m49/143) ───────────────────────────────────────────────
    "KAZ": "m49/143",  # Kazakhstan
    "KGZ": "m49/143",  # Kyrgyzstan
    "TJK": "m49/143",  # Tajikistan
    "TKM": "m49/143",  # Turkmenistan
    "UZB": "m49/143",  # Uzbekistan
    # ── Eastern Asia (m49/030) ───────────────────────────────────────────────
    "CHN": "m49/030",  # China
    "HKG": "m49/030",  # Hong Kong
    "JPN": "m49/030",  # Japan
    "MAC": "m49/030",  # Macao
    "MNG": "m49/030",  # Mongolia
    "PRK": "m49/030",  # North Korea
    "KOR": "m49/030",  # Republic of Korea
    "TWN": "m49/030",  # Taiwan
    # ── South-eastern Asia (m49/035) ─────────────────────────────────────────
    "BRN": "m49/035",  # Brunei
    "KHM": "m49/035",  # Cambodia
    "TLS": "m49/035",  # Timor-Leste
    "IDN": "m49/035",  # Indonesia
    "LAO": "m49/035",  # Lao PDR
    "MYS": "m49/035",  # Malaysia
    "MMR": "m49/035",  # Myanmar
    "PHL": "m49/035",  # Philippines
    "SGP": "m49/035",  # Singapore
    "THA": "m49/035",  # Thailand
    "VNM": "m49/035",  # Viet Nam
    # ── Southern Asia (m49/034) ──────────────────────────────────────────────
    "AFG": "m49/034",  # Afghanistan
    "BGD": "m49/034",  # Bangladesh
    "BTN": "m49/034",  # Bhutan
    "IND": "m49/034",  # India
    "IRN": "m49/034",  # Iran
    "MDV": "m49/034",  # Maldives
    "NPL": "m49/034",  # Nepal
    "PAK": "m49/034",  # Pakistan
    "LKA": "m49/034",  # Sri Lanka
    # ── Western Asia (m49/145) ───────────────────────────────────────────────
    "ARM": "m49/145",  # Armenia
    "AZE": "m49/145",  # Azerbaijan
    "BHR": "m49/145",  # Bahrain
    "CYP": "m49/145",  # Cyprus
    "GEO": "m49/145",  # Georgia
    "IRQ": "m49/145",  # Iraq
    "ISR": "m49/145",  # Israel
    "JOR": "m49/145",  # Jordan
    "KWT": "m49/145",  # Kuwait
    "LBN": "m49/145",  # Lebanon
    "OMN": "m49/145",  # Oman
    "PSE": "m49/145",  # State of Palestine
    "QAT": "m49/145",  # Qatar
    "SAU": "m49/145",  # Saudi Arabia
    "SYR": "m49/145",  # Syria
    "TUR": "m49/145",  # Türkiye
    "ARE": "m49/145",  # UAE
    "YEM": "m49/145",  # Yemen
    # ── Eastern Europe (m49/151) ─────────────────────────────────────────────
    "BLR": "m49/151",  # Belarus
    "BGR": "m49/151",  # Bulgaria
    "CZE": "m49/151",  # Czechia
    "HUN": "m49/151",  # Hungary
    "POL": "m49/151",  # Poland
    "MDA": "m49/151",  # Moldova
    "ROU": "m49/151",  # Romania
    "RUS": "m49/151",  # Russian Federation
    "SVK": "m49/151",  # Slovakia
    "UKR": "m49/151",  # Ukraine
    # ── Northern Europe (m49/154) ────────────────────────────────────────────
    "ALA": "m49/154",  # Åland Islands
    "DNK": "m49/154",  # Denmark
    "EST": "m49/154",  # Estonia
    "FRO": "m49/154",  # Faroe Islands
    "FIN": "m49/154",  # Finland
    "GBR": "m49/154",  # United Kingdom
    "GGY": "m49/154",  # Guernsey
    "ISL": "m49/154",  # Iceland
    "IRL": "m49/154",  # Ireland
    "IMN": "m49/154",  # Isle of Man
    "JEY": "m49/154",  # Jersey
    "LVA": "m49/154",  # Latvia
    "LTU": "m49/154",  # Lithuania
    "NOR": "m49/154",  # Norway
    "SJM": "m49/154",  # Svalbard and Jan Mayen
    "SWE": "m49/154",  # Sweden
    # ── Southern Europe (m49/039) ────────────────────────────────────────────
    "ALB": "m49/039",  # Albania
    "AND": "m49/039",  # Andorra
    "BIH": "m49/039",  # Bosnia and Herzegovina
    "HRV": "m49/039",  # Croatia
    "GIB": "m49/039",  # Gibraltar
    "GRC": "m49/039",  # Greece
    "VAT": "m49/039",  # Holy See (Vatican)
    "ITA": "m49/039",  # Italy
    "MLT": "m49/039",  # Malta
    "MNE": "m49/039",  # Montenegro
    "MKD": "m49/039",  # North Macedonia
    "PRT": "m49/039",  # Portugal
    "SMR": "m49/039",  # San Marino
    "SRB": "m49/039",  # Serbia
    "SVN": "m49/039",  # Slovenia
    "ESP": "m49/039",  # Spain
    # ── Western Europe (m49/155) ─────────────────────────────────────────────
    "AUT": "m49/155",  # Austria
    "BEL": "m49/155",  # Belgium
    "FRA": "m49/155",  # France
    "DEU": "m49/155",  # Germany
    "LIE": "m49/155",  # Liechtenstein
    "LUX": "m49/155",  # Luxembourg
    "MCO": "m49/155",  # Monaco
    "NLD": "m49/155",  # Netherlands
    "CHE": "m49/155",  # Switzerland
    # ── Australia and New Zealand (m49/053) ──────────────────────────────────
    "AUS": "m49/053",  # Australia
    "CXR": "m49/053",  # Christmas Island
    "CCK": "m49/053",  # Cocos (Keeling) Islands
    "HMD": "m49/053",  # Heard Island and McDonald Islands
    "NZL": "m49/053",  # New Zealand
    "NFK": "m49/053",  # Norfolk Island
    # ── Melanesia (m49/054) ──────────────────────────────────────────────────
    "FJI": "m49/054",  # Fiji
    "NCL": "m49/054",  # New Caledonia
    "PNG": "m49/054",  # Papua New Guinea
    "SLB": "m49/054",  # Solomon Islands
    "VUT": "m49/054",  # Vanuatu
    # ── Micronesia (m49/057) ─────────────────────────────────────────────────
    "GUM": "m49/057",  # Guam
    "KIR": "m49/057",  # Kiribati
    "MHL": "m49/057",  # Marshall Islands
    "FSM": "m49/057",  # Micronesia (Federated States)
    "NRU": "m49/057",  # Nauru
    "MNP": "m49/057",  # Northern Mariana Islands
    "PLW": "m49/057",  # Palau
    "UMI": "m49/057",  # United States Minor Outlying Islands
    # ── Polynesia (m49/061) ──────────────────────────────────────────────────
    "ASM": "m49/061",  # American Samoa
    "COK": "m49/061",  # Cook Islands
    "PYF": "m49/061",  # French Polynesia
    "NIU": "m49/061",  # Niue
    "PCN": "m49/061",  # Pitcairn
    "WSM": "m49/061",  # Samoa
    "TKL": "m49/061",  # Tokelau
    "TON": "m49/061",  # Tonga
    "TUV": "m49/061",  # Tuvalu
    "WLF": "m49/061",  # Wallis and Futuna
    # ── Antarctica (Q51) — no M.49 sub-region; omitted (no countries under it)
}
